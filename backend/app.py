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
_processing_status: dict = {"active": False, "stage": "", "progress": 0.0,
                             "chunk_current": 0, "chunk_total": 0}
_pending_draft: dict | None = None
_pending_bulk: dict | None = None

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


def build_combined_prompt(term_list: list[str], context_text: str) -> str:
    terms_section = (
        "Begriffe von Ollama (roh, unbereinigt):\n" + "\n".join(f"- {t}" for t in term_list)
        if term_list
        else "Keine Vorab-Begriffe — erkenne selbst alle relevanten Begriffe aus dem Text."
    )
    return (
        "Du analysierst einen wissenschaftlichen Text.\n\n"
        "Deine Aufgaben:\n"
        "1. BEREINIGUNG: Entferne Noise (URLs, Impressum, Abbildungsreferenzen, generische Wörter ohne Fachbezug)\n"
        "2. NORMALISIERUNG: Fasse zusammen was zusammengehört (Imdahl + Max Imdahl → Max Imdahl)\n"
        "3. ERGÄNZUNG: Füge wichtige Begriffe hinzu die in der Liste fehlen aber im Text stehen\n"
        "4. KLASSIFIZIERUNG: Markiere jeden Begriff als person / concept / method (oder null)\n"
        "5. METADATEN: Extrahiere title, author, year, journal (falls vorhanden), doi (falls vorhanden)\n\n"
        "Antworte NUR mit folgendem JSON (kein anderer Text, keine Markdown-Blöcke):\n"
        '{"metadata": {"title": "...", "author": "...", "year": "...", "journal": "", "doi": ""},\n'
        ' "tokens": [\n'
        '   {"term": "Max Imdahl", "type": "person", "aliases": ["Imdahl", "Max Imdahls"], "keep": true},\n'
        '   {"term": "www.verlag.de", "type": null, "aliases": [], "keep": false}\n'
        " ]}\n\n"
        "keep: true = sinnvoller Wikilink-Begriff | keep: false = Noise\n\n"
        f"{terms_section}\n\n"
        f"Text (Kontext, erste 3000 Zeichen):\n{context_text}"
    )


