import datetime
import json
import logging
import os
import re
import textwrap
from logging.handlers import RotatingFileHandler
from pathlib import Path

import anthropic
import fitz  # pymupdf
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")

LOG_PATH = Path(__file__).parent / "mneme.log"
_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("mneme")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "vault_path": "",
    "default_model": "auto",
    "claude_api_key": "",
    "ollama_model": "llama3.1:8b",
}

OLLAMA_BASE_URL = "http://localhost:11434"
CHUNK_MAX_WORDS = 2000
CHUNK_MAX_WORDS_OLLAMA = 800
TOKENS_FILENAME = "tokens.json"
HAIKU_PRICE_INPUT_PER_TOKEN = 0.0000008    # USD/token  ($0.80/MTok)
HAIKU_PRICE_OUTPUT_PER_TOKEN = 0.000004    # USD/token  ($4.00/MTok)
EUR_RATE = 0.92

_last_run_stats: dict = {"input_tokens": 0, "output_tokens": 0, "calls": 0,
                         "phase1_model": "", "meta_model": ""}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def chunk_text(text: str, max_words: int = CHUNK_MAX_WORDS) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


PSYCH_BASE_PATH = Path(__file__).parent / "psych_base_links.json"


def load_psych_base_links() -> list[str]:
    try:
        return json.loads(PSYCH_BASE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def extract_wikilinks(vault_path: str) -> list[str]:
    links = set()
    pattern = re.compile(r"\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]")
    for md_file in Path(vault_path).rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            for match in pattern.finditer(content):
                links.add(match.group(1).strip())
        except Exception:
            pass
    return sorted(links)


async def ollama_available(model: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if r.status_code != 200:
                return False
            tags = r.json().get("models", [])
            return any(t.get("name", "").split(":")[0] == model.split(":")[0] for t in tags)
    except Exception:
        return False


async def call_ollama(model: str, prompt: str) -> str:
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        r.raise_for_status()
        return r.json()["response"]


def get_anthropic_key(cfg: dict) -> str:
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    return os.getenv("ANTHROPIC_API_KEY", "") or cfg.get("claude_api_key", "")


def call_claude(api_key: str, prompt: str, max_tokens: int = 8192) -> str:
    global _last_run_stats
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    _last_run_stats["input_tokens"] += message.usage.input_tokens
    _last_run_stats["output_tokens"] += message.usage.output_tokens
    _last_run_stats["calls"] += 1
    return message.content[0].text


def build_metadata_prompt(text: str) -> str:
    return textwrap.dedent(f"""
        Extrahiere aus dem folgenden wissenschaftlichen Text:
        - title: Titel des Werks
        - author: Autor(en)
        - year: Erscheinungsjahr (4-stellig)

        Antworte NUR als JSON: {{"title": "...", "author": "...", "year": "..."}}
        Wenn ein Feld nicht erkennbar ist: leerer String.

        Text:
        {text[:3000]}
    """).strip()


def build_recognition_prompt(chunk: str) -> str:
    return (
        "Analysiere den folgenden wissenschaftlichen Text.\n"
        "Identifiziere ALLE verlinkungswürdigen Begriffe. Im Zweifel: taggen. Lieber zu viele als zu wenige.\n"
        "Erfasse ausdrücklich:\n"
        "- Alle Eigennamen (auch Nachname allein wenn eindeutig: 'Warburg', 'Imdahl')\n"
        "- Alle Fachbegriffe auch scheinbar allgemeine: 'Wahrnehmung', 'Reflexion', 'Emotion' sind Fachbegriffe!\n"
        "- Institutionen, Zeitschriften, Werktitel\n"
        "- Komposita wenn sie als Konzept fungieren\n"
        "Gib eine JSON-Liste zurück. Format:\n"
        '[{"canonical": "Kanonische Form", "aliases": ["Variante1", "Variante2"]}, ...]\n'
        "- canonical = Nominativ Singular (Grundform)\n"
        "- aliases = ALLE Flexionen im Text (Genitiv, Plural, Kasus) + Synonyme + fremdsprachige Varianten\n"
        "  Beispiel: canonical 'Denkraum' → aliases ['Denkraum', 'Denkraums', 'Denkräume', 'Denkräumen']\n"
        "- Füge canonical immer auch in aliases ein\n"
        "- Antworte NUR mit dem JSON-Array, ohne Erklärungen\n\n"
        f"Text:\n{chunk}"
    )


def build_recognition_prompt_ollama(chunk: str) -> str:
    return (
        "Liste alle relevanten Begriffe in diesem wissenschaftlichen Text.\n"
        "Erfasse: Personen (auch nur Nachnamen), Konzepte, Fachbegriffe, Theorien, Institutionen.\n"
        "Im Zweifel: aufnehmen.\n"
        "Antworte NUR mit den Begriffen, kommagetrennt oder einer pro Zeile, kein anderer Text.\n\n"
        f"Text:\n{chunk}"
    )


def parse_terms_simple(raw: str) -> list[dict]:
    """Parse plain-text term list (Ollama output: comma or newline separated)."""
    result = []
    seen: set[str] = set()
    for part in re.split(r'[,\n]', raw):
        term = re.sub(r'^[\s\-•–*#\d.]+', '', part).strip()
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            result.append({"canonical": term, "aliases": [term]})
    return result


def extract_metadata_regex(text: str) -> dict:
    """Fallback metadata extraction without API."""
    year_m = re.search(r'\b(19[0-9]{2}|20[0-2][0-9])\b', text[:3000])
    year = year_m.group(1) if year_m else ""
    title = ""
    for line in text[:600].split('\n'):
        line = line.strip()
        if 10 <= len(line) <= 150 and not line.startswith('http'):
            title = line
            break
    return {"title": title, "author": "", "year": year}


def parse_terms(raw: str) -> list[dict]:
    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            items = json.loads(m.group())
            result = []
            for t in items:
                if not isinstance(t, dict) or "canonical" not in t:
                    continue
                canonical = str(t["canonical"]).strip()
                aliases = [str(a).strip() for a in t.get("aliases", [])]
                if canonical not in aliases:
                    aliases.insert(0, canonical)
                result.append({"canonical": canonical, "aliases": aliases})
            return result
    except Exception:
        pass
    return []


_UMLAUT = {'a': 'ä', 'o': 'ö', 'u': 'ü', 'A': 'Ä', 'O': 'Ö', 'U': 'Ü'}
_SUFFIXES = ['s', 'es', 'e', 'en', 'er', 'ern', 'em']


def expand_german_inflections(canonical: str, full_text: str = "") -> set[str]:
    forms = {canonical}
    if len(canonical) < 4:
        return forms
    c = canonical
    for suffix in _SUFFIXES:
        forms.add(c + suffix)
    # Umlaut: replace last a/o/u in stem, then add plural suffixes
    for i in range(len(c) - 1, -1, -1):
        if c[i] in _UMLAUT:
            stem = c[:i] + _UMLAUT[c[i]] + c[i + 1:]
            forms.add(stem)
            for suffix in _SUFFIXES:
                forms.add(stem + suffix)
            break
    # Filter to only forms that actually occur in text (prevents "Soziologiee" etc.)
    if full_text:
        text_lower = full_text.lower()
        return {f for f in forms if f == canonical or f.lower() in text_lower}
    return forms


def merge_terms(term_lists: list[list[dict]], base_links: list[str], vault_links: list[str], full_text: str = "") -> list[dict]:
    canonical_map: dict[str, set] = {}
    for terms in term_lists:
        for t in terms:
            c = t["canonical"]
            aliases = set(t.get("aliases", [c]))
            aliases.update(expand_german_inflections(c, full_text))
            canonical_map.setdefault(c, set()).update(aliases)
    for link in base_links + vault_links:
        inflected = expand_german_inflections(link, full_text)
        if link in canonical_map:
            canonical_map[link].update(inflected)
        else:
            canonical_map[link] = inflected
    return [
        {"canonical": c, "aliases": sorted(aliases)}
        for c, aliases in canonical_map.items()
    ]


def load_token_cache(vault_path: str) -> dict[str, list[str]]:
    path = Path(vault_path) / TOKENS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("_mneme_version") != MNEME_VERSION:
            return {}
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def save_token_cache(vault_path: str, terms: list[dict]):
    path = Path(vault_path) / TOKENS_FILENAME
    cache = load_token_cache(vault_path)
    for term in terms:
        canonical = term["canonical"]
        existing = set(cache.get(canonical, []))
        existing.update(term.get("aliases", [canonical]))
        cache[canonical] = sorted(existing)
    cache["_mneme_version"] = MNEME_VERSION
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _tag_line(line: str, alias_lower_map: dict, combined_pattern) -> str:
    def replacer(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("[["):
            return s
        canonical = alias_lower_map.get(s.lower())
        if canonical is None:
            return s
        return f"[[{canonical}]]" if s == canonical else f"[[{canonical}|{s}]]"
    return combined_pattern.sub(replacer, line)


def apply_wikilinks(text: str, terms: list[dict]) -> str:
    # Isolate YAML frontmatter — never tag inside it
    yaml_end = 0
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            yaml_end = end + 5
    yaml_part = text[:yaml_end]
    body = text[yaml_end:]

    # Build alias → canonical map, ignore very short strings
    alias_lower_map: dict[str, str] = {}
    for term in terms:
        canonical = term["canonical"]
        for alias in term.get("aliases", [canonical]):
            if len(alias) >= 4:
                alias_lower_map[alias.lower()] = canonical

    if not alias_lower_map:
        return text

    # Longest-match-first: longer aliases take precedence (e.g. "Cognitive Load Theory" > "Theorie")
    sorted_aliases = sorted(alias_lower_map.keys(), key=len, reverse=True)
    link_pat = r'\[\[.*?\]\]'
    alias_pats = [r'\b' + re.escape(a) + r'\b' for a in sorted_aliases]
    combined_pattern = re.compile('(' + '|'.join([link_pat] + alias_pats) + ')', re.IGNORECASE)

    result_lines = []
    for line in body.split('\n'):
        if line.startswith(('#', '>')):
            result_lines.append(line)
        else:
            result_lines.append(_tag_line(line, alias_lower_map, combined_pattern))

    return yaml_part + '\n'.join(result_lines)


def parse_metadata(raw: str) -> dict:
    try:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass
    return {"title": "", "author": "", "year": ""}


def derive_output_filename(meta: dict, fallback: str) -> str:
    author = meta.get("author", "").split(",")[0].strip()[:30]
    year = meta.get("year", "")
    title = meta.get("title", "").strip()[:30]
    parts = [p for p in [author, year, title] if p]
    raw_name = "-".join(parts) if parts else fallback.replace(".pdf", "")
    safe_name = re.sub(r'[<>:"/\\|?*]', "", raw_name).strip("-").strip()
    return f"{safe_name}.md"


_METHOD_KEYWORDS = {"methode", "analyse", "forschung", "ansatz", "verfahren"}
_NOT_PERSON_WORDS = {
    "soziale", "sozial", "medien", "soziologie", "soziologisch",
    "sozialwissenschaft", "institut", "universität", "university",
    "methode", "analyse", "forschung", "theorie", "modell",
    "gesellschaft", "wissenschaft", "bildung", "kunst", "raum",
    "kultur", "politik", "system", "netzwerk", "plattform",
}


def should_create_stub(name: str) -> bool:
    if len(name.strip()) < 2:
        return False
    # Skip single lowercase words (adjectives/inflections like "bildliche", "affektive")
    if ' ' not in name and name[0].islower():
        return False
    return True


def get_stub_folder(name: str) -> str:
    parts = name.split()
    if (len(parts) >= 2 and
            all(p[0].isupper() and p.replace('-', '').isalpha() for p in parts) and
            not any(p.lower() in _NOT_PERSON_WORDS for p in parts)):
        return "Personen"
    if any(kw in name.lower() for kw in _METHOD_KEYWORDS):
        return "Methoden"
    return "Konzepte"


def create_stubs(vault_path: str, wikilinks: set[str], source_filename: str) -> tuple[int, int]:
    vault = Path(vault_path)
    today = datetime.date.today().isoformat()
    existing_names = {f.stem for f in vault.rglob("*.md")}
    created = 0
    existing = 0
    for name in sorted(wikilinks):
        safe = re.sub(r'[<>:"/\\|?*\n\r]', '', name).strip()
        if not safe or not should_create_stub(safe):
            continue
        if safe in existing_names:
            existing += 1
            continue
        folder = get_stub_folder(safe)
        stub_dir = vault / folder
        stub_dir.mkdir(exist_ok=True)
        content = f"---\ntitle: {safe}\ntags:\n  - concept\ncreated: {today}\n---\n"
        (stub_dir / f"{safe}.md").write_text(content, encoding="utf-8")
        existing_names.add(safe)
        created += 1
    return created, existing


def cleanup_existing_stubs(vault_path: str) -> int:
    cleaned = 0
    for folder in ("Personen", "Methoden", "Konzepte"):
        for md_file in (Path(vault_path) / folder).glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if not content.startswith("---\n") or "- concept" not in content[:300]:
                    continue
                end = content.find("\n---\n", 4)
                if end == -1:
                    continue
                frontmatter = content[:end + 5]
                if content.rstrip() == frontmatter.rstrip():
                    continue
                md_file.write_text(frontmatter, encoding="utf-8")
                cleaned += 1
            except Exception:
                pass
    return cleaned


def find_duplicate_pairs(cache: dict) -> list[dict]:
    terms = [k for k in cache if not k.startswith("_")]
    pairs = []
    for i in range(len(terms)):
        a_l = terms[i].lower()
        for j in range(i + 1, len(terms)):
            b_l = terms[j].lower()
            if (re.search(r'\b' + re.escape(a_l) + r'\b', b_l) or
                    re.search(r'\b' + re.escape(b_l) + r'\b', a_l)):
                pairs.append({"a": terms[i], "b": terms[j]})
                if len(pairs) >= 100:
                    return pairs
    return pairs


def rename_wikilinks_in_vault(vault_path: str, old_name: str, new_name: str) -> int:
    pattern = re.compile(r'\[\[' + re.escape(old_name) + r'(?:\|([^\]]+))?\]\]')
    updated = 0
    for md_file in Path(vault_path).rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            def repl(m: re.Match) -> str:
                display = m.group(1)
                return f"[[{new_name}|{display}]]" if display else f"[[{new_name}|{old_name}]]"
            new_content = pattern.sub(repl, content)
            if new_content != content:
                md_file.write_text(new_content, encoding="utf-8")
                updated += 1
        except Exception:
            pass
    return updated


def count_backlinks(vault_path: str, term: str) -> int:
    pat = re.compile(r'\[\[' + re.escape(term))
    count = 0
    for md_file in Path(vault_path).rglob("*.md"):
        try:
            if pat.search(md_file.read_text(encoding="utf-8")):
                count += 1
        except Exception:
            pass
    return count


# --- Endpoints ---

@app.get("/")
def root():
    return FileResponse(Path(__file__).parent.parent / "frontend" / "index.html")


@app.get("/config")
def get_config():
    cfg = load_config()
    cfg.pop("claude_api_key", None)
    return cfg


@app.get("/config/has_api_key")
def has_api_key():
    cfg = load_config()
    return {"has_key": bool(get_anthropic_key(cfg).strip())}


class ConfigUpdate(BaseModel):
    vault_path: str | None = None
    default_model: str | None = None
    claude_api_key: str | None = None
    ollama_model: str | None = None


class MergeRequest(BaseModel):
    keep: str
    remove: str


@app.post("/config")
def update_config(update: ConfigUpdate):
    cfg = load_config()
    if update.vault_path is not None:
        cfg["vault_path"] = update.vault_path
    if update.default_model is not None:
        cfg["default_model"] = update.default_model
    if update.claude_api_key is not None:
        cfg["claude_api_key"] = update.claude_api_key
    if update.ollama_model is not None:
        cfg["ollama_model"] = update.ollama_model
    save_config(cfg)
    return {"ok": True}


MNEME_VERSION = "2.0.0"


@app.get("/version")
def get_version():
    return {"version": MNEME_VERSION}


@app.get("/last_run_cost")
def last_run_cost():
    inp = _last_run_stats["input_tokens"]
    out = _last_run_stats["output_tokens"]
    cost_usd = inp * HAIKU_PRICE_INPUT_PER_TOKEN + out * HAIKU_PRICE_OUTPUT_PER_TOKEN
    cost_eur = cost_usd * EUR_RATE
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cost_usd": round(cost_usd, 5),
        "cost_eur": round(cost_eur, 5),
        "calls": _last_run_stats["calls"],
        "phase1_model": _last_run_stats.get("phase1_model", ""),
        "meta_model": _last_run_stats.get("meta_model", ""),
    }


@app.get("/tokens")
def get_tokens():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        return {"tokens": {}, "duplicates": [], "count": 0}
    cache = load_token_cache(vault_path)
    return {"tokens": cache, "duplicates": find_duplicate_pairs(cache), "count": len(cache)}


@app.post("/tokens/merge")
def merge_token_terms(req: MergeRequest):
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path:
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    tok_path = Path(vault_path) / TOKENS_FILENAME
    try:
        data = json.loads(tok_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=404, detail="tokens_not_found")
    if req.keep not in data or req.remove not in data:
        raise HTTPException(status_code=404, detail="term_not_found")
    keep_al = set(data[req.keep]) if isinstance(data[req.keep], list) else set()
    remove_al = set(data[req.remove]) if isinstance(data[req.remove], list) else set()
    data[req.keep] = sorted(keep_al | remove_al | {req.remove})
    del data[req.remove]
    tok_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Replace all [[req.remove]] links throughout the vault
    files_updated = rename_wikilinks_in_vault(vault_path, req.remove, req.keep)
    # Delete stub for removed term
    stub_deleted = False
    for folder in ("Personen", "Methoden", "Konzepte"):
        p = Path(vault_path) / folder / f"{req.remove}.md"
        if p.exists():
            p.unlink()
            stub_deleted = True
            break
    backlinks = count_backlinks(vault_path, req.keep)
    return {"ok": True, "stub_deleted": stub_deleted, "files_updated": files_updated, "backlinks": backlinks}


@app.post("/stubs/cleanup")
def cleanup_stubs_endpoint():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    cleaned = cleanup_existing_stubs(vault_path)
    return {"ok": True, "cleaned": cleaned}


@app.get("/vault/tree")
def get_vault_tree():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        return {"tree": [], "total": 0}

    def build_tree(path: Path, depth: int = 0) -> list:
        if depth >= 3:
            return []
        items = []
        try:
            for entry in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if entry.name.startswith('.') or entry.name == TOKENS_FILENAME:
                    continue
                if entry.is_dir():
                    children = build_tree(entry, depth + 1)
                    if children:
                        items.append({"name": entry.name, "type": "dir", "children": children})
                elif entry.suffix == '.md':
                    items.append({
                        "name": entry.name,
                        "type": "file",
                        "path": str(entry.relative_to(Path(vault_path))),
                    })
        except PermissionError:
            pass
        return items

    tree = build_tree(Path(vault_path))
    total = sum(1 for _ in Path(vault_path).rglob("*.md"))
    return {"tree": tree, "total": total}


@app.get("/ollama/status")
async def ollama_status():
    cfg = load_config()
    model = cfg.get("ollama_model", "llama3.1:8b")
    available = await ollama_available(model)
    return {"available": available, "model": model}


@app.get("/wikilinks")
def get_wikilinks():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        return {"links": [], "count": 0}
    links = extract_wikilinks(vault_path)
    return {"links": links, "count": len(links)}


@app.post("/process")
async def resolve_models(requested: str, api_key: str, ollama_model: str) -> tuple[str, str]:
    """Returns (phase1_model, meta_model)."""
    if requested == "claude":
        return "claude", "claude"
    if requested == "ollama":
        return "ollama", "regex"
    # auto
    ollama_ok = await ollama_available(ollama_model)
    phase1 = "ollama" if ollama_ok else "claude"
    meta = "claude" if api_key.strip() else "regex"
    return phase1, meta


async def process_pdf(file: UploadFile = File(...), model: str = "auto"):
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")

    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="empty_file")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = [page.get_text() for page in doc]
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"pdf_parse_error: {e}")

    full_text = "\n\n".join(pages_text).strip()
    if len(full_text) < 100:
        raise HTTPException(status_code=422, detail="scanned_pdf_or_empty")

    vault_links = extract_wikilinks(vault_path)
    base_links = load_psych_base_links()

    requested = model if model != "auto" else cfg.get("default_model", "auto")
    ollama_model = cfg.get("ollama_model", "llama3.1:8b")
    api_key = get_anthropic_key(cfg)

    if requested == "claude" and not api_key.strip():
        raise HTTPException(status_code=400, detail="claude_api_key_missing")

    phase1_model, meta_model = await resolve_models(requested, api_key, ollama_model)
    _last_run_stats.update({"input_tokens": 0, "output_tokens": 0, "calls": 0,
                            "phase1_model": phase1_model, "meta_model": meta_model})
    logger.info("PHASE1: %s | META: %s | FILE: %s", phase1_model, meta_model, file.filename)

    # Phase 0: Token-Cache
    token_cache = load_token_cache(vault_path)
    cached_terms = [{"canonical": c, "aliases": aliases} for c, aliases in token_cache.items()]
    logger.info("TOKEN CACHE: %d bekannte Begriffe", len(cached_terms))

    # Phase 1a — Metadata
    if meta_model == "claude":
        meta = parse_metadata(call_claude(api_key, build_metadata_prompt(full_text), max_tokens=256))
    else:
        meta = extract_metadata_regex(full_text)
    logger.info("METADATA: %s (via %s)", meta, meta_model)

    # Phase 1b — Term recognition (Ollama: kleine Chunks + Plain-Text; Claude: JSON)
    if phase1_model == "ollama":
        if not await ollama_available(ollama_model):
            raise HTTPException(status_code=503, detail="ollama_unavailable")
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS_OLLAMA)
        term_lists = []
        for i, chunk in enumerate(p1_chunks):
            raw = await call_ollama(ollama_model, build_recognition_prompt_ollama(chunk))
            terms = parse_terms_simple(raw)
            logger.info("CHUNK %d/%d [Ollama]: %d Begriffe", i + 1, len(p1_chunks), len(terms))
            term_lists.append(terms)
    else:
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS)
        term_lists = []
        for i, chunk in enumerate(p1_chunks):
            try:
                raw = call_claude(api_key, build_recognition_prompt(chunk), max_tokens=1024)
                terms = parse_terms(raw)
            except Exception as e:
                logger.warning("Claude Phase1 Chunk %d fehlgeschlagen: %s", i + 1, e)
                terms = []
            logger.info("CHUNK %d/%d [Claude]: %d Begriffe", i + 1, len(p1_chunks), len(terms))
            term_lists.append(terms)

    all_terms = merge_terms([cached_terms] + term_lists, base_links, vault_links, full_text)
    logger.info("TERMS GESAMT: %d (davon %d aus Cache)", len(all_terms), len(cached_terms))

    # Phase 2 — Python-Ersetzung
    source_pdf = file.filename or "document.pdf"
    frontmatter = (
        f"---\n"
        f"title: {meta.get('title', '')}\n"
        f"author: {meta.get('author', '')}\n"
        f"year: {meta.get('year', '')}\n"
        f"tags:\n"
        f"  - literature-note\n"
        f"source_pdf: {source_pdf}\n"
        f"mneme_version: {MNEME_VERSION}\n"
        f"---\n\n"
    )
    result = apply_wikilinks(frontmatter + full_text, all_terms)

    total_links = len(re.findall(r"\[\[.+?\]\]", result))
    logger.info("TOTAL LINKS: %d | TERMS: %d | TOKENS in/out: %d/%d",
                total_links, len(all_terms),
                _last_run_stats["input_tokens"], _last_run_stats["output_tokens"])

    save_token_cache(vault_path, all_terms)
    output_filename = derive_output_filename(meta, source_pdf)
    (Path(vault_path) / output_filename).write_text(result, encoding="utf-8")

    found_links = set(re.findall(r'\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]', result))
    stubs_created, stubs_existing = create_stubs(vault_path, found_links, output_filename)
    logger.info("STUBS: %d erstellt, %d existieren", stubs_created, stubs_existing)

    return {
        "ok": True,
        "filename": output_filename,
        "model_used": f"{phase1_model}/{meta_model}",
        "wikilinks_total": total_links,
        "chunks": len(chunks),
        "stubs_created": stubs_created,
        "stubs_existing": stubs_existing,
    }
