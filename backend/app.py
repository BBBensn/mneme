import asyncio
import datetime
import json
import logging
import os
import re
import shutil
import textwrap
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import anthropic
import fitz  # pymupdf
import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
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
JOBS_PATH = Path(__file__).parent / "mneme_jobs.jsonl"

DEFAULT_CONFIG = {
    "vault_path": "",
    "default_model": "auto",
    "claude_api_key": "",
    "ollama_model": "llama3.1:8b",
}

OLLAMA_BASE_URL = "http://localhost:11434"
CHUNK_MAX_WORDS = 2000
CHUNK_MAX_WORDS_OLLAMA = 800
OLLAMA_BATCH_SIZE = 3
TOKENS_FILENAME = "tokens.json"
HAIKU_PRICE_INPUT_PER_TOKEN = 0.0000008       # $0.80/MTok
HAIKU_PRICE_OUTPUT_PER_TOKEN = 0.000004       # $4.00/MTok
HAIKU_PRICE_CACHE_WRITE_PER_TOKEN = 0.000001  # $1.00/MTok
HAIKU_PRICE_CACHE_READ_PER_TOKEN = 0.000000080  # $0.08/MTok
EUR_RATE = 0.92

_last_run_stats: dict = {
    "input_tokens": 0, "output_tokens": 0, "calls": 0,
    "cache_read_tokens": 0, "cache_creation_tokens": 0,
    "phase1_model": "", "meta_model": "",
}
_processing_status: dict = {"active": False, "stage": "", "progress": 0.0,
                             "chunk_current": 0, "chunk_total": 0}
_pending_draft: dict | None = None
_pending_bulk: dict | None = None
_pending_book_pdf: dict[str, dict] = {}  # pdf_id → {"bytes": bytes, "filename": str}
_queue_jobs: dict[str, dict] = {}  # job_id → {status, filename, draft, error, stage}
_pending_book_drafts: dict[str, dict] = {}  # book_id → {folder_name, book_meta, pdf_filename, vault_path, job_ids}
_cancel_flags: set[str] = set()  # job_ids marked for cancellation

_IMPRINT_BLACKLIST = frozenset({
    "abonnement", "anzeigen", "verlag", "issn", "doi", "isbn", "druck",
    "abonnentenbetreuung", "visdp", "erscheinen", "erscheinungsweise",
    "impressum", "redaktion", "herausgeber", "chefredakteur", "erscheinungsort",
    "druckerei", "bezugspreis", "einzelheft", "jahresabonnement",
})
_FIGURE_PREFIXES = ("abbildung", "abb.", "fig.", "tab.", "tabelle")
_NAME_PATTERN = re.compile(
    r'^[A-ZÄÖÜ][a-zäöüß]+(?:[\s\-][A-ZÄÖÜ]\.?)?(?:\s+[A-ZÄÖÜ][a-zäöüß]+)+$'
)


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


def call_claude_with_cache(api_key: str, system_text: str, user_blocks: list[dict],
                            max_tokens: int = 4096) -> str:
    """Call Claude with prompt caching on the system prompt."""
    global _last_run_stats
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_blocks}],
    )
    _last_run_stats["input_tokens"] += message.usage.input_tokens
    _last_run_stats["output_tokens"] += message.usage.output_tokens
    _last_run_stats["calls"] += 1
    _last_run_stats["cache_read_tokens"] += getattr(message.usage, "cache_read_input_tokens", 0) or 0
    _last_run_stats["cache_creation_tokens"] += getattr(message.usage, "cache_creation_input_tokens", 0) or 0
    return message.content[0].text


def yaml_str(s: str) -> str:
    """YAML single-quoted string — safe for citations with commas, quotes, colons."""
    if not s:
        return "''"
    return "'" + s.replace("'", "''") + "'"


def extract_page_text_smart(page) -> str:
    """Extract page text, handling two-column layouts via block position sorting."""
    blocks = page.get_text("blocks")
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
    if len(text_blocks) < 4:
        return page.get_text()
    mid_x = page.rect.width / 2
    left = sorted([b for b in text_blocks if b[0] < mid_x], key=lambda b: b[1])
    right = sorted([b for b in text_blocks if b[0] >= mid_x], key=lambda b: b[1])
    if len(left) < 2 or len(right) < 2:
        return page.get_text()
    # Sanity: both columns should span similar y-range
    y_overlap = min(left[-1][3], right[-1][3]) - max(left[0][1], right[0][1])
    if y_overlap < page.rect.height * 0.25:
        return page.get_text()
    left_text = " ".join(b[4].replace("\n", " ") for b in left)
    right_text = " ".join(b[4].replace("\n", " ") for b in right)
    return left_text + " " + right_text


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
        "Du analysierst einen wissenschaftlichen Text. Liste ALLE relevanten Begriffe auf — sei großzügig.\n"
        "Tagge ALLE der folgenden:\n"
        "- Alle Personennamen (auch Nachnamen allein: 'Warburg', 'Imdahl', 'Husserl', 'Bourdieu')\n"
        "- Alle Institutionen, Zeitschriften, Orte, Verlage\n"
        "- Alle Fachbegriffe — auch wenn scheinbar allgemein: 'Wahrnehmung', 'Reflexion', 'Emotion', "
        "'Gedächtnis', 'Aufmerksamkeit' SIND Fachbegriffe in diesem Kontext!\n"
        "- Alle Konzepte, Theorien, Methoden, Werktitel\n"
        "- Alle Komposita die als eigenständige Konzepte fungieren\n"
        "Gib MINDESTENS 30 Begriffe zurück. Im Zweifel: lieber zu viele als zu wenige.\n"
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
        if len(term) < 4:
            continue
        if not re.search(r'[A-Za-zÄÖÜäöüß]', term):
            continue
        if re.search(r'\d', term):
            continue
        if term.lower() in _IMPRINT_BLACKLIST:
            continue
        if any(term.lower().startswith(p) for p in _FIGURE_PREFIXES):
            continue
        if term not in seen:
            seen.add(term)
            result.append({"canonical": term, "aliases": [term]})
    return result


def extract_metadata_regex(text: str) -> dict:
    """Fallback metadata extraction without API."""
    excerpt = text[:3000]
    lines = [l.strip() for l in excerpt.split('\n') if l.strip()]

    year_m = re.search(r'\b(20[0-2][0-9]|2030|199[0-9])\b', excerpt)
    year = year_m.group(1) if year_m else ""

    author = ""
    for line in lines[:30]:
        if 5 <= len(line) <= 60 and _NAME_PATTERN.match(line):
            author = line
            break

    # Title: longest non-author line in first 200 words
    title = ""
    best_len = 0
    words_seen = 0
    for line in lines:
        words_seen += len(line.split())
        if words_seen > 200:
            break
        if 15 <= len(line) <= 150 and not line.startswith('http') and not _NAME_PATTERN.match(line):
            if len(line) > best_len:
                title = line
                best_len = len(line)

    if not title:
        for line in lines[:15]:
            if 10 <= len(line) <= 150 and not line.startswith('http') and not _NAME_PATTERN.match(line):
                title = line
                break

    return {"title": title, "author": author, "year": year}


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


def load_token_cache(vault_path: str) -> dict[str, dict]:
    """Returns canonical → {type, aliases, translations, forms}. Handles old flat and new format."""
    path = Path(vault_path) / TOKENS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = {}
        for k, v in data.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                result[k] = {"type": None, "aliases": v, "translations": {}, "forms": list(v)}
            elif isinstance(v, dict):
                result[k] = {
                    "type": v.get("type"),
                    "aliases": v.get("aliases", [k]),
                    "translations": v.get("translations", {}),
                    "forms": v.get("forms", v.get("aliases", [k])),
                }
        return result
    except Exception:
        return {}


def save_token_cache(vault_path: str, terms: list[dict]):
    path = Path(vault_path) / TOKENS_FILENAME
    cache = load_token_cache(vault_path)
    for term in terms:
        canonical = term["canonical"]
        # If this canonical is already an alias/form of an existing token, merge into it
        existing_canonical = check_alias_conflict(canonical, cache)
        if existing_canonical and existing_canonical != canonical:
            existing = cache[existing_canonical]
            new_aliases = sorted(set(existing.get("aliases", [])) | {canonical} | set(term.get("aliases", [canonical])))
            new_forms = sorted(set(existing.get("forms", [])) | {canonical} | set(term.get("aliases", [canonical])))
            cache[existing_canonical] = {**existing, "aliases": new_aliases, "forms": new_forms}
            continue
        existing = cache.get(canonical, {"type": None, "aliases": [], "translations": {}, "forms": []})
        new_aliases = sorted(set(existing.get("aliases", [])) | set(term.get("aliases", [canonical])))
        new_translations = {**existing.get("translations", {}), **term.get("translations", {})}
        new_forms = sorted(set(new_aliases) | set(new_translations.values()))
        cache[canonical] = {
            "type": term.get("type") or existing.get("type"),
            "aliases": new_aliases,
            "translations": new_translations,
            "forms": new_forms,
        }
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
    # "Ogwudile Chinenye Linda", 2025, "Stufflebeam's CIPP Model of Evaluation"
    # → "Ogwudile Chinenye Linda-2025-Stufflebeam's CIPP Model of Evaluation.md"
    author = (meta.get("author") or "").strip()[:40]
    year = (meta.get("year") or "").strip()
    title = (meta.get("title") or "").strip()[:80]
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


def create_stubs(vault_path: str, wikilinks: set[str], source_filename: str,
                 term_types: dict[str, str | None] | None = None) -> tuple[int, int]:
    vault = Path(vault_path)
    today = datetime.date.today().isoformat()
    existing_names = {f.stem for f in vault.rglob("*.md")}
    term_types = term_types or {}
    created = 0
    existing = 0
    for name in sorted(wikilinks):
        safe = re.sub(r'[<>:"/\\|?*\n\r]', '', name).strip()
        if not safe or not should_create_stub(safe):
            continue
        if safe in existing_names:
            existing += 1
            continue
        t = term_types.get(safe)
        folder = _CLAUDE_TYPE_TO_FOLDER.get(t, get_stub_folder(safe)) if t else get_stub_folder(safe)
        tag = _CLAUDE_TYPE_TO_TAG.get(t, "concept") if t else "concept"
        stub_dir = vault / folder
        stub_dir.mkdir(exist_ok=True)
        content = f"---\ntitle: {safe}\ntags:\n  - {tag}\ncreated: {today}\n---\n"
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
                if not content.startswith("---\n"):
                    continue
                if "- author" in content[:300]:  # skip author stubs (Dataview body intentional)
                    continue
                if not any(t in content[:300] for t in ("- concept", "- person", "- method")):
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


def parse_author_list(author_str: str) -> list[str]:
    if not author_str:
        return []
    # Split on &, ;, "und", "and" first
    parts = re.split(r'\s*[&;]\s*|\s+und\s+|\s+and\s+', author_str)
    result = []
    for part in parts:
        commas = part.count(',')
        if commas == 0:
            result.append(part.strip())
        elif commas == 1:
            # "Nachname, Vorname" (single author, APA) → keep as one
            result.append(part.strip())
        else:
            # Multiple commas → "Nachname, Vorname, Nachname2, Vorname2" or list
            result.extend(p.strip() for p in part.split(',') if p.strip())
    return [r for r in result if r]


def get_author_stub_name(author: str) -> str:
    """Canonical filesystem-safe name for an author stub."""
    safe = re.sub(r'[<>:"/\\|?*\n\r]', '', author.strip()[:60])
    safe = re.sub(r'\s+', ' ', safe).strip().rstrip('.')
    return safe


def check_alias_conflict(new_canonical: str, existing_tokens: dict) -> str | None:
    """Returns existing canonical if new_canonical is already a known alias/form of any token."""
    nc = new_canonical.lower()
    for canonical, data in existing_tokens.items():
        if canonical.lower() == nc:
            return canonical
        all_forms = data.get("forms", []) + data.get("aliases", [])
        if any(f.lower() == nc for f in all_forms):
            return canonical
    return None


def format_author_yaml(author_str: str, authors_list: list[str]) -> str:
    """Format author YAML as plain text (no wikilinks — Dataview string() strips them anyway)."""
    if not author_str:
        return "author: ''\n"
    first = get_author_stub_name(authors_list[0] if authors_list else author_str)
    result = f"author: {first}\n"
    if len(authors_list) > 1:
        result += "authors:\n"
        for a in authors_list:
            result += f"  - {get_author_stub_name(a)}\n"
    return result


