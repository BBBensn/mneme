---
date_created: 2026-05-12 21:12:44
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 21:12:44
---

# v1.2.0 — Zweistufiges Linking + File-Logging + Auto-Reload (2026-05-12)

- Zweistufiger Verarbeitungsprozess: Stufe 1 generiert die Notiz-Struktur, Stufe 2 bekommt NUR den fertigen Text + Linkliste und setzt alle [[Wikilinks]] — kleinere, fokussierte Prompts schlagen einen langen komplexen Call für llama3.1:8b
- Neuer build_linking_prompt(): minimaler Prompt für Stufe 2, ausschließlich auf Linking spezialisiert
- Logging von print() auf Python logging.RotatingFileHandler umgestellt → backend/mneme.log (max 1MB, 3 Backups)
- Log enthält: Prompt Stufe 1, Response Stufe 1, Response Stufe 2, Anzahl Links im Output
- uvicorn Start-Befehl auf --reload aktualisiert: Änderungen an app.py werden sofort ohne Neustart aktiv
