---
date_created: 2026-05-15 06:44:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 06:44:00
---

# v2.9.4 — Author Plain Text, Buch-Crash Fix, Buch-Warnung (2026-05-15)

## Author-Feld: Wikilinks entfernt (kritisch, Dataview-Fix)

- **Ursache:** `string(author)` in Dataview gibt `"[[Name]]"` zurück — Query sucht nach `"Name"` ohne Klammern → 0 Ergebnisse
- `format_author_yaml()`: `author: '[[Name]]'` → `author: Name` (plain text, kein Quote, keine Klammern)
- `authors`-Liste: `'[[Name]]'` → `Name`
- `POST /authors/fix-author-field`: entfernt Klammern auch aus bestehenden Literature-Notes (author-Feld und authors-Liste)

## Buch-Modus Crash Fix

- `find_chapter_boundaries()`: `ch.get("page_start", 1) - 3` → `int(ch.get("page_start") or 1) - 3`
- Absicherung gegen `page_start: null` aus Claude-Output (führte zu `TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'`)
- Gleicher Fix auch im Fallback-Pfad

## Buch-Modus Warnung im Artikel-Modus

- Nach PDF-Drop: wenn Datei > 3 MB und Artikel-Modus aktiv → Info-Meldung (kein Blocker)
- "Großes Dokument (~X MB). Buch-Modus könnte besser geeignet sein."
- Link "→ Zum Buch-Modus wechseln" schaltet den Typ-Toggle direkt um

- Version auf 2.9.4 gesetzt