def _dataview_block(safe_name: str) -> str:
    return (
        f"\n## Werke\n\n"
        f"```dataview\n"
        f'TABLE year, journal\n'
        f'WHERE contains(string(author), "{safe_name}")'
        f' OR contains(string(authors), "{safe_name}")\n'
        f"SORT year DESC\n"
        f"```\n"
    )


def update_author_stub(vault_path: str, author: str, work: dict, affiliation: str = ""):
    """Create or repair author stub. Adds Dataview block if missing."""
    safe_name = get_author_stub_name(author)
    if len(safe_name) < 2:
        return
    stub_path = Path(vault_path) / "Personen" / f"{safe_name}.md"

    if stub_path.exists():
        content = stub_path.read_text(encoding="utf-8")
        if "## Werke" not in content:
            stub_path.write_text(content.rstrip() + _dataview_block(safe_name), encoding="utf-8")
        return

    (Path(vault_path) / "Personen").mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    stub_path.write_text(
        f"---\ntitle: {safe_name}\ntags:\n  - person\n  - author\ntype: person\n"
        f"created: {today}\n---\n" + _dataview_block(safe_name),
        encoding="utf-8",
    )


_COMBINED_SYSTEM_PROMPT = (
    "Du analysierst einen wissenschaftlichen Text.\n\n"
    "Deine Aufgaben:\n"
    "1. BEREINIGUNG: Entferne Noise (URLs, Impressum, Abbildungsreferenzen, generische Wörter ohne Fachbezug)\n"
    "2. NORMALISIERUNG: Fasse zusammen was zusammengehört (Imdahl + Max Imdahl → Max Imdahl)\n"
    "3. ERGÄNZUNG: Füge wichtige Begriffe hinzu die im Text stehen aber fehlen\n"
    "4. KLASSIFIZIERUNG: Markiere jeden Begriff als person / concept / method (oder null)\n"
    "5. ÜBERSETZUNG: Gib für jeden Begriff die deutsche (de) und englische (en) Form an\n"
    "6. METADATEN:\n"
    "   - title: NUR der eigentliche Werktitel. NIEMALS der erste Satz des Abstracts.\n"
    "     NIEMALS ein Satzteil der mit einem Verb beginnt ('angebote setzen...' ist KEIN Titel).\n"
    "     Der Titel steht als Heading auf Seite 1, VOR dem Autorennamen, kürzer als 15 Wörter.\n"
    "     Wenn kein sicherer Titel erkennbar: null zurückgeben.\n"
    "   - author, year, journal, doi, affiliation (Institution des Erstautors)\n"
    "   - citation_apa und citation_chicago: OHNE äußere Anführungszeichen, reiner Textstring\n"
    "   - body_start_marker: erste ~20 Wörter des echten Fließtexts (NICHT Titel/Abstract/Keywords/Instituts-/DOI-Block).\n"
    "     Der Fließtext beginnt typisch nach Abstract und Keywords mit dem ersten Einleitungssatz.\n"
    "     Gib den exakten Wortlaut zurück. null wenn unklar.\n"
    "7. ZITATION: Generiere aus den Metadaten korrekte APA und Chicago Strings\n"
    "8. SECTIONS: Analysiere die Textstruktur:\n"
    "   - has_abstract: true wenn Text einen Abstract-Abschnitt HAT (nicht erfinden!)\n"
    "   - abstract_text: den Abstract-Text (max 400 Wörter) oder null\n"
    "   - has_bibliography: true wenn Text eine Literaturliste HAT (nicht erfinden!)\n"
    "   - bibliography_start: genaue Überschrift ('Literatur', 'References' etc.) oder null\n\n"
    "Antworte NUR mit folgendem JSON (kein anderer Text, keine Markdown-Blöcke):\n"
    '{"metadata": {"title": "...", "author": "...", "year": "...", "journal": "", '
    '"doi": "", "affiliation": "", "citation_apa": "...", "citation_chicago": "...", '
    '"body_start_marker": "Erster Satz des echten Fließtexts..."},\n'
    ' "sections": {"has_abstract": true, "abstract_text": "...", '
    '"has_bibliography": true, "bibliography_start": "Literatur"},\n'
    ' "tokens": [\n'
    '   {"term": "Max Imdahl", "type": "person", "aliases": ["Imdahl"], '
    '"de": "Max Imdahl", "en": "Max Imdahl", "keep": true},\n'
    '   {"term": "Lernen", "type": "concept", "aliases": ["Lernens"], '
    '"de": "Lernen", "en": "Learning", "keep": true},\n'
    '   {"term": "www.verlag.de", "type": null, "aliases": [], "de": "", "en": "", "keep": false}\n'
    " ]}\n"
    "keep: true = sinnvoller Wikilink-Begriff | keep: false = Noise"
)


def build_combined_user_blocks(term_list: list[str], context_text: str) -> list[dict]:
    terms_section = (
        "Begriffe von Ollama (roh, unbereinigt):\n" + "\n".join(f"- {t}" for t in term_list)
        if term_list
        else "Keine Vorab-Begriffe — erkenne selbst alle relevanten Begriffe aus dem Text."
    )
    return [
        {"type": "text", "text": terms_section, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"\nText (Kontext, erste 3000 Zeichen):\n{context_text}"},
    ]


def parse_combined_response(raw: str) -> tuple[dict, list[dict]]:
    try:
        cleaned = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not m:
            return {}, []
        data = json.loads(m.group())
        md = data.get("metadata", {}) or {}
        title_raw = md.get("title")
        metadata = {
            "title": "" if (title_raw is None or str(title_raw).lower() == "null") else str(title_raw),
            "author": str(md.get("author") or ""),
            "year": str(md.get("year") or ""),
            "journal": str(md.get("journal") or ""),
            "doi": str(md.get("doi") or ""),
            "affiliation": str(md.get("affiliation") or ""),
            "citation_apa": str(md.get("citation_apa") or ""),
            "citation_chicago": str(md.get("citation_chicago") or ""),
            "body_start_marker": str(md.get("body_start_marker") or ""),
        }
        sec = data.get("sections", {}) or {}
        metadata["sections"] = {
            "has_abstract": bool(sec.get("has_abstract", False)),
            "abstract_text": str(sec.get("abstract_text") or ""),
            "has_bibliography": bool(sec.get("has_bibliography", False)),
            "bibliography_start": str(sec.get("bibliography_start") or ""),
        }
        tokens = []
        for t in data.get("tokens", []):
            if not isinstance(t, dict):
                continue
            term = str(t.get("term") or "").strip()
            if not term:
                continue
            aliases = [str(a).strip() for a in (t.get("aliases") or []) if a]
            if term not in aliases:
                aliases.insert(0, term)
            de = str(t.get("de") or "").strip()
            en = str(t.get("en") or "").strip()
            translations = {}
            if de:
                translations["de"] = de
            if en and en.lower() != de.lower():
                translations["en"] = en
            tokens.append({
                "canonical": term,
                "aliases": aliases,
                "type": t.get("type"),
                "keep": bool(t.get("keep", True)),
                "translations": translations,
            })
        return metadata, tokens
    except Exception as e:
        logger.warning("parse_combined_response fehlgeschlagen: %s", e)
        return {}, []


def structure_text_sections(full_text: str) -> tuple[str, str, str]:
    """Returns (abstract, main_body, references)."""
    text = full_text.strip()
    ref_m = re.search(
        r'\n(Literatur(?:verzeichnis)?|References?|Bibliographie|Bibliography|Quellenverzeichnis)\s*\n',
        text, re.IGNORECASE,
    )
    body_text = text[:ref_m.start()].strip() if ref_m else text
    references = text[ref_m.start():].strip() if ref_m else ""

    abs_m = re.search(r'(?:^|\n)(Abstract|Zusammenfassung|Kurzfassung)\b', body_text, re.IGNORECASE)
    if abs_m:
        after = body_text[abs_m.end():]
        next_sec = re.search(r'\n\n+[A-Z1-9À-Ü]', after)
        if next_sec and next_sec.start() < 1500:
            abstract = after[:next_sec.start()].strip()
            main_body = after[next_sec.start():].strip()
        else:
            words = after.split()
            abstract = ' '.join(words[:300])
            main_body = ' '.join(words[300:]).strip()
    else:
        words = body_text.split()
        abstract = ' '.join(words[:200])
        main_body = ' '.join(words[200:]).strip()

    return abstract, main_body, references


_CLAUDE_TYPE_TO_FOLDER = {"person": "Personen", "method": "Methoden", "concept": "Konzepte"}
_CLAUDE_TYPE_TO_TAG = {"person": "person", "method": "method", "concept": "concept"}


def build_chapter_prompt(toc_text: str) -> str:
    return (
        "Analysiere das folgende Inhaltsverzeichnis eines Buches.\n"
        "Extrahiere nur die Hauptkapitel (keine Unterkapitel, keine Anhänge).\n"
        "Antworte NUR mit JSON-Array (kein anderer Text):\n"
        '[{"chapter": 1, "title": "Einleitung", "page_start": 15}, ...]\n'
        "page_start = gedruckte Seitenzahl wo das Kapitel beginnt.\n"
        "Wenn kein Inhaltsverzeichnis erkennbar: []\n\n"
        f"Text:\n{toc_text[:4000]}"
    )


def parse_chapter_structure(raw: str) -> list[dict]:
    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if not m:
            return []
        chapters = json.loads(m.group())
        return [c for c in chapters if isinstance(c, dict) and "title" in c and c.get("title")]
    except Exception:
        return []


def find_chapter_boundaries(doc, chapters: list[dict]) -> list[dict]:
    """Find actual PDF page indices by searching for chapter titles in page text."""
    result = []
    for ch in chapters:
        title = ch.get("title", "")
        page_hint = max(0, int(ch.get("page_start") or 1) - 3)
        found_page = None
        # Try progressively shorter substrings of the title (longest first)
        for frac in (1.0, 0.66, 0.33):
            sub = title[:max(5, int(len(title) * frac))]
            if len(sub) < 5:
                break
            pattern = re.compile(re.escape(sub), re.IGNORECASE)
            for page_idx in range(page_hint, len(doc)):
                if pattern.search(doc[page_idx].get_text()):
                    found_page = page_idx
                    break
            if found_page is not None:
                break
        if found_page is None:
            found_page = max(0, int(ch.get("page_start") or 1) - 2)
        result.append({**ch, "pdf_page": found_page})
    return result


def _pdf_page_from_printed(page_end: int | None, doc_len: int) -> int:
    """Convert printed page_end to a capped PDF page index."""
    if page_end is None:
        return doc_len
    return min(max(0, page_end - 1), doc_len)


def _is_author_line(s: str) -> bool:
    """Heuristic: does this line look like an author attribution (not a chapter title)?"""
    if not s or not s[0].isupper() or len(s) > 120:
        return False
    if re.search(r'\d+\s*$', s):  # ends with page number → TOC entry, not author
        return False
    if re.search(r'\s+(und|&|/)\s+|\s*,\s*[A-ZÄÖÜ]', s):  # multiple people
        return True
    words = s.split()
    if 2 <= len(words) <= 4 and all(re.match(r'^[^\s\d<>:"/\\|?*;!?()\[\]]+$', w) for w in words):
        return True  # single name: 2-4 words (unicode-safe, handles é, à, ő etc.)
    return False


def detect_book_type(toc_text: str, front_pages_text: str) -> str:
    """Score-based: ≥2 points → sammelband, else monographie."""
    score = 0
    combined = toc_text + "\n" + front_pages_text
    if re.search(r'\(Hrsg\.\)|Hrsg\.|eds?\.|edited by|Herausgeber', combined, re.IGNORECASE):
        score += 2
    author_lines = sum(1 for line in toc_text.split('\n') if _is_author_line(line.strip()))
    if author_lines >= 3:
        score += 2
    elif author_lines >= 1:
        score += 1
    return "sammelband" if score >= 2 else "monographie"


def _fill_page_ends(chapters: list[dict], total_pages: int) -> None:
    """Fill page_end=None entries: next chapter's page_start-1, or total_pages for the last."""
    non_sections = [c for c in chapters if not c.get("is_section")]
    for i, ch in enumerate(non_sections):
        if ch.get("page_end") is not None:
            continue
        if i + 1 < len(non_sections):
            ch["page_end"] = non_sections[i + 1]["page_start"] - 1
        else:
            ch["page_end"] = total_pages


