---
date_created: 2026-05-15 17:37:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 17:37:00
---

# v2.9.11 — Titel-Fix, Autoren-Fix, Tooltip, Vault-Relinking (2026-05-15)

- derive_chapter_filename: Titel nicht mehr auf 40 Zeichen gekürzt ([:40] → [:80])
- Autoren-Normalisierung in Buchkapiteln: chapter_author wird jetzt via parse_author_list() normalisiert ("Hedder und Ziegler" → "Hedder, Ziegler") — an beiden Stellen (_run_dry und _execute_book_chapters)
- Hover-Tooltip für Titel-Input: title="${ch.title}" als HTML-Attribut; langer Titel ist im Browser-Tooltip lesbar
- Vault-Relinking: neuer POST /vault/relink Endpoint startet Background-Task; GET /vault/relink/status für Fortschritt
  - Iteriert alle .md im Vault-Root + Bücher/ (nicht: Personen/Konzepte/Methoden/)
  - apply_wikilinks() auf bestehende Files — fügt neue Links hinzu, lässt bestehende unberührt
  - Response: {files_checked, files_updated, elapsed_s}
- Frontend: "Vault neu verlinken" Button im Token-Tab; Fortschrittsanzeige "87/122 Dateien…" während Lauf; Toast nach Fertigstellung
- import asyncio (bereits v2.9.10), BackgroundTasks zu FastAPI-Import ergänzt
