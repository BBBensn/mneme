---
date_created: 2026-05-15 17:09:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 17:09:00
---

# v2.9.10 — TOC Fix, Wrapper, Dry-Run, Doku (2026-05-15)

- Wrapper breiter: Book-Preview-Seite nutzt max-width: 900px via main.wide CSS-Klasse (showPage togglet sie)
- TOC-Fix mehrzeilige Titel: parse_toc_regex() preprocesst Zeilen — Titelfortsetzung ohne Seitenzahl direkt vor Zeile mit Seitenzahl wird zusammengeführt
- × Button entfernt aus Kapitel-Liste; Checkbox-Deaktivierung reicht; Grid-Template auf 5 Spalten (20px 56px 56px 1fr 0.6fr) ohne Del-Spalte
- Dry-Run-Endpoint POST /process/book/run_dry: identischer Request wie /run, erstellt Stub-.md mit Frontmatter + leerem Body, asyncio.sleep(0.5) pro Kapitel für Fortschrittstest; asyncio import ergänzt
- Frontend: Testlauf-Button neben Verarbeiten; nur sichtbar bei localStorage.getItem('mneme_debug') === 'true'; zeigt DRY-RUN-Badge in Fortschrittsanzeige
- docs/mneme.md: Meilensteine bis v2.9.10 als done, Offene Probleme aktualisiert, neue Endpoints dokumentiert, alte behobene Bugs entfernt