def parse_toc_regex(toc_text: str) -> list[dict]:
    """Parse TOC entries via regex. Returns list with title/page_start/author/is_section/enabled."""
    _page_re = re.compile(r'[\s.·•–]{2,}\d{1,4}\s*$')
    raw = [l.strip() for l in toc_text.split('\n')]
    # Merge continuation lines: a line without page number directly before a line with one
    merged: list[str] = []
    i = 0
    while i < len(raw):
        line = raw[i]
        if (line and not _page_re.search(line) and not _is_author_line(line) and
                i + 1 < len(raw) and _page_re.search(raw[i + 1])):
            raw[i + 1] = line + ' ' + raw[i + 1]
            i += 1
            continue
        merged.append(line)
        i += 1
    lines = merged
    result = []
    chapter_num = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(.+?)[\s.·•–]{2,}(\d{1,4})\s*$', line)
        if m:
            title = m.group(1).strip()
            page_start = int(m.group(2))
            if len(title) < 4 or re.fullmatch(r'[\d\s\.\-]+', title):
                i += 1
                continue
            author = None
            if i + 1 < len(lines) and _is_author_line(lines[i + 1].strip()):
                author = lines[i + 1].strip()
                i += 1
            is_section = (author is None and (
                re.match(r'^(Teil|Abschnitt|Section|Part)\s+[IVX\d]', title, re.I) or
                re.match(r'^[IVX]+\.\s+', title) or
                (title.isupper() and len(title.split()) <= 4)
            ))
            if not is_section:
                chapter_num += 1
            result.append({
                "chapter": chapter_num if not is_section else 0,
                "title": title,
                "page_start": page_start,
                "page_end": None,
                "author": author,
                "is_section": is_section,
                "enabled": not is_section,
            })
        i += 1
    return result


def derive_chapter_filename(chapter_num: int, chapter_title: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "", chapter_title).strip()
    safe = re.sub(r'\s+', '-', safe)
    return f"{chapter_num:02d}-{safe}.md"


_HEADER_LINE_PATTERNS = [
    re.compile(r'^\s*ISSN\s*[\d\-:]', re.IGNORECASE),
    re.compile(r'^\s*DOI\s*:\s*10\.', re.IGNORECASE),
    re.compile(r'^\s*Volume\s*\d', re.IGNORECASE),
    re.compile(r'^\s*Issue\s*\d', re.IGNORECASE),
    re.compile(r'^\s*Impact\s+Factor', re.IGNORECASE),
    re.compile(r'^\s*Published\s+(by|in)\b', re.IGNORECASE),
    re.compile(r'^\s*https?://\S+\s*$'),
    re.compile(r'^\s*\d{1,4}\s*$'),
    re.compile(r'^\s*(Department|Faculty|Institute|School)\s+[Oo]f\b'),
    re.compile(r'^\s*University\s+(of|College)\b', re.IGNORECASE),
]


def _extract_pdf_title(doc) -> str:
    """Extract title from PDF metadata if valid (non-empty, not generic, not only symbols)."""
    try:
        title = (doc.metadata.get("title") or "").strip()
        if (len(title) > 10 and
                re.search(r'[A-Za-zÄÖÜäöüß]', title) and
                not re.fullmatch(r'[\W\d\s]+', title) and
                not re.search(r'Microsoft|Word|Document|Untitled|Template', title, re.IGNORECASE)):
            if title.isupper():
                title = title.title()
            return title
    except Exception:
        pass
    return ""


def _is_noisy_header_line(line: str) -> bool:
    """Return True if this line is typical journal header noise."""
    s = line.strip()
    if not s:
        return False
    checks = [
        re.search(r'\bISSN\b', s, re.IGNORECASE),
        re.search(r'\bDOI\s*:\s*10\.', s, re.IGNORECASE),
        re.search(r'\bVol\.\s*\d|\bIssue\s*\d|\bpp?\.\s*\d|\bNo\.\s*\d', s),
        re.search(r'www\.|https?://', s, re.IGNORECASE),
        re.fullmatch(r'\s*\d+\s*', s),
        re.search(r'[Pp]age\s+\d+|\|\s*P\s*a\s*g\s*e\b', s),
        re.search(r'@\S+\.\w{2,4}', s),
        re.search(r'Impact\s+Factor|Published\s+by|Copyright\s*©|All\s+rights\s+reserved', s, re.IGNORECASE),
        (s.isupper() and len(s) < 60),
    ]
    return any(checks)


def clean_header_text(text: str, body_start_marker: str = "") -> str:
    """Remove journal header noise. Step 1: body_start_marker. Step 2: noisy first-30-lines."""
    # Step 1: body_start_marker → jump directly to body start
    if body_start_marker and len(body_start_marker) > 15:
        idx = text.find(body_start_marker[:60])
        if idx > 0:
            text = text[idx:]

    # Step 2: additionally clean remaining noisy lines in first 30 lines
    lines = text.split('\n')
    result = []
    real_text_started = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if real_text_started or i >= 30:
            result.append(line)
            continue
        if not stripped:
            result.append(line)
            continue
        if _is_noisy_header_line(stripped):
            continue  # skip noisy header line
        if len(stripped) > 40:
            real_text_started = True
        result.append(line)

    return '\n'.join(result)


