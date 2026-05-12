---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.0.0 — MVP (2026-05-12)

- FastAPI Backend auf Port 5050 mit CORS-Middleware
- PDF-Upload via Drag & Drop oder Datei-Auswahl im Browser
- Text-Extraktion via pymupdf, Chunking (max 2000 Wörter, 200 Overlap)
- Wikilinks aus bestehendem Obsidian Vault einlesen (alle [[...]] aus .md-Dateien)
- Modellauswahl: Auto (Ollama → Claude Fallback), Ollama, Claude API
- Ollama-Integration via HTTP API, konfigurierbares Modell (default: llama3.1:8b)
- Claude API Fallback via anthropic SDK (claude-opus-4-7)
- Prompt generiert strukturierte Obsidian-Notiz mit Zusammenfassung, Kernthesen, Konzepten, Wikilinks
- Output-Dateiname aus Metadaten: [Autor]-[Jahr]-[Kurztitel].md
- Output direkt in konfigurierten Vault-Pfad geschrieben
- Settings-Screen: Vault-Pfad, Standard-Modell, Ollama-Modell, Claude API Key
- Config persistiert in config.json (außerhalb von Git)
- Ollama-Status in Echtzeit in der Nav-Leiste
- Fehlermeldungen für: Ollama offline, kein Vault-Pfad, kein API Key, gescannte PDFs
- Design: Apple-Designsprache, SF Pro, Whitespace, clean