def parse_combined_response(raw: str) -> tuple[dict, list[dict]]:
    try:
        cleaned = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not m:
            return {}, []
        data = json.loads(m.group())
        md = data.get("metadata", {}) or {}
        metadata = {
            "title": str(md.get("title") or ""),
            "author": str(md.get("author") or ""),
            "year": str(md.get("year") or ""),
            "journal": str(md.get("journal") or ""),
            "doi": str(md.get("doi") or ""),
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
            tokens.append({
                "canonical": term,
                "aliases": aliases,
                "type": t.get("type"),
                "keep": bool(t.get("keep", True)),
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


MNEME_VERSION = "2.3.0"


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


async def _process_pdf_bytes(pdf_bytes: bytes, filename: str, model: str,
                              stage_prefix: str = "") -> dict:
    """Core processing. Returns a complete draft dict ready for review or bulk confirm."""
    cfg = load_config()
    vault_path = cfg.get("vault_path", "")
    if not vault_path or not Path(vault_path).is_dir():
        raise HTTPException(status_code=400, detail="vault_path_not_set")
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

    def _stage(s: str, p: float):
        _processing_status["stage"] = f"{stage_prefix}{s}"
        _processing_status["progress"] = p

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

    _last_run_stats.update({"input_tokens": 0, "output_tokens": 0, "calls": 0,
                            "phase1_model": phase1_model, "meta_model": meta_model})
    logger.info("PHASE1: %s | META: %s | FILE: %s", phase1_model, meta_model, filename)

    # Phase 0: Token-Cache
    token_cache = load_token_cache(vault_path)
    cached_terms = [{"canonical": c, "aliases": aliases} for c, aliases in token_cache.items()]
    cached_canonical = set(token_cache.keys())
    logger.info("TOKEN CACHE: %d bekannte Begriffe", len(cached_terms))

    chunks_count = 0
    meta: dict = {}
    # {canonical, aliases, type, keep}
    claude_tokens: list[dict] = []

    # === AUTO MODE: Ollama → single Claude quality-pass call ===
    if phase1_model == "ollama" and meta_model == "claude":
        if not await ollama_available(ollama_model):
            raise HTTPException(status_code=503, detail="ollama_unavailable")
        p1_chunks = chunk_text(full_text, CHUNK_MAX_WORDS_OLLAMA)
        chunks_count = len(p1_chunks)
        _processing_status["chunk_total"] = chunks_count
        all_raw: list[str] = []
        for i, chunk in enumerate(p1_chunks):
            _stage(f"Chunk {i + 1}/{chunks_count} — Ollama...", 0.15 + 0.38 * (i / chunks_count))
            _processing_status["chunk_current"] = i + 1
            raw = await call_ollama(ollama_model, build_recognition_prompt_ollama(chunk))
            terms = parse_terms_simple(raw)
            all_raw.extend(t["canonical"] for t in terms)
            logger.info("CHUNK %d/%d [Ollama]: %d Begriffe", i + 1, chunks_count, len(terms))

        _stage("Claude Quality-Pass (1 Call)...", 0.58)
        unique_raw = list(dict.fromkeys(t for t in all_raw if t not in cached_canonical))
        try:
            combined_raw = call_claude(api_key, build_combined_prompt(unique_raw, full_text[:3000]),
                                       max_tokens=4096)
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
        for i, chunk in enumerate(p1_chunks):
            _stage(f"Chunk {i + 1}/{chunks_count} — Ollama...", 0.15 + 0.65 * (i / chunks_count))
            _processing_status["chunk_current"] = i + 1
            raw = await call_ollama(ollama_model, build_recognition_prompt_ollama(chunk))
            all_raw.extend(t["canonical"] for t in parse_terms_simple(raw))
        unique_raw = list(dict.fromkeys(t for t in all_raw if t not in cached_canonical))
        raw_list = [{"canonical": t, "aliases": [t]} for t in unique_raw]
        kept, filtered = filter_noisy_terms(raw_list)
        claude_tokens = (
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": True}
             for t in kept] +
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": False}
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
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": True}
             for t in kept] +
            [{"canonical": t["canonical"], "aliases": t["aliases"], "type": None, "keep": False}
             for t in filtered]
        )

    # Fallback: if metadata empty, try regex
    if not any(meta.get(k) for k in ("title", "author", "year")):
        meta = extract_metadata_regex(full_text)
    logger.info("METADATA: %s (via %s)", meta, meta_model)

    # Phase 3: Text structuring + wikilink application
    _stage("Wikilinks werden gesetzt...", 0.82)

    kept_for_preview = [
        {"canonical": t["canonical"], "aliases": t["aliases"]}
        for t in claude_tokens if t.get("keep", True)
    ]
    preview_terms = merge_terms([cached_terms, kept_for_preview], base_links, vault_links, full_text)

    abstract, main_body, references = structure_text_sections(full_text)
    sections_text = f"## Abstract\n\n{abstract}\n\n## Volltext\n\n{main_body}"
    if references:
        sections_text += f"\n\n## Literatur\n\n{references}"

    frontmatter = f"---\ntitle: {meta.get('title', '')}\nauthor: {meta.get('author', '')}\nyear: {meta.get('year', '')}\n"
    if meta.get("journal"):
        frontmatter += f"journal: {meta['journal']}\n"
    if meta.get("doi"):
        frontmatter += f"doi: {meta['doi']}\n"
    frontmatter += f"tags:\n  - literature-note\nsource_pdf: {filename}\nmneme_version: {MNEME_VERSION}\n---\n\n"

    preview_content = apply_wikilinks(frontmatter + sections_text, preview_terms)
    total_links = len(re.findall(r"\[\[.+?\]\]", preview_content))
    output_filename = derive_output_filename(meta, filename)

    _stage("Review wird vorbereitet...", 0.94)

    token_list = [
        {
            "canonical": t["canonical"],
            "is_new": t["canonical"] not in cached_canonical,
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
                    if t.get("keep", True) and t["canonical"] not in cached_canonical)
    filtered_count = sum(1 for t in claude_tokens if not t.get("keep", True))

    logger.info("REVIEW READY: %d kept (%d new), %d filtered | %d links | %s",
                len(kept_for_preview), truly_new, filtered_count, total_links, output_filename)

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
            {"canonical": t["canonical"], "aliases": t["aliases"], "type": t.get("type")}
            for t in claude_tokens
            if t["canonical"] not in cached_canonical
        ],
        "base_links": base_links,
        "vault_links": vault_links,
        "token_list": token_list,
        "duplicate_suggestions": dup_suggestions,
        "stats": {
            "links_total": total_links,
            "filtered": filtered_count,
            "new": truly_new,
            "existing": len(cached_terms),
            "model_used": f"{phase1_model}/{meta_model}",
            "chunks": chunks_count,
        },
        "cost": {
            "input_tokens": _last_run_stats["input_tokens"],
            "output_tokens": _last_run_stats["output_tokens"],
            "phase1_model": phase1_model,
        },
    }