def log_job(job: dict):
    try:
        with open(JOBS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(job, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Job-Log fehlgeschlagen: %s", e)


def _noise_reason(term: str) -> str | None:
    t = term.strip()
    tl = t.lower()
    if tl in _IMPRINT_BLACKLIST:
        return "impressum"
    if any(tl.startswith(p) for p in _FIGURE_PREFIXES):
        return "figure_ref"
    if any(x in t for x in ("www.", ".de", ".com", "http", "@")):
        return "technical"
    if len(t) < 4:
        return "too_short"
    if re.fullmatch(r'[\d\s\.\-/]+', t):
        return "number_or_year"
    return None


def filter_noisy_terms(terms: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, filtered = [], []
    for term in terms:
        reason = _noise_reason(term["canonical"])
        if reason:
            filtered.append({**term, "filtered_reason": reason})
        else:
            kept.append(term)
    return kept, filtered


def find_review_duplicates(terms: list[dict]) -> list[list[str]]:
    canonicals = [t["canonical"] for t in terms]
    pairs: list[list[str]] = []
    seen: set[tuple] = set()
    for i in range(len(canonicals)):
        a_l = canonicals[i].lower()
        for j in range(i + 1, len(canonicals)):
            b_l = canonicals[j].lower()
            key = (min(canonicals[i], canonicals[j]), max(canonicals[i], canonicals[j]))
            if key in seen:
                continue
            if (re.search(r'\b' + re.escape(a_l) + r'\b', b_l) or
                    re.search(r'\b' + re.escape(b_l) + r'\b', a_l)):
                pairs.append([canonicals[i], canonicals[j]])
                seen.add(key)
                if len(pairs) >= 20:
                    return pairs
    return pairs


def build_quality_pass_prompt(terms: list[str]) -> str:
    terms_text = "\n".join(f"- {t}" for t in terms)
    return (
        "Du überprüfst eine Liste von Begriffen die als Wikilinks in einem wissenschaftlichen Text gesetzt werden sollen.\n"
        "Identifiziere Begriffe die eindeutig KEIN sinnvoller Wikilink-Begriff sind:\n"
        "- Generische Alltagswörter ohne Fachbezug im wissenschaftlichen Kontext\n"
        "- Reine Funktionswörter oder grammatische Formen\n"
        "- Druckdaten, Impressumsbegriffe, Abbildungsreferenzen\n"
        "BEHALTE: Personennamen, Fachbegriffe, Konzepte, Institutionen, Werktitel — auch wenn scheinbar allgemein.\n"
        "Entferne NUR eindeutige False Positives.\n\n"
        f"Begriffe:\n{terms_text}\n\n"
        "Antworte NUR mit einer JSON-Liste der zu entfernenden Begriffe: [\"Begriff1\", \"Begriff2\", ...]\n"
        "Wenn alle Begriffe sinnvoll sind: []"
    )


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


class ConfirmRequest(BaseModel):
    selected_terms: list[str]
    merged_terms: list[dict] = []


class QualityPassRequest(BaseModel):
    terms: list[str]


class BulkRequest(BaseModel):
    pdf_paths: list[str]
    model: str = "auto"


class BulkConfirmRequest(BaseModel):
    selected_terms: list[str]
    merged_terms: list[dict] = []


class QueueConfirmRequest(BaseModel):
    job_id: str
    selected_terms: list[str]
    merged_terms: list[dict] = []
    meta_override: dict = {}


class BookFinalizeRequest(BaseModel):
    book_id: str


class CancelJobRequest(BaseModel):
    job_id: str


class DuplicateCheckRequest(BaseModel):
    pdf_filename: str


class BatchDuplicateCheckRequest(BaseModel):
    files: list[dict]  # [{pdf_filename: str}]


class BookReparseRequest(BaseModel):
    pdf_id: str
    page_range: str | None = None
    toc_text: str | None = None


class BookRunRequest(BaseModel):
    pdf_id: str
    model: str = "auto"
    chapters: list[dict]
    book_title: str | None = None


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


MNEME_VERSION = "3.0.3"


@app.get("/version")
def get_version():
    return {"version": MNEME_VERSION}


def _build_vault_source_map(vault_path: str) -> dict[str, tuple[str, str]]:
    """Scan vault once and build {source_pdf_lower → (rel_path, title_lower)} map."""
    result: dict[str, tuple[str, str]] = {}
    vault = Path(vault_path)
    candidates = list(vault.glob("*.md"))
    bucher = vault / "Bücher"
    if bucher.is_dir():
        candidates.extend(bucher.rglob("*.md"))
    for md_file in candidates:
        try:
            lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()[:30]
            src_val = title_val = ""
            for line in lines:
                ls = line.strip().lower()
                if ls.startswith("source_pdf:") and not src_val:
                    src_val = line.split(":", 1)[1].strip().strip("'\"").lower()
                if ls.startswith("title:") and not title_val:
                    title_val = line.split(":", 1)[1].strip().strip("'\"").lower()
            if src_val:
                rel = str(md_file.relative_to(vault))
                result[src_val] = (rel, title_val)
        except Exception:
            pass
    return result


@app.post("/check/duplicate")
def check_duplicate(req: DuplicateCheckRequest):
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        return {"exists": False, "existing_file": None, "match_type": None}
    src_map = _build_vault_source_map(vault_path)
    target = req.pdf_filename.strip().lower()
    if target in src_map:
        return {"exists": True, "existing_file": src_map[target][0], "match_type": "source_pdf"}
    return {"exists": False, "existing_file": None, "match_type": None}


@app.post("/check/duplicates")
def check_duplicates_batch(req: BatchDuplicateCheckRequest):
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    empty = {"exists": False, "existing_file": None, "match_type": None}
    if not vault_path or not Path(vault_path).is_dir():
        return {"results": {f.get("pdf_filename", ""): empty for f in req.files}}
    src_map = _build_vault_source_map(vault_path)
    results = {}
    for f in req.files:
        filename = f.get("pdf_filename", "")
        target = filename.strip().lower()
        if target in src_map:
            results[filename] = {"exists": True, "existing_file": src_map[target][0], "match_type": "source_pdf"}
        else:
            results[filename] = empty
    return {"results": results}


@app.get("/last_run_cost")
def last_run_cost():
    inp = _last_run_stats["input_tokens"]
    out = _last_run_stats["output_tokens"]
    cache_read = _last_run_stats.get("cache_read_tokens", 0)
    cache_write = _last_run_stats.get("cache_creation_tokens", 0)
    cost_usd = (
        inp * HAIKU_PRICE_INPUT_PER_TOKEN +
        out * HAIKU_PRICE_OUTPUT_PER_TOKEN +
        cache_read * HAIKU_PRICE_CACHE_READ_PER_TOKEN +
        cache_write * HAIKU_PRICE_CACHE_WRITE_PER_TOKEN
    )
    cost_eur = cost_usd * EUR_RATE
    saved_usd = cache_read * (HAIKU_PRICE_INPUT_PER_TOKEN - HAIKU_PRICE_CACHE_READ_PER_TOKEN)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_write,
        "cost_usd": round(cost_usd, 5),
        "cost_eur": round(cost_eur, 5),
        "saved_eur": round(saved_usd * EUR_RATE, 5),
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
    def _get_aliases(entry) -> set:
        if isinstance(entry, list):
            return set(entry)
        if isinstance(entry, dict):
            return set(entry.get("aliases", []))
        return set()

    keep_entry = data[req.keep]
    remove_entry = data[req.remove]
    keep_al = _get_aliases(keep_entry)
    remove_al = _get_aliases(remove_entry)
    merged_aliases = sorted(keep_al | remove_al | {req.remove})

    if isinstance(keep_entry, dict):
        remove_translations = remove_entry.get("translations", {}) if isinstance(remove_entry, dict) else {}
        merged_translations = {**remove_translations, **keep_entry.get("translations", {})}
        merged_forms = sorted(set(keep_entry.get("forms", [])) |
                              set(remove_entry.get("forms", []) if isinstance(remove_entry, dict) else []) |
                              {req.remove})
        data[req.keep] = {**keep_entry, "aliases": merged_aliases,
                          "translations": merged_translations, "forms": merged_forms}
    else:
        data[req.keep] = merged_aliases
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


@app.get("/process/status")
def get_process_status():
    return _processing_status


@app.post("/process/confirm")
def confirm_process(req: ConfirmRequest):
    global _pending_draft
    if not _pending_draft:
        raise HTTPException(status_code=400, detail="no_pending_draft")

    draft = _pending_draft
    vault_path = draft["vault_path"]
    selected_set = set(req.selected_terms)

    selected_new = [t for t in draft["new_terms"] if t["canonical"] in selected_set]

    for merge in req.merged_terms:
        keep_c = merge.get("keep")
        remove_c = merge.get("remove")
        if not keep_c or not remove_c:
            continue
        keep_term = next((t for t in selected_new if t["canonical"] == keep_c), None)
        if keep_term:
            remove_term = next((t for t in draft["new_terms"] if t["canonical"] == remove_c), None)
            if remove_term:
                keep_term["aliases"] = sorted(
                    set(keep_term.get("aliases", [])) | set(remove_term.get("aliases", [])) | {remove_c}
                )
        selected_new = [t for t in selected_new if t["canonical"] != remove_c]

    final_terms = merge_terms(
        [draft["cached_terms"], selected_new],
        draft["base_links"],
        draft["vault_links"],
        draft["full_text"],
    )
    body = draft.get("sections_text", draft["full_text"])
    content = apply_wikilinks(draft["frontmatter"] + body, final_terms)
    total_links = len(re.findall(r"\[\[.+?\]\]", content))

    output_filename = draft["output_filename"]

    # Create author stubs BEFORE writing the literature note
    draft_meta = draft.get("meta", {})
    author_str_d = draft_meta.get("author", "")
    if author_str_d:
        work_info = {
            "title": draft_meta.get("title", ""),
            "year": draft_meta.get("year", ""),
            "file": output_filename.replace(".md", ""),
            "doi": draft_meta.get("doi", ""),
        }
        aff = draft_meta.get("affiliation", "")
        for a in (parse_author_list(author_str_d) or [author_str_d]):
            update_author_stub(vault_path, a, work_info, aff)

    (Path(vault_path) / output_filename).write_text(content, encoding="utf-8")

    save_token_cache(vault_path, selected_new)

    if req.merged_terms:
        tok_path = Path(vault_path) / TOKENS_FILENAME
        try:
            data = json.loads(tok_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for merge in req.merged_terms:
            keep_c = merge.get("keep")
            remove_c = merge.get("remove")
            if keep_c in data and remove_c in data:
                data[keep_c] = sorted(
                    set(data.get(keep_c, [])) | set(data.get(remove_c, [])) | {remove_c}
                )
                del data[remove_c]
                rename_wikilinks_in_vault(vault_path, remove_c, keep_c)
        tok_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    term_types = {t["canonical"]: t.get("type") for t in selected_new}
    found_links = set(re.findall(r'\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]', content))
    stubs_created, stubs_existing = create_stubs(vault_path, found_links, output_filename, term_types)

    cost_info = draft.get("cost", {})
    cost_eur = round(
        (cost_info.get("input_tokens", 0) * HAIKU_PRICE_INPUT_PER_TOKEN +
         cost_info.get("output_tokens", 0) * HAIKU_PRICE_OUTPUT_PER_TOKEN +
         cost_info.get("cache_read_tokens", 0) * HAIKU_PRICE_CACHE_READ_PER_TOKEN +
         cost_info.get("cache_creation_tokens", 0) * HAIKU_PRICE_CACHE_WRITE_PER_TOKEN) * EUR_RATE, 5
    )
    log_job({
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "filename": output_filename,
        "source_pdf": draft.get("source_pdf", ""),
        "model": draft.get("stats", {}).get("model_used", ""),
        "links": total_links,
        "new_tokens": len(selected_new),
        "elapsed_s": draft.get("process_elapsed_s", 0),
        "cost_eur": cost_eur,
        "status": "ok",
    })
    logger.info("CONFIRMED: %d links | %d stubs | %s", total_links, stubs_created, output_filename)
    _pending_draft = None
    return {
        "ok": True,
        "filename": output_filename,
        "wikilinks_total": total_links,
        "stubs_created": stubs_created,
        "stubs_existing": stubs_existing,
        "model_used": f"{_last_run_stats.get('phase1_model', '')}/{_last_run_stats.get('meta_model', '')}",
    }


async def _process_queue_job(job_id: str, pdf_bytes: bytes, filename: str, model: str):
    import time
    global _queue_jobs, _cancel_flags
    if job_id in _cancel_flags:
        _queue_jobs[job_id]["status"] = "cancelled"
        _queue_jobs[job_id]["stage"] = "Abgebrochen"
        _cancel_flags.discard(job_id)
        return
    t0 = time.time()

    def _stage_cb(s: str):
        if job_id in _queue_jobs:
            _queue_jobs[job_id]["stage"] = s

    _queue_jobs[job_id]["status"] = "processing"
    _queue_jobs[job_id]["stage"] = "Verarbeitung läuft..."
    try:
        draft = await _process_pdf_bytes(pdf_bytes, filename, model,
                                          stage_callback=_stage_cb, cancel_job_id=job_id)
        _queue_jobs[job_id]["status"] = "done"
        _queue_jobs[job_id]["draft"] = draft
        _queue_jobs[job_id]["elapsed"] = round(time.time() - t0)
        _queue_jobs[job_id]["stage"] = "Fertig"
    except HTTPException as e:
        if e.detail == "cancelled_by_user":
            _queue_jobs[job_id]["status"] = "cancelled"
            _queue_jobs[job_id]["stage"] = "Abgebrochen"
        else:
            _queue_jobs[job_id]["status"] = "error"
            _queue_jobs[job_id]["error"] = str(e.detail)
            _queue_jobs[job_id]["stage"] = f"Fehler: {e.detail}"
    except Exception as e:
        _queue_jobs[job_id]["status"] = "error"
        _queue_jobs[job_id]["error"] = str(e)
        _queue_jobs[job_id]["stage"] = "Fehler"
    finally:
        _cancel_flags.discard(job_id)


@app.post("/process/queue")
async def start_queue_processing(files: list[UploadFile] = File(...), model: str = "auto"):
    # Parallel tasks — Ollama serializes internally due to single-GPU constraint
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    jobs = []
    for f in files:
        job_id = str(uuid.uuid4())[:12]
        pdf_bytes = await f.read()
        filename = f.filename or f"{job_id}.pdf"
        _queue_jobs[job_id] = {"status": "pending", "filename": filename,
                               "draft": None, "error": None, "stage": "Wartend..."}
        asyncio.create_task(_process_queue_job(job_id, pdf_bytes, filename, model))
        jobs.append({"job_id": job_id, "filename": filename})
    return {"jobs": jobs}


@app.get("/process/queue/status")
def get_queue_status():
    result = []
    for jid, job in _queue_jobs.items():
        d = job["draft"]
        result.append({
            "job_id": jid,
            "filename": job["filename"],
            "status": job["status"],
            "stage": job.get("stage", ""),
            "error": job.get("error"),
            "elapsed": job.get("elapsed"),
            "draft_summary": {
                "filename": d["output_filename"],
                "tokens": d["token_list"],
                "stats": d["stats"],
                "cost": d["cost"],
                "meta": d.get("meta", {}),
                "content": d.get("preview_content", ""),
                "duplicate_suggestions": d.get("duplicate_suggestions", []),
            } if d else None,
        })
    return {"jobs": result}


@app.post("/process/queue/cancel")
def cancel_queue_job(req: CancelJobRequest):
    global _cancel_flags
    job = _queue_jobs.get(req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if job["status"] == "pending":
        job["status"] = "cancelled"
        job["stage"] = "Abgebrochen"
    elif job["status"] == "processing":
        _cancel_flags.add(req.job_id)
        job["stage"] = "Wird abgebrochen..."
    return {"cancelled": True}


@app.post("/process/book/finalize")
def finalize_book(req: BookFinalizeRequest):
    book_data = _pending_book_drafts.get(req.book_id)
    if not book_data:
        raise HTTPException(status_code=404, detail="book_not_found")
    vault_path = book_data["vault_path"]
    folder_name = book_data["folder_name"]
    book_meta = book_data["book_meta"]
    pdf_filename = book_data["pdf_filename"]
    book_dir = Path(vault_path) / "Bücher" / folder_name
    book_dir.mkdir(parents=True, exist_ok=True)
    _write_book_overview(book_dir, book_meta, folder_name, pdf_filename)
    for jid in book_data.get("job_ids", []):
        _queue_jobs.pop(jid, None)
    del _pending_book_drafts[req.book_id]
    logger.info("BUCH FINALIZED: %s", folder_name)
    return {"ok": True, "folder": folder_name}


@app.post("/process/queue/confirm")
def confirm_queue_job(req: QueueConfirmRequest):
    global _queue_jobs
    if req.job_id not in _queue_jobs:
        raise HTTPException(status_code=404, detail="job_not_found")
    job = _queue_jobs[req.job_id]
    if job["status"] != "done" or not job["draft"]:
        raise HTTPException(status_code=400, detail="job_not_ready")
    draft = job["draft"]

    if req.meta_override:
        meta = draft.setdefault("meta", {})
        for field, value in req.meta_override.items():
            if value and field in ("title", "author", "year"):
                meta[field] = value
                draft["frontmatter"] = re.sub(
                    rf'^{re.escape(field)}:.*$', f'{field}: {yaml_str(str(value))}',
                    draft["frontmatter"], flags=re.MULTILINE,
                )
        if req.meta_override.get("title"):
            draft["output_filename"] = derive_output_filename(meta, draft.get("source_pdf", "document.pdf"))

    vault_path = draft["vault_path"]
    selected_set = set(req.selected_terms)
    selected_new = [t for t in draft["new_terms"] if t["canonical"] in selected_set]
    for merge in req.merged_terms:
        keep_c, remove_c = merge.get("keep"), merge.get("remove")
        if not keep_c or not remove_c:
            continue
        keep_term = next((t for t in selected_new if t["canonical"] == keep_c), None)
        if keep_term:
            remove_term = next((t for t in draft["new_terms"] if t["canonical"] == remove_c), None)
            if remove_term:
                keep_term["aliases"] = sorted(set(keep_term.get("aliases", [])) | set(remove_term.get("aliases", [])) | {remove_c})
        selected_new = [t for t in selected_new if t["canonical"] != remove_c]

    final_terms = merge_terms([draft["cached_terms"], selected_new], draft["base_links"], draft["vault_links"], draft["full_text"])
    body = draft.get("sections_text", draft["full_text"])
    content = apply_wikilinks(draft["frontmatter"] + body, final_terms)
    total_links = len(re.findall(r"\[\[.+?\]\]", content))
    output_filename = draft["output_filename"]

    draft_meta = draft.get("meta", {})
    author_str_d = draft_meta.get("author", "")
    if author_str_d:
        work_info = {"title": draft_meta.get("title", ""), "year": draft_meta.get("year", ""),
                     "file": output_filename.replace(".md", ""), "doi": draft_meta.get("doi", "")}
        for a in (parse_author_list(author_str_d) or [author_str_d]):
            update_author_stub(vault_path, a, work_info, draft_meta.get("affiliation", ""))

    out_path = Path(vault_path) / output_filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    save_token_cache(vault_path, selected_new)

    if req.merged_terms:
        tok_path = Path(vault_path) / TOKENS_FILENAME
        try:
            data = json.loads(tok_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        for merge in req.merged_terms:
            keep_c, remove_c = merge.get("keep"), merge.get("remove")
            if keep_c in data and remove_c in data:
                data[keep_c] = sorted(set(data.get(keep_c, [])) | set(data.get(remove_c, [])) | {remove_c})
                del data[remove_c]
                rename_wikilinks_in_vault(vault_path, remove_c, keep_c)
        tok_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    term_types = {t["canonical"]: t.get("type") for t in selected_new}
    found_links = set(re.findall(r'\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]', content))
    stubs_created, _ = create_stubs(vault_path, found_links, output_filename, term_types)
    cost_info = draft.get("cost", {})
    cost_eur = round(
        (cost_info.get("input_tokens", 0) * HAIKU_PRICE_INPUT_PER_TOKEN +
         cost_info.get("output_tokens", 0) * HAIKU_PRICE_OUTPUT_PER_TOKEN +
         cost_info.get("cache_read_tokens", 0) * HAIKU_PRICE_CACHE_READ_PER_TOKEN +
         cost_info.get("cache_creation_tokens", 0) * HAIKU_PRICE_CACHE_WRITE_PER_TOKEN) * EUR_RATE, 5)
    log_job({"timestamp": datetime.datetime.now().isoformat(timespec="seconds"), "filename": output_filename,
             "source_pdf": draft.get("source_pdf", ""), "model": draft.get("stats", {}).get("model_used", ""),
             "links": total_links, "new_tokens": len(selected_new),
             "elapsed_s": draft.get("process_elapsed_s", 0), "cost_eur": cost_eur, "status": "ok"})
    logger.info("QUEUE CONFIRMED: %d links | %d stubs | %s", total_links, stubs_created, output_filename)
    del _queue_jobs[req.job_id]
    return {"ok": True, "filename": output_filename, "wikilinks_total": total_links,
            "stubs_created": stubs_created, "model_used": draft.get("stats", {}).get("model_used", "")}


@app.post("/process/quality_pass")
def quality_pass(req: QualityPassRequest):
    cfg = load_config()
    api_key = get_anthropic_key(cfg)
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="claude_api_key_missing")
    try:
        raw = call_claude(api_key, build_quality_pass_prompt(req.terms), max_tokens=512)
        m = re.search(r'\[.*?\]', raw, re.DOTALL)
        remove = json.loads(m.group()) if m else []
        if not isinstance(remove, list):
            remove = []
    except Exception as e:
        logger.warning("Quality pass fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail=f"quality_pass_error: {e}")
    return {"remove": [str(r) for r in remove]}


@app.post("/process/book/preview")
async def process_book_preview(file: UploadFile = File(...), model: str = "auto"):
    global _processing_status
    _processing_status = {"active": True, "stage": "TOC wird erkannt...", "progress": 0.05,
                          "chunk_current": 0, "chunk_total": 0}
    try:
        cfg = load_config()
        vault_path = cfg.get("vault_path", "")
        if not vault_path or not Path(vault_path).is_dir():
            raise HTTPException(status_code=400, detail="vault_path_not_set")
        api_key = get_anthropic_key(cfg)

        pdf_bytes = await file.read()
        if not pdf_bytes:
            raise HTTPException(status_code=400, detail="empty_file")
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"pdf_parse_error: {e}")

        total_pages = len(doc)
        toc_text = "\n\n".join(doc[p].get_text() for p in range(min(25, total_pages)))
        front_pages_text = "\n\n".join(doc[p].get_text() for p in range(min(5, total_pages)))

        book_type = detect_book_type(toc_text, front_pages_text)
        book_title = _extract_pdf_title(doc)
        if not book_title:
            book_title = (extract_metadata_regex(front_pages_text).get("title") or
                          re.sub(r'[_\-.]', ' ', Path(file.filename or "book").stem)[:80].strip())
        doc.close()

        chapters = parse_toc_regex(toc_text)
        if len(chapters) < 3 and api_key.strip():
            _processing_status["stage"] = "Claude parst Kapitelstruktur..."
            _processing_status["progress"] = 0.5
            try:
                raw = call_claude(api_key, build_chapter_prompt(toc_text), max_tokens=1024)
                claude_chs = parse_chapter_structure(raw)
                if len(claude_chs) > len(chapters):
                    chapters = [
                        {**ch, "page_end": None, "author": None, "is_section": False, "enabled": True}
                        for ch in claude_chs
                    ]
            except Exception as e:
                logger.warning("Claude TOC-Fallback fehlgeschlagen: %s", e)

        pdf_id = str(uuid.uuid4())[:12]
        if len(_pending_book_pdf) >= 3:
            del _pending_book_pdf[next(iter(_pending_book_pdf))]
        _pending_book_pdf[pdf_id] = {"bytes": pdf_bytes, "filename": file.filename or "book.pdf"}

        _fill_page_ends(chapters, total_pages)
        logger.info("BOOK PREVIEW: type=%s, chapters=%d, id=%s", book_type, len(chapters), pdf_id)
        return {"pdf_id": pdf_id, "book_type": book_type, "title": book_title,
                "total_pages": total_pages, "chapters": chapters}
    finally:
        _processing_status["active"] = False
        _processing_status["stage"] = ""


@app.post("/process/book/reparse")
def process_book_reparse(req: BookReparseRequest):
    if req.pdf_id not in _pending_book_pdf:
        raise HTTPException(status_code=404, detail="pdf_not_found")
    if req.toc_text:
        text = req.toc_text
    elif req.page_range:
        try:
            parts = req.page_range.split("-")
            start = max(0, int(parts[0]) - 1)
            end = int(parts[1])
            pdf_bytes = _pending_book_pdf[req.pdf_id]["bytes"]
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "\n\n".join(doc[p].get_text() for p in range(start, min(end, len(doc))))
            doc.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"page_range_error: {e}")
    else:
        raise HTTPException(status_code=400, detail="need_page_range_or_toc_text")
    return {"chapters": parse_toc_regex(text)}


@app.post("/process/book/run")
async def process_book_run(req: BookRunRequest):
    global _processing_status
    if req.pdf_id not in _pending_book_pdf:
        raise HTTPException(status_code=404, detail="pdf_not_found")
    _processing_status = {"active": True, "stage": "Buch wird geladen...", "progress": 0.02,
                          "chunk_current": 0, "chunk_total": 0}
    try:
        cfg = load_config()
        vault_path = cfg.get("vault_path", "")
        if not vault_path or not Path(vault_path).is_dir():
            raise HTTPException(status_code=400, detail="vault_path_not_set")

        stored = _pending_book_pdf[req.pdf_id]
        pdf_bytes, pdf_filename = stored["bytes"], stored["filename"]
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"pdf_parse_error: {e}")

        active = [c for c in req.chapters if c.get("enabled", True) and not c.get("is_section", False)]
        if not active:
            doc.close()
            raise HTTPException(status_code=400, detail="no_chapters_selected")
        for i, ch in enumerate(active):
            ch["chapter"] = i + 1

        _processing_status["stage"] = "Buch-Metadaten werden extrahiert..."
        _processing_status["progress"] = 0.05
        intro_text = "\n\n".join(doc[p].get_text() for p in range(min(5, len(doc))))
        book_meta = extract_metadata_regex(intro_text)
        if not book_meta.get("title"):
            book_meta["title"] = re.sub(r'[_\-.]', ' ', Path(pdf_filename).stem)[:80].strip()
        if req.book_title and req.book_title.strip():
            book_meta["title"] = req.book_title.strip()

        folder_name = derive_output_filename(book_meta, pdf_filename).replace(".md", "")

        _processing_status["stage"] = "Seitengrenzen werden ermittelt..."
        _processing_status["progress"] = 0.08
        chapters_with_pages = find_chapter_boundaries(doc, active)

        chapter_summaries, errors = await _execute_book_chapters(
            doc, chapters_with_pages, book_meta, pdf_filename, req.model, vault_path, folder_name,
        )
        doc.close()

        book_id = str(uuid.uuid4())[:12]
        _pending_book_drafts[book_id] = {
            "folder_name": folder_name, "book_meta": book_meta,
            "pdf_filename": pdf_filename, "vault_path": vault_path,
            "job_ids": [c["job_id"] for c in chapter_summaries],
        }
        del _pending_book_pdf[req.pdf_id]
        logger.info("BUCH RUN REVIEW-READY: %d Kapitel | %d Fehler | %s",
                    len(chapter_summaries), len(errors), folder_name)
        return {
            "status": "book_review_ready",
            "book_id": book_id,
            "folder": folder_name,
            "book_title": book_meta.get("title", ""),
            "chapters": chapter_summaries,
            "errors": errors,
        }
    finally:
        _processing_status["active"] = False
        _processing_status["stage"] = ""


@app.post("/process/book/run_dry")
async def process_book_run_dry(req: BookRunRequest):
    global _processing_status
    if req.pdf_id not in _pending_book_pdf:
        raise HTTPException(status_code=404, detail="pdf_not_found")
    _processing_status = {"active": True, "stage": "[DRY RUN] Vorbereitung...", "progress": 0.02,
                          "chunk_current": 0, "chunk_total": 0}
    try:
        cfg = load_config()
        vault_path = cfg.get("vault_path", "")
        if not vault_path or not Path(vault_path).is_dir():
            raise HTTPException(status_code=400, detail="vault_path_not_set")

        stored = _pending_book_pdf[req.pdf_id]
        pdf_filename = stored["filename"]

        active = [c for c in req.chapters if c.get("enabled", True) and not c.get("is_section", False)]
        if not active:
            raise HTTPException(status_code=400, detail="no_chapters_selected")
        for i, ch in enumerate(active):
            ch["chapter"] = i + 1

        book_meta = {"title": re.sub(r'[_\-.]', ' ', Path(pdf_filename).stem)[:80].strip(), "author": "", "year": ""}
        folder_name = derive_output_filename(book_meta, pdf_filename).replace(".md", "")
        book_dir = Path(vault_path) / "Bücher" / folder_name
        book_dir.mkdir(parents=True, exist_ok=True)

        n = len(active)
        _processing_status["chunk_total"] = n
        processed_chapters: list[dict] = []
        overview_link = f"Bücher/{folder_name}/00-Uebersicht"
        book_title_safe = book_meta.get("title", "").replace('"', "'")

        for i, ch in enumerate(active):
            chapter_num = ch.get("chapter", i + 1)
            chapter_title = ch.get("title", f"Kapitel {chapter_num}")
            chapter_author = ch.get("author")
            _processing_status["stage"] = f"[DRY RUN] {chapter_num}/{n}: {chapter_title[:35]}"
            _processing_status["progress"] = 0.10 + 0.82 * (i / n)
            _processing_status["chunk_current"] = chapter_num
            await asyncio.sleep(0.5)
            if chapter_author:
                author_normalized = ", ".join(parse_author_list(chapter_author))
                author_field = f"author: {author_normalized}\n"
            else:
                author_field = ""
            chapter_filename = derive_chapter_filename(chapter_num, chapter_title)
            frontmatter = (
                f"---\ntitle: {yaml_str(chapter_title)}\n{author_field}chapter: {chapter_num}\n"
                f'book: "[[{overview_link}|{book_title_safe}]]"\n'
                f"tags:\n  - book-chapter\nsource_pdf: {yaml_str(pdf_filename)}\n"
                f"mneme_version: {MNEME_VERSION}\n---\n\n"
                f"> Teil von [[{overview_link}|{book_title_safe}]] *(Dry-Run)*\n\n"
                f"## Volltext\n\n*[Dry-run — kein Inhalt]*\n"
            )
            (book_dir / chapter_filename).write_text(frontmatter, encoding="utf-8")
            processed_chapters.append({
                "chapter": chapter_num, "title": chapter_title,
                "filename": chapter_filename, "author": chapter_author,
                "links": 0, "new_terms": 0,
            })

        _write_book_overview(book_dir, book_meta, folder_name, pdf_filename)
        logger.info("BUCH DRY-RUN FERTIG: %d Kapitel | %s", n, folder_name)
        return {
            "status": "book_ready", "folder": folder_name,
            "book_title": book_meta.get("title", ""),
            "chapters": processed_chapters, "errors": [],
        }
    finally:
        _processing_status["active"] = False
        _processing_status["stage"] = ""


@app.post("/process/book")
async def process_book(file: UploadFile = File(...), model: str = "auto"):
    global _processing_status
    _processing_status = {"active": True, "stage": "Buch wird geladen...", "progress": 0.02,
                          "chunk_current": 0, "chunk_total": 0}
    try:
        return await _process_book_inner(file, model)
    finally:
        _processing_status["active"] = False
        _processing_status["stage"] = ""


def _write_book_overview(book_dir: Path, book_meta: dict, folder_name: str, pdf_filename: str):
    author_str = book_meta.get("author", "")
    authors_list = parse_author_list(author_str)
    authors_yaml = "authors:\n" + "".join(f"  - {a}\n" for a in authors_list) if authors_list else ""
    content = (
        f"---\ntitle: {yaml_str(book_meta.get('title', ''))}\nauthor: {yaml_str(author_str)}\n"
        f"{authors_yaml}year: {book_meta.get('year', '')}\ntype: book\n"
        f"tags:\n  - book-note\nsource_pdf: {yaml_str(pdf_filename)}\n"
        f"mneme_version: {MNEME_VERSION}\n---\n\n"
        f"## Inhalt\n\n"
        f"```dataview\n"
        f'LIST FROM "Bücher/{folder_name}"\n'
        f'WHERE file.name != "00-Uebersicht"\n'
        f"SORT file.name ASC\n"
        f"```\n"
    )
    (book_dir / "00-Uebersicht.md").write_text(content, encoding="utf-8")


async def _execute_book_chapters(
    doc, chapters_with_pages: list[dict], book_meta: dict,
    pdf_filename: str, model: str, vault_path: str, folder_name: str,
) -> tuple[list[dict], list[dict]]:
    """Process chapters, store drafts in _queue_jobs for review, return (chapter_summaries, errors)."""
    global _queue_jobs
    n = len(chapters_with_pages)
    _processing_status["chunk_total"] = n
    chapter_summaries: list[dict] = []
    errors: list[dict] = []
    accumulated_terms: dict[str, dict] = {}
    overview_link = f"Bücher/{folder_name}/00-Uebersicht"
    book_title_safe = book_meta.get("title", "").replace('"', "'")

    for i, chapter in enumerate(chapters_with_pages):
        chapter_num = chapter.get("chapter", i + 1)
        chapter_title = re.sub(r'[\x00-\x1f\x7f]', '', chapter.get("title", f"Kapitel {chapter_num}")).strip() or f"Kapitel {chapter_num}"
        chapter_author = chapter.get("author") or ""
        pdf_start = chapter.get("pdf_page", 0)
        if i + 1 < n:
            pdf_end = chapters_with_pages[i + 1].get("pdf_page", len(doc))
        else:
            pdf_end = _pdf_page_from_printed(chapter.get("page_end"), len(doc))
        chapter_text = "\n\n".join(
            doc[p].get_text() for p in range(pdf_start, min(pdf_end, len(doc)))
        ).strip()
        if len(chapter_text) < 30:
            continue

        _processing_status["stage"] = f"Kapitel {chapter_num}/{n}: {chapter_title[:35]}"
        _processing_status["progress"] = 0.10 + 0.82 * (i / n)
        _processing_status["chunk_current"] = chapter_num

        chapter_filename = derive_chapter_filename(chapter_num, chapter_title)
        chapter_rel_path = f"Bücher/{folder_name}/{chapter_filename}"
        try:
            draft = await _process_pdf_bytes(
                None, chapter_filename, model,
                stage_prefix=f"[{chapter_num}/{n}] ",
                full_text_override=chapter_text,
                extra_cached_terms=accumulated_terms,
                meta_override={"title": chapter_title, "author": chapter_author} if chapter_author else {"title": chapter_title},
            )
            # Build book chapter frontmatter (overrides article frontmatter in draft)
            if chapter_author:
                author_normalized = ", ".join(parse_author_list(chapter_author))
                author_field = f"author: {author_normalized}\n"
            else:
                author_field = ""
            draft["frontmatter"] = (
                f"---\ntitle: {yaml_str(chapter_title)}\n{author_field}chapter: {chapter_num}\n"
                f'book: "[[{overview_link}|{book_title_safe}]]"\n'
                f"tags:\n  - book-chapter\n"
                f"source_pdf: {yaml_str(pdf_filename)}\n"
                f"mneme_version: {MNEME_VERSION}\n---\n\n"
                f"> Teil von [[{overview_link}|{book_title_safe}]]\n\n"
            )
            draft["output_filename"] = chapter_rel_path
            # Accumulate terms for subsequent chapters
            for term in draft["new_terms"]:
                c = term["canonical"]
                if c not in accumulated_terms:
                    accumulated_terms[c] = {
                        "type": term.get("type"),
                        "aliases": term.get("aliases", [c]),
                        "translations": term.get("translations", {}),
                        "forms": term.get("aliases", [c]),
                    }
            # Register draft in queue_jobs so /process/queue/confirm handles it
            job_id = str(uuid.uuid4())[:12]
            _queue_jobs[job_id] = {"status": "done", "filename": chapter_filename, "draft": draft,
                                   "error": None, "stage": "Fertig"}
            chapter_summaries.append({
                "job_id": job_id,
                "chapter_num": chapter_num,
                "title": chapter_title,
                "author": chapter_author,
                "filename": chapter_filename,
                "tokens": draft["token_list"],
                "stats": draft["stats"],
                "cost": draft["cost"],
                "meta": draft.get("meta", {}),
                "content": draft.get("preview_content", ""),
            })
        except Exception as e:
            logger.warning("Kapitel %d fehlgeschlagen: %s", chapter_num, e, exc_info=True)
            errors.append({"chapter": chapter_num, "title": chapter_title, "error": str(e)})

    return chapter_summaries, errors


async def _process_book_inner(file: UploadFile, model: str) -> dict:
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="empty_file")

    api_key = get_anthropic_key(cfg)
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="claude_api_key_missing")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"pdf_parse_error: {e}")

    # Phase 0: Chapter detection from first 15 pages
    _processing_status["stage"] = "Kapitelstruktur wird erkannt..."
    _processing_status["progress"] = 0.04
    toc_text = "\n\n".join(doc[p].get_text() for p in range(min(25, len(doc))))
    try:
        chapters = parse_chapter_structure(call_claude(api_key, build_chapter_prompt(toc_text), max_tokens=1024))
    except Exception as e:
        logger.warning("Kapitel-Extraktion fehlgeschlagen: %s", e, exc_info=True)
        chapters = []

    if not chapters:
        doc.close()
        draft = await _process_pdf_bytes(pdf_bytes, file.filename or "book.pdf", model)
        global _pending_draft
        _pending_draft = draft
        return {"status": "review_ready", "draft": {
            "filename": draft["output_filename"], "content": draft["preview_content"],
            "tokens": draft["token_list"], "duplicate_suggestions": draft["duplicate_suggestions"],
            "stats": draft["stats"], "cost": draft["cost"],
        }}

    chapters_with_pages = find_chapter_boundaries(doc, chapters)

    _processing_status["stage"] = "Buch-Metadaten werden extrahiert..."
    _processing_status["progress"] = 0.07
    intro_text = "\n\n".join(doc[p].get_text() for p in range(min(5, len(doc))))
    try:
        book_meta = parse_metadata(call_claude(api_key, build_metadata_prompt(intro_text), max_tokens=256))
    except Exception:
        book_meta = extract_metadata_regex(intro_text)
    if not book_meta.get("title"):
        book_meta["title"] = re.sub(r'[_\-.]', ' ', Path(file.filename or "book").stem)[:80].strip()

    folder_name = derive_output_filename(book_meta, file.filename or "book.pdf").replace(".md", "")

    processed_chapters, errors = await _execute_book_chapters(
        doc, chapters_with_pages, book_meta,
        file.filename or "book.pdf", model, vault_path, folder_name,
    )
    doc.close()

    _processing_status["stage"] = "Übersicht wird erstellt..."
    _processing_status["progress"] = 0.96
    book_dir = Path(vault_path) / "Bücher" / folder_name
    _write_book_overview(book_dir, book_meta, folder_name, file.filename or "book.pdf")
    logger.info("BUCH FERTIG: %d Kapitel | %d Fehler | %s | Errors: %s",
                len(processed_chapters), len(errors), folder_name,
                [(e["chapter"], e["error"]) for e in errors])

    return {
        "status": "book_ready",
        "overview": f"Bücher/{folder_name}/00-Uebersicht.md",
        "folder": folder_name,
        "book_title": book_meta.get("title", ""),
        "chapters": processed_chapters,
        "errors": errors,
    }


