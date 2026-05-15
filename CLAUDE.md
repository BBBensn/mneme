---
date_created: 2026-05-05 16:49:24
date_modified: 2026-05-05 19:38:31
---
# mneme — CLAUDE.md

Projekt-spezifischer Kontext für Claude Code. Ergänzt `~/.claude/CLAUDE.md`.
Ablageort: `~/Documents/Coding/J-Vault/mneme/CLAUDE.md`

---

## Projekt-Basics

- **Name:** mneme
- **Version:** v3.0.1
- **Status:** active
- **Stack:** Vanilla JS + FastAPI + pymupdf + Ollama + Anthropic SDK
- **Läuft lokal auf:** MacBook (kein Server-Deploy)
- **Port:** 5050

---

## Lokale Struktur

```
~/Documents/Coding/J-Vault/mneme/
├── frontend/
│   └── index.html
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── psych_base_links.json
│   └── mneme.log
├── docs/
│   └── changelogs/
├── .env                     ← ANTHROPIC_API_KEY (nicht ins Repo!)
├── config.json              ← vault_path, default_model
├── CLAUDE.md
└── .gitignore
```

---

## Services & Ports

| Dienst  | Port | Start                                    |
|---------|------|------------------------------------------|
| Backend | 5050 | `uvicorn app:app --port 5050 --reload`   |
| Ollama  | auto | läuft als separater Prozess              |

Port belegt? `lsof -ti:5050 | xargs kill -9`

---

## Git

- **Repo:** https://github.com/BBBensn/mneme
- **Branch:** master
- **Remote:** `git remote add origin git@github.com:BBBensn/mneme.git`

Am Ende jeder Session: Changelog schreiben + `git add . && git commit -m "vX.X.X Titel" && git push`

---

## Kein Deploy

Ausschließlich lokal. Kein SCP, kein systemctl, kein nginx.

---

## Architektur & Workflow

### Auto-Modus (Default)
1. **Phase 0 — Python:** PDF extrahieren via pymupdf, tokens.json laden, bekannte Begriffe vormerken
2. **Phase 1 — Ollama:** Neue Begriffe erkennen (lokal, kostenlos, ~650 Begriffe pro Paper)
3. **Phase 2 — Claude:** Einen einzigen API-Call: Begriffsliste bereinigen + normalisieren + Metadaten extrahieren
4. **Phase 3 — Python:** Volltext mit allen Begriffen verlinken, Stubs erstellen, tokens.json updaten
5. **Review-Screen:** User bestätigt Begriffe, dann erst speichern (`POST /process/confirm`)

### Modell-Auswahl
- `"auto"` = Ollama (Phase 1) + Claude (Phase 2 Meta), default
- `"ollama"` = Ollama für alles, Regex für Metadaten
- `"claude"` = Claude für alles

---

## Projekt-spezifische Konventionen

- **Vault-Pfad:** kommt aus `config.json`, nie hardcoded
- **API Key:** kommt aus `.env` (ANTHROPIC_API_KEY), mit `load_dotenv(override=True)` in jeder Funktion die ihn braucht
- **Wikilinks:** immer `[[Begriff]]` oder `[[Begriff|Alias]]` (Obsidian-Syntax)
- **Chunking:** max 2000 Wörter, Overlap 200 Wörter
- **Output-Dateiname:** `[Autor]-[Jahr]-[Kurztitel].md` (aus Metadaten extrahiert, Fallback: PDF-Dateiname)
- **Modell für Meta:** `claude-haiku-4-5-20251001`

## Vault-Struktur (wird von mneme angelegt)

```
Vault/
├── Personen/        ← Autoren-Stubs (YAML only, Dataview für Werkliste)
├── Konzepte/        ← Konzept-Stubs
├── Methoden/        ← Methoden-Stubs
├── Bücher/          ← Buch-Verzeichnisse (je ein Ordner pro Buch)
│   └── [Autor-Jahr-Titel]/
│       ├── 00-Uebersicht.md
│       └── [N]-[Kapitel].md
├── RAW-Data/        ← Original PDFs
├── [Autor-Jahr-Titel].md   ← Literature Notes (Artikel)
└── tokens.json      ← persistente Begriff-Datenbank
```

