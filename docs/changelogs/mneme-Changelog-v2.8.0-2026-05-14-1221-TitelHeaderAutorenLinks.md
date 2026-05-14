---
date_created: 2026-05-14 12:21:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 12:21:00
---

# v2.8.0 — Bugfix: Titel, Header, Autoren-Links + Docs-Update (2026-05-14)

## Titel-Erkennung (PDF-Metadaten zuerst)
- Neue Prioritätsreihenfolge: 1) pymupdf `doc.metadata["title"]` → 2) Claude → 3) Dateiname
- `_extract_pdf_title(doc)`: validiert PDF-Metadaten-Titel (>10 Zeichen, hat Buchstaben, kein generischer Name wie "Microsoft Word", ALL CAPS → Title Case)
- `_COMBINED_SYSTEM_PROMPT` verschärft: "NIEMALS ein Satzteil der mit einem Verb beginnt" als explizites Beispiel
- `pdf_meta_title = ""` initialisiert, nur gesetzt wenn PDF-Bytes gelesen werden (nicht bei `full_text_override`)

## Header-Cleanup (robuster, zweistufig)
- Neue Funktion `_is_noisy_header_line(line)`: erkennt ISSN, DOI:10., Vol./Issue/pp., www./http, Seitenzahlen (nur Ziffern), Page N / | P a g e, E-Mail/@-Adressen, Impact Factor, Published by, Copyright ©, ALL-CAPS-Zeilen <60 Zeichen
- `clean_header_text()` jetzt zweistufig: Schritt 1: body_start_marker (wie v2.7), Schritt 2: erste 30 Zeilen auf `_is_noisy_header_line` prüfen und entfernen, bis erste Zeile >40 Zeichen kommt

## Autoren als Wikilinks in Literature-Notes
- Neue Funktion `get_author_stub_name(author)`: kanonischer Dateiname für Stub (filesystem-safe, trailing periods entfernt)
- Neue Funktion `format_author_yaml(author_str, authors_list)`: schreibt `author: '[[Name]]'` + `authors: ['[[Name1]]', '[[Name2]]']` mit YAML-korrekten single quotes
- Frontmatter der Literature-Note hat jetzt Wikilinks für alle Autoren
- Neue Hilfsfunktion `_dataview_block(name)`: gemeinsamer Dataview-Block für alle Stub-Erstellungspfade

## Autoren-Stubs vervollständigen
- `update_author_stub()` neu: prüft ob `## Werke` bereits im Stub vorhanden; falls nicht: hängt Dataview-Block an bestehenden Stub an
- Autoren-Stubs werden jetzt für ALLE Autoren (parse_author_list) erstellt, nicht nur den ersten
- Aufruf in `confirm_process` jetzt VOR dem Schreiben der Literature-Note (Spec-konform)
- Neuer Endpoint `POST /authors/fix-stubs`: repariert alle bestehenden Autoren-Stubs ohne Dataview-Block
- Neuer Button "Autoren-Stubs reparieren" in Token-Verwaltung

## Speichern-Bug (Debugging-Vorbereitung)
- `console.log` beim Klick auf Speichern: `currentDraft` + `btn.disabled` Status
- TODO-Kommentar im Code dokumentiert den Bug für spätere Diagnose

## Docs-Update
- `docs/mneme.md`: Meilensteine bis v2.8 als ✅ done markiert; Bekannte Probleme bereinigt (Titelextraktion + Header behoben, Autoren-Links als gelöst markiert); Stack-Beschreibung aktualisiert
- `CLAUDE.md`: Version auf v2.8.0, v2.8 als ✅ done, v2.9 als nächste geplante Version

- Version auf 2.8.0 gesetzt