@app.get("/authors")
def get_authors():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path:
        return {"authors": [], "count": 0}
    personen_dir = Path(vault_path) / "Personen"
    if not personen_dir.is_dir():
        return {"authors": [], "count": 0}
    authors = []
    for md_file in sorted(personen_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            if "author" in content[:300]:
                authors.append({
                    "name": md_file.stem,
                    "file": str(md_file.relative_to(Path(vault_path))),
                })
        except Exception:
            pass
    return {"authors": authors, "count": len(authors)}


@app.get("/jobs")
def get_jobs(limit: int = 50):
    if not JOBS_PATH.exists():
        return {"jobs": [], "count": 0}
    try:
        lines = [ln for ln in JOBS_PATH.read_text(encoding="utf-8").strip().split("\n") if ln.strip()]
        recent = [json.loads(ln) for ln in lines[-limit:]]
        recent.reverse()
        return {"jobs": recent, "count": len(lines)}
    except Exception as e:
        logger.warning("Jobs-Lesen fehlgeschlagen: %s", e)
        return {"jobs": [], "count": 0}


@app.post("/authors/fix-stubs")
def fix_author_stubs():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    personen_dir = Path(vault_path) / "Personen"
    if not personen_dir.is_dir():
        return {"ok": True, "fixed": 0, "skipped": 0}
    fixed = 0
    skipped = 0
    for md_file in personen_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            name = md_file.stem
            if "## Werke" in content:
                skipped += 1
                continue
            if "- author" not in content[:400] and "type: person" not in content[:400]:
                skipped += 1
                continue
            md_file.write_text(content.rstrip() + _dataview_block(name), encoding="utf-8")
            fixed += 1
        except Exception:
            skipped += 1
    logger.info("FIX AUTHOR STUBS: %d fixed, %d skipped", fixed, skipped)
    return {"ok": True, "fixed": fixed, "skipped": skipped}


@app.post("/authors/fix-dataview-query")
def fix_dataview_query():
    """Update Dataview queries in Personen/ stubs to current format."""
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    personen_dir = Path(vault_path) / "Personen"
    if not personen_dir.is_dir():
        return {"ok": True, "fixed": 0}
    fixed = 0
    for md_file in personen_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            name = md_file.stem
            if "## Werke" not in content:
                continue
            new_content = content
            correct = f'WHERE contains(string(author), "{name}") OR contains(string(authors), "{name}")'
            # Remove FROM "/" from TABLE line (v2.9.2 and earlier)
            new_content = new_content.replace('TABLE year, journal FROM "/"', 'TABLE year, journal')
            # Replace v2.9.0 wrong format
            new_content = new_content.replace(
                f'WHERE author = [[{name}]] OR contains(authors, [[{name}]])', correct
            )
            # Replace v2.8 format (missing string() on authors)
            new_content = new_content.replace(
                f'WHERE contains(string(author), "{name}") OR contains(authors, "{name}")', correct
            )
            if new_content != content:
                md_file.write_text(new_content, encoding="utf-8")
                fixed += 1
        except Exception:
            pass
    logger.info("FIX DATAVIEW QUERY: %d fixed", fixed)
    return {"ok": True, "fixed": fixed}


@app.post("/authors/fix-author-field")
def fix_author_field():
    """Fix literature notes: strip wikilink brackets from author fields (plain text for Dataview)."""
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    fixed = 0
    for md_file in Path(vault_path).rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if "literature-note" not in content[:500]:
                continue
            new_content = content
            # author: '[[Name]]' or "[[Name]]" → author: Name
            new_content = re.sub(
                r"^(author:\s*)['\"]?\[\[([^\]]+)\]\]['\"]?",
                r"\1\2",
                new_content,
                flags=re.MULTILINE,
            )
            # authors list: '  - '[[Name]]'' or "[[Name]]" → '  - Name'
            new_content = re.sub(
                r"^(\s+-\s+)['\"]?\[\[([^\]]+)\]\]['\"]?",
                r"\1\2",
                new_content,
                flags=re.MULTILINE,
            )
            if new_content != content:
                md_file.write_text(new_content, encoding="utf-8")
                fixed += 1
        except Exception:
            pass
    logger.info("FIX AUTHOR FIELD: %d files fixed", fixed)
    return {"ok": True, "fixed": fixed}


@app.post("/vault/reset")
def vault_reset():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    deleted_dirs = 0
    deleted_files = 0
    for folder in ("Personen", "Methoden", "Konzepte"):
        d = Path(vault_path) / folder
        if d.is_dir():
            shutil.rmtree(d)
            deleted_dirs += 1
    tok_path = Path(vault_path) / TOKENS_FILENAME
    if tok_path.exists():
        tok_path.unlink()
        deleted_files += 1
    logger.info("VAULT RESET: %d Ordner, %d Dateien gelöscht", deleted_dirs, deleted_files)
    return {"ok": True, "deleted_dirs": deleted_dirs, "deleted_files": deleted_files}


_relink_status: dict = {"active": False, "checked": 0, "total": 0, "updated": 0, "elapsed_s": 0}


@app.get("/vault/relink/status")
def vault_relink_status():
    return _relink_status


@app.post("/vault/relink")
def vault_relink_start(background_tasks: BackgroundTasks):
    global _relink_status
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    if _relink_status.get("active"):
        raise HTTPException(status_code=409, detail="relink_already_running")
    background_tasks.add_task(_run_relink, vault_path)
    return {"status": "started"}


def _run_relink(vault_path: str):
    import time
    global _relink_status
    t0 = time.time()
    _relink_status = {"active": True, "checked": 0, "total": 0, "updated": 0, "elapsed_s": 0}
    try:
        cache = load_token_cache(vault_path)
        if not cache:
            return
        terms = [{"canonical": k, **v} for k, v in cache.items()]
        vault = Path(vault_path)
        files: list[Path] = list(vault.glob("*.md"))
        bucher = vault / "Bücher"
        if bucher.is_dir():
            files.extend(bucher.rglob("*.md"))
        _relink_status["total"] = len(files)
        updated = 0
        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
                new_content = apply_wikilinks(content, terms)
                if new_content != content:
                    f.write_text(new_content, encoding="utf-8")
                    updated += 1
            except Exception as e:
                logger.warning("Relink: %s — %s", f.name, e)
            _relink_status["checked"] += 1
        _relink_status["updated"] = updated
        _relink_status["elapsed_s"] = round(time.time() - t0, 1)
        logger.info("VAULT RELINK: %d geprüft, %d aktualisiert", len(files), updated)
    finally:
        _relink_status["active"] = False


@app.post("/tokens/migrate")
def migrate_tokens():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
    tok_path = Path(vault_path) / TOKENS_FILENAME
    if not tok_path.exists():
        return {"ok": True, "migrated": 0, "already_new": 0, "message": "Keine tokens.json gefunden"}
    try:
        data = json.loads(tok_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="tokens_read_error")
    flat_terms = [k for k, v in data.items() if not k.startswith("_") and isinstance(v, list)]
    if not flat_terms:
        return {"ok": True, "migrated": 0, "already_new": len([k for k in data if not k.startswith("_")]),
                "message": "Bereits im neuen Format"}
    new_data = {"_mneme_version": MNEME_VERSION}
    for k, v in data.items():
        if k.startswith("_"):
            continue
        if isinstance(v, list):
            new_data[k] = {"type": None, "aliases": v, "translations": {}, "forms": list(v)}
        else:
            new_data[k] = v
    tok_path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "migrated": len(flat_terms), "already_new": 0,
            "message": f"{len(flat_terms)} Begriffe ins neue Format migriert"}


