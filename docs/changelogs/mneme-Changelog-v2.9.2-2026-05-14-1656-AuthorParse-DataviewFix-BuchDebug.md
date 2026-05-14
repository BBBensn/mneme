---
date_created: 2026-05-14 16:56:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 16:56:00
---

# v2.9.2 — Author-Parse Fix, Dataview Fix, Buch-Modus Debug (2026-05-14)

## parse_author_list — Komma-Separator

- `parse_author_list()` splittet jetzt auch auf Kommas: "Ngala, Fongod, Orock" wird korrekt als 3 Autoren erkannt
- Heuristik für Einzelautor im APA-Format: genau 1 Komma → nicht splitten ("Nachname, Vorname" bleibt als eine Person)
- Mehrere Kommas → immer auf alle Kommas splitten

## Dataview Query Fix

- `_dataview_block()` zurück auf `contains(string(author), "Name") OR contains(string(authors), "Name")` — funktioniert zuverlässig für YAML-Strings und Listen
- v2.9.0 hatte `author = [[Name]]` eingeführt — matcht in Dataview nur bei echten Link-Feldern, nicht bei YAML-Strings
- Neuer Endpoint `POST /authors/fix-dataview-query`: repariert bestehende Personen/-Stubs
  - Ersetzt v2.9.0-Format (`WHERE author = [[Name]] OR contains(authors, [[Name]])`) durch korrektes Format
  - Ersetzt v2.8-Format (`contains(authors, "Name")` ohne `string()`) durch korrektes Format
- Neuer Button "Dataview-Queries reparieren" in Token-Verwaltung
- `fix_author_stubs()` wieder vereinfacht — keine Query-Migration mehr darin (das macht jetzt fix-dataview-query)

## Buch-Modus Logging

- `exc_info=True` zu allen Kapitel-bezogenen `logger.warning()` Aufrufen hinzugefügt — Traceback wird jetzt vollständig ins Log geschrieben
- `BUCH FERTIG` Log-Zeile gibt jetzt auch `[(chapter, error)]` aus für schnelle Fehlerdiagnose

- Version auf 2.9.2 gesetzt
