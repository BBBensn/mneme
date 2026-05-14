---
date_created: 2026-05-14 19:27:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 19:27:00
---

# v2.9.3 — Titel-Fix, Dataview-Fix, Buch-Kapitel-Fix, Token-Accumulation (2026-05-14)

## Titel-Fix

- `derive_output_filename()`: Titel-Kürzung von `[:30]` auf `[:60]` erhöht — keine abgeschnittenen Dateinamen mehr
- `_process_pdf_bytes()`: `title`-Feld im Frontmatter jetzt mit `yaml_str()` gequotet → Doppelpunkte im Titel brechen kein YAML mehr
- `_process_book_inner()`: Übersichts-Frontmatter `title` und `author` ebenfalls mit `yaml_str()` gequotet
- Kapitel-Frontmatter: `title` mit `yaml_str()` gequotet

## Dataview-Fix

- `_dataview_block()`: `FROM "/"` entfernt — in Obsidian Dataview sucht `FROM "/"` nur den Root-Ordner, nicht den gesamten Vault
- Neue Query ohne FROM: `TABLE year, journal\nWHERE contains(string(author), "Name") OR contains(string(authors), "Name")`
- `POST /authors/fix-dataview-query`: entfernt jetzt auch `FROM "/"` aus bestehenden Stubs (zusätzlich zu v2.9.0/v2.8-Query-Migrationen)

## Buch-Kapitel-Erkennung

- TOC-Extraktion: erste 25 Seiten statt 15 — tiefere Inhaltsverzeichnisse werden erkannt
- `find_chapter_boundaries()`: robusteres progressives Matching (100% → 66% → 33% des Titels), beginnt ab `page_hint` (Claude's page_start − 3) statt Seite 0 → schneller und genauer
- Mindest-Textlänge pro Kapitel: 80 → 30 Zeichen (kurze Einleitungsseiten nicht mehr übersprungen)

## Token-Accumulation im Buch-Modus

- `_process_pdf_bytes()`: neuer Parameter `extra_cached_terms: dict | None` — wird zu Beginn in den Token-Cache gemerged
- `_process_book_inner()`: `accumulated_terms` Dict wächst nach jedem Kapitel um neue Begriffe; folgende Kapitel erhalten sie als `extra_cached_terms`
- Ab Kapitel 2 werden bereits bekannte Begriffe direkt via Python verlinkt, ohne Ollama-Erkennung

## Buch-Modus Feedback

- `processed_chapters` enthält jetzt `links` und `new_terms` pro Kapitel
- Frontend zeigt nach Buch-Verarbeitung eine detaillierte Liste aller Kapitel mit Link- und Begriff-Zähler

- Version auf 2.9.3 gesetzt