@app.get("/vault/raw_pdfs")
def get_raw_pdfs():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path:
        return {"pdfs": [], "folder": "", "count": 0}
    raw_folder = Path(vault_path) / "RAW-Data"
    if not raw_folder.is_dir():
        return {"pdfs": [], "folder": str(raw_folder), "count": 0}
    pdfs = sorted(str(p) for p in raw_folder.rglob("*.pdf"))
    return {"pdfs": pdfs, "folder": str(raw_folder), "count": len(pdfs)}


@app.post("/process/bulk")
async def process_bulk(req: BulkRequest):
    global _pending_bulk, _processing_status
    all_drafts: list[dict] = []
    all_tokens: list[dict] = []
    seen_canonical: set[str] = set()
    results: list[dict] = []
    n = len(req.pdf_paths)

    for i, pdf_path in enumerate(req.pdf_paths):
        name = Path(pdf_path).name
        _processing_status = {
            "active": True,
            "stage": f"PDF {i + 1}/{n}: {name}",
            "progress": i / n,
            "chunk_current": 0,
            "chunk_total": 0,
        }
        try:
            pdf_bytes = Path(pdf_path).read_bytes()
            draft = await _process_pdf_bytes(pdf_bytes, name, req.model,
                                             stage_prefix=f"[{i + 1}/{n}] ")
            all_drafts.append(draft)
            for tok in draft["token_list"]:
                c = tok["canonical"]
                if c not in seen_canonical:
                    seen_canonical.add(c)
                    all_tokens.append({**tok, "source": name})
            results.append({"pdf": pdf_path, "filename": draft["output_filename"],
                            "stats": draft["stats"]})
        except HTTPException as e:
            results.append({"pdf": pdf_path, "error": e.detail})
        except Exception as e:
            results.append({"pdf": pdf_path, "error": str(e)})

    _processing_status["active"] = False
    _processing_status["stage"] = ""
    _pending_bulk = {"drafts": all_drafts, "token_list": all_tokens}

    ok = [r for r in results if "error" not in r]
    return {
        "status": "bulk_review_ready",
        "results": results,
        "token_list": all_tokens,
        "stats": {
            "processed": len(ok),
            "errors": len(results) - len(ok),
            "new_tokens": sum(1 for t in all_tokens if t["is_new"] and t["selected"]),
            "filtered_tokens": sum(1 for t in all_tokens if not t["selected"]),
        },
    }


