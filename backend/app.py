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
TOKENS_FILENAME = "tokens.json"
HAIKU_PRICE_INPUT_PER_TOKEN = 0.0000008    # USD/token  ($0.80/MTok)
HAIKU_PRICE_OUTPUT_PER_TOKEN = 0.000004    # USD/token  ($4.00/MTok)
EUR_RATE = 0.92

_last_run_stats: dict = {"input_tokens": 0, "output_tokens": 0, "calls": 0}


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


def chunk_text(text: str) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + CHUNK_MAX_WORDS]) for i in range(0, len(words), CHUNK_MAX_WORDS)]


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
        "Identifiziere alle relevanten Fachbegriffe, Personen, Konzepte, Theorien und Methoden.\n"
        "Gib eine JSON-Liste zurück. Format:\n"
        '[{"canonical": "Kanonische Form", "aliases": ["Variante1", "Variante2"]}, ...]\n'
        "Regeln:\n"
        "- Nur Begriffe die wirklich im Text vorkommen\n"
        "- canonical = Nominativ Singular (Grundform)\n"
        "- aliases = ALLE im Text vorkommenden Flexionen: Genitiv (-s/-es), Plural (-e/-en/-er/-ø), Akkusativ, Dativ\n"
        "  Beispiel: canonical 'Denkraum' → aliases ['Denkraum', 'Denkraums', 'Denkraumes', 'Denkräume', 'Denkräumen']\n"
        "- Auch fremdsprachige Varianten und Synonyme in aliases aufnehmen\n"
        "- Füge canonical immer auch in aliases ein\n"
        "- Antworte NUR mit dem JSON-Array, ohne Erklärungen\n\n"
        f"Text:\n{chunk}"
    )


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


def get_stub_folder(name: str) -> str:
    parts = name.split()
    if (len(parts) == 2 and
            all(p[0].isupper() and p.replace('-', '').isalpha() for p in parts)):
        return "Personen"
    if any(kw in name.lower() for kw in _METHOD_KEYWORDS):
        return "Methoden"
    return "Konzepte"


def create_stubs(vault_path: str, wikilinks: set[str], source_filename: str) -> tuple[int, int]:
    vault = Path(vault_path)
    today = datetime.date.today().isoformat()
    source_stem = Path(source_filename).stem
    existing_names = {f.stem for f in vault.rglob("*.md")}
    created = 0
    existing = 0
    for name in sorted(wikilinks):
        safe = re.sub(r'[<>:"/\\|?*\n\r]', '', name).strip()
        if not safe or len(safe) < 2:
            continue
        if safe in existing_names:
            existing += 1
            continue
        folder = get_stub_folder(safe)
        stub_dir = vault / folder
        stub_dir.mkdir(exist_ok=True)
        content = (
            f"---\ntitle: {safe}\ntags:\n  - concept\ncreated: {today}\n---\n"
            f"# {safe}\n\n"
            f"> Stub — noch kein Inhalt. Verlinkt in: [[{source_stem}]]\n"
        )
        (stub_dir / f"{safe}.md").write_text(content, encoding="utf-8")
        existing_names.add(safe)
        created += 1
    return created, existing


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


MNEME_VERSION = "1.8.0"


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
    }


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

    chunks = chunk_text(full_text)
    vault_links = extract_wikilinks(vault_path)
    base_links = load_psych_base_links()

    requested = model if model != "auto" else cfg.get("default_model", "auto")
    ollama_model = cfg.get("ollama_model", "llama3.1:8b")
    api_key = get_anthropic_key(cfg)

    if requested == "auto":
        use_model = "claude" if api_key.strip() else "ollama"
    elif requested == "claude":
        if not api_key.strip():
            raise HTTPException(status_code=400, detail="claude_api_key_missing")
        use_model = "claude"
    else:
        use_model = "ollama"

    _last_run_stats.update({"input_tokens": 0, "output_tokens": 0, "calls": 0})
    logger.info("MODEL: %s | FILE: %s | CHUNKS: %d", use_model, file.filename, len(chunks))

    async def run_call(p: str, max_tokens: int = 1024) -> str:
        if use_model == "claude":
            try:
                return call_claude(api_key, p, max_tokens=max_tokens)
            except Exception as e:
                logger.warning("Claude fehlgeschlagen (%s), Fallback auf Ollama", e)
                if not await ollama_available(ollama_model):
                    raise HTTPException(status_code=503, detail="claude_error_and_ollama_unavailable")
                return await call_ollama(ollama_model, p)
        else:
            if not await ollama_available(ollama_model):
                raise HTTPException(status_code=503, detail="ollama_unavailable")
            return await call_ollama(ollama_model, p)

    # Phase 0: Token-Cache laden (bekannte Begriffe aus früheren Runs)
    token_cache = load_token_cache(vault_path)
    cached_terms = [{"canonical": c, "aliases": aliases} for c, aliases in token_cache.items()]
    logger.info("TOKEN CACHE: %d bekannte Begriffe", len(cached_terms))

    # Phase 1a — Metadata
    meta_raw = await run_call(build_metadata_prompt(full_text), max_tokens=256)
    meta = parse_metadata(meta_raw)
    logger.info("METADATA: %s", meta)

    # Phase 1b — KI erkennt neue Begriffe pro Chunk
    term_lists = []
    for i, chunk in enumerate(chunks):
        raw = await run_call(build_recognition_prompt(chunk), max_tokens=1024)
        terms = parse_terms(raw)
        logger.info("CHUNK %d/%d: %d Begriffe erkannt", i + 1, len(chunks), len(terms))
        term_lists.append(terms)

    all_terms = merge_terms([cached_terms] + term_lists, base_links, vault_links, full_text)
    logger.info("TERMS GESAMT: %d (davon %d aus Cache)", len(all_terms), len(cached_terms))

    # Phase 2 — Python ersetzt Begriffe im Originaltext (0 weitere API-Calls)
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
    output_path = Path(vault_path) / output_filename
    output_path.write_text(result, encoding="utf-8")

    # Stubs für neue Wikilinks anlegen
    found_links = set(re.findall(r'\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]', result))
    stubs_created, stubs_existing = create_stubs(vault_path, found_links, output_filename)
    logger.info("STUBS: %d erstellt, %d existieren", stubs_created, stubs_existing)

    return {
        "ok": True,
        "filename": output_filename,
        "model_used": use_model,
        "wikilinks_total": total_links,
        "chunks": len(chunks),
        "stubs_created": stubs_created,
        "stubs_existing": stubs_existing,
    }
