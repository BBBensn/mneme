---
date_created: 2026-05-05 16:49:24
date_modified: 2026-05-05 19:38:31
---
# mneme — CLAUDE.md

Projekt-spezifischer Kontext. Ergänzt `~/.claude/CLAUDE.md`.
Ablageort: `~/Documents/Coding/J-Vault/mneme/CLAUDE.md`

---

## Projekt-Basics

- **Name:** mneme
- **Version:** v1.0.0
- **Status:** active
- **Stack:** Vanilla JS + FastAPI + pymupdf + ollama + anthropic SDK
- **Läuft lokal auf:** MacBook (kein Server-Deploy)

---

## Lokale Struktur

~/Documents/Coding/J-Vault/mneme/
├── frontend/
│   └── index.html
├── backend/
│   └── app.py
├── config.json              ← vault_path, default_model, claude_api_key
├── docs/
│   └── changelogs/
├── CLAUDE.md
└── .gitignore

---

## Services & Ports

| Dienst  | Port | Start              |
|---------|------|--------------------|
| Backend | 5050 | uvicorn app:app    |

---

## Git

- **Repo:** https://github.com/BBBensn/mneme
- **Remote:** git remote add origin git@github.com:BBBensn/mneme.git

---

## Kein Deploy

Dieses Projekt läuft ausschließlich lokal. Kein SCP, kein systemctl, kein nginx.
Am Ende der Session: nur Changelog schreiben + Git commit auf Anweisung.

---

## Projekt-spezifische Konventionen

- Vault-Pfad kommt aus config.json, nie hardcoded
- Wikilinks immer im Format [[Begriff]] (doppelte eckige Klammern)
- Chunks: max 2000 Wörter, Overlap 200 Wörter
- Modell-Auswahl: "ollama" | "claude" | "auto" (auto = ollama wenn verfügbar, sonst claude)
- Output-Dateiname: [Autor]-[Jahr]-[Kurztitel].md (aus Metadaten extrahiert)

---

## Roadmap

| Version | Feature                                      | Status  |
|---------|----------------------------------------------|---------|
| v1.0.0  | MVP: PDF → MD → Vault (Ollama + Claude)      | aktiv   |
| v1.1.0  | Preview/Review + Quality Score + Rerun       | geplant |
| v1.2.0  | Batch-Verarbeitung mehrerer PDFs             | geplant |
| v1.3.0  | Vault-Suche direkt im Tool                   | geplant |

---

## Obsidian-Doku

- Projekt-MD: 03_Projects/Coding PC/mneme/mneme.md
- Changelogs: 03_Projects/Coding PC/mneme/Changelogs/
- Changelog-All: 03_Projects/Coding PC/mneme/mneme-Changelog-All.md