@app.post("/process/bulk_confirm")
def bulk_confirm(req: BulkConfirmRequest):
    global _pending_bulk
    if not _pending_bulk:
        raise HTTPException(status_code=400, detail="no_pending_bulk")

    selected_set = set(req.selected_terms)
    confirmed: list[dict] = []
    errors: list[dict] = []

    for draft in _pending_bulk["drafts"]:
        vault_path = draft["vault_path"]
        selected_new = [t for t in draft["new_terms"] if t["canonical"] in selected_set]

        for merge in req.merged_terms:
            keep_c, remove_c = merge.get("keep"), merge.get("remove")
            if not keep_c or not remove_c:
                continue
            keep_term = next((t for t in selected_new if t["canonical"] == keep_c), None)
            if keep_term:
                remove_term = next((t for t in draft["new_terms"] if t["canonical"] == remove_c), None)
                if remove_term:
                    keep_term["aliases"] = sorted(
                        set(keep_term.get("aliases", [])) | set(remove_term.get("aliases", [])) | {remove_c}
                    )
            selected_new = [t for t in selected_new if t["canonical"] != remove_c]

        try:
            final_terms = merge_terms(
                [draft["cached_terms"], selected_new],
                draft["base_links"], draft["vault_links"], draft["full_text"],
            )
            body = draft.get("sections_text", draft["full_text"])
            content = apply_wikilinks(draft["frontmatter"] + body, final_terms)
            output_filename = draft["output_filename"]
            (Path(vault_path) / output_filename).write_text(content, encoding="utf-8")
            save_token_cache(vault_path, selected_new)
            term_types = {t["canonical"]: t.get("type") for t in selected_new}
            found_links = set(re.findall(r'\[\[([^\[\]|#]+?)(?:\|[^\[\]]+?)?\]\]', content))
            stubs_created, _ = create_stubs(vault_path, found_links, output_filename, term_types)
            draft_meta = draft.get("meta", {})
            if draft_meta.get("author"):
                update_author_stub(vault_path, draft_meta["author"], {
                    "title": draft_meta.get("title", ""),
                    "year": draft_meta.get("year", ""),
                    "file": output_filename.replace(".md", ""),
                    "doi": draft_meta.get("doi", ""),
                }, draft_meta.get("affiliation", ""))
            confirmed.append({"filename": output_filename, "stubs_created": stubs_created})
        except Exception as e:
            errors.append({"filename": draft["output_filename"], "error": str(e)})

    # Vault merges (applied once, using first draft's vault path)
    if req.merged_terms and _pending_bulk["drafts"]:
        vault_path = _pending_bulk["drafts"][0]["vault_path"]
        tok_path = Path(vault_path) / TOKENS_FILENAME
        try:
            data = json.loads(tok_path.read_text(encoding="utf-8"))
            for merge in req.merged_terms:
                keep_c, remove_c = merge.get("keep"), merge.get("remove")
                if keep_c in data and remove_c in data:
                    data[keep_c] = sorted(set(data[keep_c]) | set(data[remove_c]) | {remove_c})
                    del data[remove_c]
                    rename_wikilinks_in_vault(vault_path, remove_c, keep_c)
            tok_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    _pending_bulk = None
    return {"ok": True, "confirmed": confirmed, "errors": errors, "total": len(confirmed)}


@app.get("/wikilinks")
def get_wikilinks():
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        return {"links": [], "count": 0}
    links = extract_wikilinks(vault_path)
    return {"links": links, "count": len(links)}


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


@app.post("/process")
async def process_pdf(file: UploadFile = File(...), model: str = "auto"):
    global _processing_status
    _processing_status = {"active": True, "stage": "PDF wird gelesen...", "progress": 0.05,
                          "chunk_current": 0, "chunk_total": 0}
    try:
        return await _process_pdf_inner(file, model)
    finally:
        _processing_status["active"] = False
        _processing_status["stage"] = ""


async def _process_pdf_inner(file: UploadFile, model: str):
    global _pending_draft
    pdf_bytes = await file.read()
    draft = await _process_pdf_bytes(pdf_bytes, file.filename or "document.pdf", model)
    _pending_draft = draft
    return {
        "status": "review_ready",
        "draft": {
            "filename": draft["output_filename"],
            "content": draft["preview_content"],
            "tokens": draft["token_list"],
            "duplicate_suggestions": draft["duplicate_suggestions"],
            "stats": draft["stats"],
            "cost": draft["cost"],
        },
    }