### tokens.json Format (v2.5)
```json
{
  "Max Imdahl": {
    "type": "person",
    "aliases": ["Imdahl", "Max Imdahls"],
    "translations": {"de": "Max Imdahl", "en": "Max Imdahl"},
    "forms": ["Max Imdahl", "Imdahl", "Max Imdahls"]
  }
}
```

### Literature Note YAML
```yaml
title: The CIPP Model for Evaluation
author: Daniel L. Stufflebeam
authors:
  - Daniel L. Stufflebeam
year: 2000
journal: Evaluation Models
doi: ...
citation_apa: "..."
citation_chicago: "..."
tags:
  - literature-note
source_pdf: 16.PDF
mneme_version: 2.5.0
```

### Autoren-Stub (Personen/)
```yaml
title: Daniel L. Stufflebeam
tags:
  - person
type: person
created: 2026-05-14
```
Body enthält Dataview-Block — keine works-Liste im YAML.

---

## Changelog-Konvention

**Dateiname:** `mneme-Changelog-vX.X.X-YYYY-MM-DD-HHMM-Kurztitel.md`
Beispiel: `mneme-Changelog-v2.5.0-2026-05-14-1430-BuchModus.md`

**YAML:**
```yaml
date_created: 2026-05-14 14:30:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 14:45:00
```

---

## Roadmap

| Version | Feature                                              | Status      |
|---------|------------------------------------------------------|-------------|
| v1.0–1.9 | MVP, Volltext-Annotation, Stubs, Token-Persistenz  | ✅ done     |
| v2.0–2.1 | Ollama rehabilitiert, Auto-Modus, Noise-Filter      | ✅ done     |
| v2.2    | Review-Interface vor dem Speichern                   | ✅ done     |
| v2.3    | Optimierte Arbeitsteilung (Phase 0–3)                | ✅ done     |
| v2.4    | Multilingual Tokens, Titelextraktion, Autoren-DB     | ✅ done     |
| v2.5    | YAML Fix, Dataview Autoren, Sections-Erkennung, Buch-Modus | ✅ done |
| v2.6    | YAML Citation Fix, 2-Spalten-Extraktion, Prompt-Caching, Timer | ✅ done |
| v2.7    | Header-Cleanup, Job-Log, Vault Reset, mm:ss Timer    | ✅ done     |
| v2.8    | Bugfixes: Titel, Header, Autoren-Links, fix-stubs    | ✅ done     |
| v2.9    | Dataview-Fix, Alias-Konflikt, Kosten-Optimierung     | ✅ done     |
| v2.9.1–7 | Speichern-Bug, Author, Dataview, Buch-Fixes, TOC-Preview | ✅ done |
| v2.9.8  | Buch-Preview Layout, Von/Bis-Spalten, Autoren-Toggle, Warnung-Fix | ✅ done |
| v2.9.9  | Layout Grid Final, Warnung-Logik reaktiv, Version 2.9.9 | ✅ done  |
| v2.9.10 | TOC Fix, Wrapper 900px, Dry-Run, mneme.md Update     | ✅ done     |
| v2.9.11 | Titel-Fix, Autoren-Fix, Tooltip, Vault-Relinking     | ✅ done     |
| v2.9.12 | Titel kein Limit, André-Fix, Icon-Fix, Token-Cleanup | ✅ done     |
| v2.9.13 | Nav-Icon Active State Fix                            | ✅ done     |
| v3.0.0  | Multi-File Queue, Review-Rebuild                     | ✅ done     |
| v3.0.1  | Queue-Fixes, Buch-Review, freie Navigation           | ✅ done     |
| v3.1.0  | Token-Verwaltung Bubble+Tree UI                      | geplant     |
| v3.2.0  | Graph-UI, Literatursuche via Claude                  | geplant     |

---

## Obsidian-Doku

- **Projekt-MD:** `mneme.md` (im Vault)
- **Changelogs:** `mneme/docs/changelogs/`