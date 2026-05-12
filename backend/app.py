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
CHUNK_OVERLAP_WORDS = 200


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
    chunks = []
    step = CHUNK_MAX_WORDS - CHUNK_OVERLAP_WORDS
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + CHUNK_MAX_WORDS])
        chunks.append(chunk)
        if i + CHUNK_MAX_WORDS >= len(words):
            break
    return chunks


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


def call_claude(api_key: str, prompt: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_prompt(chunks: list[str], vault_links: list[str], base_links: list[str], filename: str) -> str:
    text = "\n\n".join(chunks[:2])[:8000]

    all_links = sorted(set(vault_links) | set(base_links))
    link_list = ", ".join(f"[[{w}]]" for w in all_links[:400])

    return textwrap.dedent(f"""
        Du bist ein Assistent der wissenschaftliche Texte in strukturierte Obsidian-Notizen umwandelt.

        Erstelle eine strukturierte Obsidian-Notiz für das Dokument "{filename}".

        WIKILINK-REGELN (absolut verpflichtend):
        - Setze [[Wikilinks]] direkt im Fließtext bei JEDEM relevanten Begriff: Konzepte, Theorien, Personen, Methoden, Schulen, Institutionen
        - Ziel: mindestens 20 bis 50 Links verteilt über die gesamte Notiz — nicht am Ende gesammelt
        - Alias-Logik: Synonyme und fremdsprachige Varianten auf denselben Begriff mappen, z.B. "working memory" → [[Arbeitsgedächtnis]], "self-concept" → [[Selbstkonzept]]
        - Begriffe aus der Liste unten IMMER verlinken wenn sie im Text vorkommen
        - Neue, im Text vorkommende Fachbegriffe ebenfalls verlinken, auch wenn nicht in der Liste

        Bekannte Begriffe zum Verlinken (Vault + Basisliste):
        {link_list if link_list else "(noch keine — erkenne alle relevanten Begriffe selbst)"}

        Struktur (exakt so, Wikilinks überall im Fließtext):
        ---
        title: [Titel]
        author: [Autor(en)]
        year: [Jahr]
        tags:
          - literature-note
        ---

        # [Titel]

        ## Zusammenfassung
        [3-5 Sätze mit [[verlinkten]] Begriffen direkt im Text]

        ## Kernthesen
        - [These mit [[verlinkten]] Begriffen]
        - [These mit [[verlinkten]] Begriffen]
        - ...

        ## Wichtige Konzepte
        - **[[Konzept]]**: [Erklärung mit weiteren [[Links]]]
        - ...

        ## Methoden
        - **[[Methode]]**: [kurze Beschreibung] (nur wenn relevant, sonst Abschnitt weglassen)

        Dokumentinhalt:
        {text}

        Antworte NUR mit dem Markdown-Inhalt, ohne zusätzlichen Text davor oder danach.
    """).strip()


def build_linking_prompt(text: str, all_links: list[str]) -> str:
    link_list = ", ".join(f"[[{w}]]" for w in all_links[:400])
    return textwrap.dedent(f"""
        Ersetze im folgenden Markdown-Text jeden relevanten Begriff, Namen, Theorie oder jedes Konzept mit [[Begriff]].
        Behalte das YAML-Frontmatter und alle Markdown-Überschriften exakt bei.
        Gib NUR den modifizierten Text zurück, ohne Erklärungen.

        Bekannte Links (bevorzugt verwenden wenn passend):
        {link_list if link_list else "(keine — erkenne selbst)"}

        Text:
        {text}
    """).strip()


def derive_output_filename(raw_response: str, fallback: str) -> str:
    author_match = re.search(r"author:\s*(.+)", raw_response)
    year_match = re.search(r"year:\s*(\d{4})", raw_response)
    title_match = re.search(r"title:\s*(.+)", raw_response)

    author = author_match.group(1).strip().split(",")[0].strip() if author_match else ""
    year = year_match.group(1).strip() if year_match else ""
    title = title_match.group(1).strip()[:30] if title_match else fallback.replace(".pdf", "")

    parts = [p for p in [author, year, title] if p]
    raw_name = "-".join(parts) if parts else fallback.replace(".pdf", "")
    safe_name = re.sub(r'[<>:"/\\|?*]', "", raw_name).strip("-").strip()
    return f"{safe_name}.md"


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
    prompt = build_prompt(chunks, vault_links, base_links, file.filename or "document.pdf")

    requested = model if model != "auto" else cfg.get("default_model", "auto")
    ollama_model = cfg.get("ollama_model", "llama3.1:8b")
    api_key = get_anthropic_key(cfg)

    # Resolve effective model: Claude primary, Ollama fallback
    if requested == "auto":
        use_model = "claude" if api_key.strip() else "ollama"
    elif requested == "claude":
        if not api_key.strip():
            raise HTTPException(status_code=400, detail="claude_api_key_missing")
        use_model = "claude"
    else:
        use_model = "ollama"

    logger.info("MODEL: %s | FILE: %s", use_model, file.filename)
    logger.info("PROMPT (erste 500):\n%s", prompt[:500])

    async def run_stage(p: str) -> str:
        if use_model == "claude":
            try:
                return call_claude(api_key, p)
            except Exception as e:
                logger.warning("Claude fehlgeschlagen (%s), Fallback auf Ollama", e)
                if not await ollama_available(ollama_model):
                    raise HTTPException(status_code=503, detail="claude_error_and_ollama_unavailable")
                return await call_ollama(ollama_model, p)
        else:
            if not await ollama_available(ollama_model):
                raise HTTPException(status_code=503, detail="ollama_unavailable")
            return await call_ollama(ollama_model, p)

    stage1 = await run_stage(prompt)
    logger.info("STAGE 1 (erste 500):\n%s", stage1[:500])

    all_links = sorted(set(vault_links) | set(base_links))
    linking_prompt = build_linking_prompt(stage1, all_links)

    result = await run_stage(linking_prompt)

    link_count = len(re.findall(r"\[\[.+?\]\]", result))
    logger.info("STAGE 2 (erste 500):\n%s", result[:500])
    logger.info("WIKILINKS IM OUTPUT: %d Links", link_count)

    output_filename = derive_output_filename(result, file.filename or "document.pdf")
    output_path = Path(vault_path) / output_filename
    output_path.write_text(result, encoding="utf-8")

    return {
        "ok": True,
        "filename": output_filename,
        "model_used": use_model,
        "wikilinks_available": len(vault_links) + len(base_links),
        "chunks": len(chunks),
    }
