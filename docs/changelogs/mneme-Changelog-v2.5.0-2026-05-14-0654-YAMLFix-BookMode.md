---
date_created: 2026-05-14 06:54:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 06:54:00
---

# v2.5.0 — YAML Fix + Autoren Dataview + Sections-Erkennung + Buch-Modus (2026-05-14)

## YAML Fix — Autoren-Stubs (kritisch)
- `works`-Feld aus YAML entfernt (war in Obsidian kaputt)
- Autoren-Stub hat jetzt einen Dataview-Block im Body: `TABLE year, journal ... WHERE contains(author, "Name")` — listet Literature-Notes automatisch als Werkliste
- Stub wird nur einmal erstellt; Dataview hält die Liste aktuell
- `cleanup_existing_stubs` überspringt Author-Stubs (- author Tag)

## Literature-Note YAML bereinigt
- Neue Felder: `author` (String) + `authors` (YAML-Liste bei mehreren Autoren)
- `affiliation` nicht mehr im YAML der Literature-Note
- `parse_author_list()`: parst "Müller & Schulz" → ["Müller", "Schulz"]
- Felder: title, author, authors[], year, journal, doi, citation_apa, citation_chicago, tags, source_pdf, mneme_version

## Sections-Erkennung (costenneutral im kombinierten Claude-Call)
- Combined Prompt erweitert um Aufgabe 8: SECTIONS
- Claude gibt zurück: has_abstract (bool), abstract_text (String/null), has_bibliography (bool), bibliography_start (String/null)
- Python nutzt das: has_abstract=false → kein ## Abstract; abstract_text → direkter Text statt Heuristik
- has_bibliography=false → kein ## Literatur; bibliography_start → findet Abschnitt per Regex
- Niemals Sections erfinden — nur einbauen wenn Claude sie bestätigt

## Buch-Modus (neues Feature)
- Neuer Toggle "Artikel / Buch" im Frontend
- Neuer Endpoint POST /process/book
- Phase 0: Claude erkennt Kapitelstruktur aus ersten 15 Seiten (TOC)
- Phase 1: Python findet Seitengrenzen per Titelsuche im PDF (`find_chapter_boundaries`)
- Phase 2: Jedes Kapitel durchläuft normalen Auto-Workflow via `_process_pdf_bytes` mit `full_text_override`
- Ausgabe: Bücher/[Autor-Jahr-Titel]/01-Kapitel.md, 02-Kapitel.md, ...
- Jede Kapitel-Datei: frontmatter (chapter, book-link), Zurück-Link im Body
- Phase 3: 00-Uebersicht.md mit Dataview LIST der Kapitel
- Kein Review-Screen für Bücher → direktes Speichern, Fortschrittsanzeige "Kapitel 3/12"
- Fallback: wenn keine Kapitel erkannt → normaler Artikel-Workflow

## Refactoring
- `_process_pdf_bytes` akzeptiert optional `full_text_override: str` (für Buchkapitel)
- `parse_author_list()` neue Hilfsfunktion
- `build_chapter_prompt()`, `parse_chapter_structure()`, `find_chapter_boundaries()`, `derive_chapter_filename()` neue Hilfsfunktionen

- Version auf 2.5.0 gesetzt