async def _process_pdf_bytes(pdf_bytes: bytes | None, filename: str, model: str,
                              stage_prefix: str = "",
                              full_text_override: str | None = None,
                              extra_cached_terms: dict | None = None,
                              meta_override: dict | None = None,
                              stage_callback=None,
                              cancel_job_id: str | None = None) -> dict:
    """Core processing. Returns a complete draft dict ready for review or bulk confirm."""
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")

    _process_start = datetime.datetime.now()

    pdf_meta_title = ""

    if full_text_override is not None:
        full_text = full_text_override.strip()
        if len(full_text) < 50:
            raise HTTPException(status_code=422, detail="scanned_pdf_or_empty")
    elif pdf_bytes:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text = [extract_page_text_smart(page) for page in doc]
            pdf_meta_title = _extract_pdf_title(doc)
            doc.close()
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"pdf_parse_error: {e}")
        full_text = "\n\n".join(pages_text).strip()
        if len(full_text) < 100:
            raise HTTPException(status_code=422, detail="scanned_pdf_or_empty")
    else:
        raise HTTPException(status_code=400, detail="empty_file")

    def _stage(s: str, p: float):
        _processing_status["stage"] = f"{stage_prefix}{s}"
        _processing_status["progress"] = p
        if stage_callback:
            stage_callback(s)

    def _check_cancel():
        if cancel_job_id and cancel_job_id in _cancel_flags:
            _cancel_flags.discard(cancel_job_id)
            raise HTTPException(status_code=499, detail="cancelled_by_user")

    _stage("Vault wird gescannt...", 0.10)
    vault_links = extract_wikilinks(vault_path)
    base_links = load_psych_base_links()

    requested = model if model != "auto" else cfg.get("default_model", "auto")
    ollama_model = cfg.get("ollama_model", "llama3.1:8b")
    api_key = get_anthropic_key(cfg)

    if requested == "claude" and not api_key.strip():
        raise HTTPException(status_code=400, detail="claude_api_key_missing")

    phase1_model, meta_model = await resolve_models(requested, api_key, ollama_model)
    if phase1_model == "claude" and not api_key.strip():
        raise HTTPException(status_code=400, detail="claude_api_key_missing")

    _last_run_stats.update({
        "input_tokens": 0, "output_tokens": 0, "calls": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
        "phase1_model": phase1_model, "meta_model": meta_model,
    })
    logger.info("PHASE1: %s | META: %s | FILE: %s", phase1_model, meta_model, filename)

    # Phase 0: Token-Cache
    token_cache = load_token_cache(vault_path)
    cached_terms = [
        {"canonical": c, "aliases": entry.get("forms", entry.get("aliases", [c]))}
        for c, entry in token_cache.items()
    ]
    cached_canonical = set(token_cache.keys())
    # Build lowercase alias map for alias-conflict detection
    cached_alias_map: dict[str, str] = {}
    for c, entry in token_cache.items():
        cached_alias_map[c.lower()] = c
        for f in entry.get("forms", []) + entry.get("aliases", []):
            if f and f.lower() not in cached_alias_map:
                cached_alias_map[f.lower()] = c
    # Merge accumulated terms from earlier chapters (book mode only)
    if extra_cached_terms:
        for c, entry in extra_cached_terms.items():
            if c not in token_cache:
                token_cache[c] = entry
        cached_terms = [
            {"canonical": c, "aliases": e.get("forms", e.get("aliases", [c]))}
            for c, e in token_cache.items()
        ]
        cached_canonical = set(token_cache.keys())
        cached_alias_map = {}
        for c, e in token_cache.items():
            cached_alias_map[c.lower()] = c
            for f in e.get("forms", []) + e.get("aliases", []):
                if f and f.lower() not in cached_alias_map:
                    cached_alias_map[f.lower()] = c
    logger.info("TOKEN CACHE: %d bekannte Begriffe (davon %d akkumuliert)",
                len(cached_terms), len(extra_cached_terms) if extra_cached_terms else 0)

    chunks_count = 0
    meta: dict = {}
    # {canonical, aliases, type, keep, translations}
    claude_tokens: list[dict] = []

    # === AUTO MODE: Ollama → single Claude quality-pass call ===
    if phase1_model == "ollama" and meta_model == "claude":
        if not await ollama_available(ollama_model):
            raise HTTPException(status_code=503, detail="ollama_unavailable")
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS_OLLAMA)
        chunks_count = len(p1_chunks)
        _processing_status["chunk_total"] = chunks_count
        all_raw: list[str] = []
        # Batch chunks (≤3 per Ollama call) to reduce latency
        batched = [" ".join(p1_chunks[i:i + OLLAMA_BATCH_SIZE])
                   for i in range(0, chunks_count, OLLAMA_BATCH_SIZE)]
        n_batches = len(batched)
        for bi, batch_chunk in enumerate(batched):
            _check_cancel()
            _stage(f"Batch {bi + 1}/{n_batches} — Ollama...", 0.15 + 0.38 * (bi / max(n_batches, 1)))
            _processing_status["chunk_current"] = min((bi + 1) * OLLAMA_BATCH_SIZE, chunks_count)
            raw = await call_ollama(ollama_model, build_recognition_prompt_ollama(batch_chunk))
            terms = parse_terms_simple(raw)
            all_raw.extend(t["canonical"] for t in terms)
            logger.info("BATCH %d/%d [Ollama]: %d Begriffe", bi + 1, n_batches, len(terms))

        _stage("Claude Quality-Pass (1 Call)...", 0.58)
        unique_raw = list(dict.fromkeys(t for t in all_raw if t not in cached_canonical))
        try:
            combined_raw = call_claude_with_cache(
                api_key, _COMBINED_SYSTEM_PROMPT,
                build_combined_user_blocks(unique_raw, full_text[:3000]),
                max_tokens=4096,
            )
            meta, claude_tokens = parse_combined_response(combined_raw)
        except Exception as e:
            logger.warning("Combined Claude call fehlgeschlagen (%s), Fallback", e)
            meta = extract_metadata_regex(full_text)
            raw_list = [{"canonical": t, "aliases": [t]} for t in unique_raw]
            kept, filtered = filter_noisy_terms(raw_list)
            claude_tokens = (
                [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": True}
                 for t in kept] +
                [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": False}
                 for t in filtered]
            )

    # === OLLAMA-ONLY MODE ===
    elif phase1_model == "ollama" and meta_model == "regex":
        if not await ollama_available(ollama_model):
            raise HTTPException(status_code=503, detail="ollama_unavailable")
        _stage("Metadaten werden extrahiert...", 0.12)
        meta = extract_metadata_regex(full_text)
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS_OLLAMA)
        chunks_count = len(p1_chunks)
        _processing_status["chunk_total"] = chunks_count
        all_raw = []
        batched = [" ".join(p1_chunks[i:i + OLLAMA_BATCH_SIZE])
                   for i in range(0, chunks_count, OLLAMA_BATCH_SIZE)]
        n_batches = len(batched)
        for bi, batch_chunk in enumerate(batched):
            _check_cancel()
            _stage(f"Batch {bi + 1}/{n_batches} — Ollama...", 0.15 + 0.65 * (bi / max(n_batches, 1)))
            _processing_status["chunk_current"] = min((bi + 1) * OLLAMA_BATCH_SIZE, chunks_count)
            raw = await call_ollama(ollama_model, build_recognition_prompt_ollama(batch_chunk))
            all_raw.extend(t["canonical"] for t in parse_terms_simple(raw))
        unique_raw = list(dict.fromkeys(t for t in all_raw if t not in cached_canonical))
        raw_list = [{"canonical": t, "aliases": [t]} for t in unique_raw]
        kept, filtered = filter_noisy_terms(raw_list)
        claude_tokens = (
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": True, "translations": {}}
             for t in kept] +
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": False, "translations": {}}
             for t in filtered]
        )

    # === CLAUDE-ONLY MODE ===
    else:
        _stage("Metadaten werden extrahiert...", 0.12)
        try:
            meta = parse_metadata(call_claude(api_key, build_metadata_prompt(full_text), max_tokens=256))
        except Exception as e:
            logger.warning("Metadata-Call fehlgeschlagen (%s), Fallback", e)
            meta = extract_metadata_regex(full_text)
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS)
        chunks_count = len(p1_chunks)
        _processing_status["chunk_total"] = chunks_count
        term_lists = []
        for i, chunk in enumerate(p1_chunks):
            _check_cancel()
            _stage(f"Chunk {i + 1}/{chunks_count} — Claude...", 0.15 + 0.65 * (i / chunks_count))
            _processing_status["chunk_current"] = i + 1
            try:
                raw = call_claude(api_key, build_recognition_prompt(chunk), max_tokens=2048)
                terms = parse_terms(raw)
            except Exception as e:
                logger.warning("Claude Chunk %d fehlgeschlagen: %s", i + 1, e)
                terms = []
            logger.info("CHUNK %d/%d [Claude]: %d Begriffe", i + 1, chunks_count, len(terms))
            term_lists.append(terms)
        raw_new = merge_terms(term_lists, [], [], full_text)
        unique_new = [t for t in raw_new if t["canonical"] not in cached_canonical]
        kept, filtered = filter_noisy_terms(unique_new)
        claude_tokens = (
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": True, "translations": {}}
             for t in kept] +
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": False, "translations": {}}
             for t in filtered]
        )

    # Fallback: if metadata empty, try regex
    if not any(meta.get(k) for k in ("title", "author", "year")):
        meta = extract_metadata_regex(full_text)
    # Title priority: 1) PDF metadata  2) Claude  3) filename
    if pdf_meta_title:
        meta["title"] = pdf_meta_title
    elif not meta.get("title") or meta.get("title") == "null":
        meta["title"] = re.sub(r'[_\-.]', ' ', Path(filename).stem)[:80].strip()
    if meta_override:
        for k, v in meta_override.items():
            if v:
                meta[k] = v
    logger.info("METADATA: %s (via %s)", {k: v for k, v in meta.items() if k != "citation_chicago"}, meta_model)

    # Phase 3: Text structuring + wikilink application
    _stage("Wikilinks werden gesetzt...", 0.82)

    kept_for_preview = [
        {"canonical": t["canonical"], "aliases": t["aliases"]}
        for t in claude_tokens if t.get("keep", True)
    ]
    preview_terms = merge_terms([cached_terms, kept_for_preview], base_links, vault_links, full_text)

    # Sections: use Claude's analysis if available, else heuristic
    sections_info = meta.get("sections", {})
    abstract_h, main_body_h, references_h = structure_text_sections(full_text)

    if sections_info.get("has_abstract") is False:
        abstract = ""
    elif sections_info.get("abstract_text"):
        abstract = sections_info["abstract_text"]
    else:
        abstract = abstract_h

    if sections_info.get("has_bibliography") is False:
        references = ""
    elif sections_info.get("bibliography_start"):
        kw = re.escape(sections_info["bibliography_start"])
        bib_m = re.search(r'\n' + kw + r'\s*\n', full_text, re.IGNORECASE)
        references = full_text[bib_m.start():].strip() if bib_m else references_h
    else:
        references = references_h

    main_body = main_body_h

    # Clean header block (institute, DOI, ISSN etc.) from body text
    body_start_marker = meta.get("body_start_marker", "")
    clean_body = clean_header_text(full_text, body_start_marker)

    sections_parts = []
    if abstract:
        sections_parts.append(f"## Abstract\n\n{abstract}")
    sections_parts.append(f"## Volltext\n\n{clean_body}")
    if references:
        sections_parts.append(f"## Literatur\n\n{references}")
    sections_text = "\n\n".join(sections_parts)

    # Frontmatter — Literature-Note format
    author_str = meta.get("author", "")
    authors_list = parse_author_list(author_str)
    frontmatter = f"---\ntitle: {yaml_str(meta.get('title', ''))}\n"
    frontmatter += format_author_yaml(author_str, authors_list)
    frontmatter += f"year: {meta.get('year', '')}\n"
    for fld in ("journal", "doi"):
        if meta.get(fld):
            frontmatter += f"{fld}: {meta[fld]}\n"
    if meta.get("citation_apa"):
        frontmatter += f"citation_apa: {yaml_str(meta['citation_apa'])}\n"
    if meta.get("citation_chicago"):
        frontmatter += f"citation_chicago: {yaml_str(meta['citation_chicago'])}\n"
    frontmatter += f"tags:\n  - literature-note\nsource_pdf: {yaml_str(filename)}\nmneme_version: {MNEME_VERSION}\n---\n\n"

    preview_content = apply_wikilinks(frontmatter + sections_text, preview_terms)
    total_links = len(re.findall(r"\[\[.+?\]\]", preview_content))
    output_filename = derive_output_filename(meta, filename)

    _stage("Review wird vorbereitet...", 0.94)

    token_list = [
        {
            "canonical": t["canonical"],
            "is_new": (t["canonical"] not in cached_canonical
                       and t["canonical"].lower() not in cached_alias_map),
            "selected": bool(t.get("keep", True)),
            "filtered_reason": None if t.get("keep", True) else "claude_noise",
            "type": t.get("type"),
        }
        for t in claude_tokens
    ]
    dup_suggestions = find_review_duplicates([
        {"canonical": t["canonical"]} for t in claude_tokens if t.get("keep", True)
    ])
    truly_new = sum(1 for t in claude_tokens
                    if t.get("keep", True)
                    and t["canonical"] not in cached_canonical
                    and t["canonical"].lower() not in cached_alias_map)
    filtered_count = sum(1 for t in claude_tokens if not t.get("keep", True))

    logger.info("REVIEW READY: %d kept (%d new), %d filtered | %d links | %s",
                len(kept_for_preview), truly_new, filtered_count, total_links, output_filename)
    logger.info("[mneme] Claude calls this run: total=%d | input=%d tokens | cache_read=%d tokens",
                _last_run_stats["calls"], _last_run_stats["input_tokens"],
                _last_run_stats.get("cache_read_tokens", 0))

    return {
        "vault_path": vault_path,
        "source_pdf": filename,
        "frontmatter": frontmatter,
        "full_text": full_text,
        "sections_text": sections_text,
        "preview_content": preview_content,
        "output_filename": output_filename,
        "cached_terms": cached_terms,
        "new_terms": [
            {"canonical": t["canonical"], "aliases": t["aliases"], "type": t.get("type"),
             "translations": t.get("translations", {})}
            for t in claude_tokens
            if t["canonical"] not in cached_canonical
            and t["canonical"].lower() not in cached_alias_map
        ],
        "base_links": base_links,
        "vault_links": vault_links,
        "token_list": token_list,
        "duplicate_suggestions": dup_suggestions,
        "meta": meta,
        "stats": {
            "links_total": total_links,
            "filtered": filtered_count,
            "new": truly_new,
            "existing": len(cached_terms),
            "model_used": f"{phase1_model}/{meta_model}",
            "chunks": chunks_count,
            "citation_apa": meta.get("citation_apa", ""),
        },
        "process_elapsed_s": round(
            (datetime.datetime.now() - _process_start).total_seconds(), 1
        ),
        "cost": {
            "input_tokens": _last_run_stats["input_tokens"],
            "output_tokens": _last_run_stats["output_tokens"],
            "cache_read_tokens": _last_run_stats.get("cache_read_tokens", 0),
            "cache_creation_tokens": _last_run_stats.get("cache_creation_tokens", 0),
            "phase1_model": phase1_model,
        },
    }
