---
date_created: 2026-05-15 12:19:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 12:19:00
---

# v2.9.7 — Buch-Modus mehrstufig: TOC-Preview + Sammelband-Erkennung (2026-05-15)

## Neue Architektur: Drei-Phasen-Flow

Der Buch-Modus wird jetzt dreistufig:
1. **Preview:** PDF hochladen → TOC parsen → Kapitel-Liste prüfen/editieren
2. **Review:** User bestätigt/editiert Kapitel, Autoren, Seitenzahlen
3. **Verarbeitung:** nur ausgewählte Beiträge werden verarbeitet

## Backend: Neue Funktionen

- `_is_author_line(s)`: Heuristik — erkennt Autorenzeilen im TOC (Großbuchstabe, kein Seitenende, Trennzeichen)
- `detect_book_type(toc_text, front_pages_text) → "sammelband" | "monographie"`: Score-basiert (Hrsg., Autorenzeilen, edited by)
- `parse_toc_regex(toc_text) → list[dict]`: Regex-Parser für TOC-Einträge (Titel + Seitenzahl + optionale Autorenzeile danach); erkennt `is_section` (Teil I/II, ALL-CAPS-Kurztitel)

## Backend: Neue Endpoints

- `POST /process/book/preview`: liest PDF, erkennt TOC via Regex (Fallback: Claude), gibt `{pdf_id, book_type, title, total_pages, chapters}` zurück; speichert PDF-Bytes in `_pending_book_pdf[pdf_id]`
- `POST /process/book/reparse`: re-parst TOC mit alternativem Seitenbereich oder manuellem Text
- `POST /process/book/run`: verarbeitet ausgewählte Kapitel aus gespeichertem PDF; filtert `enabled=True, is_section=False`

## Backend: Refactoring

- `_write_book_overview(book_dir, book_meta, folder_name, pdf_filename)`: Übersichts-Datei als separate Funktion
- `_execute_book_chapters(doc, chapters, book_meta, ...)`: Kapitel-Verarbeitungsloop als separate async-Funktion (shared zwischen Legacy + neuem Run-Endpoint)
- `_process_book_inner()`: schlank, nutzt jetzt `_execute_book_chapters` + `_write_book_overview`
- `_process_pdf_bytes()`: neuer `meta_override: dict | None = None` Parameter — ermöglicht Autoren-Override aus TOC (Sammelband-Beiträge)
- Legacy `POST /process/book`: unverändert (kein Preview-Schritt)

## Frontend: Neue Seite #page-book-preview

- Erscheint nach "Verarbeiten" im Buch-Modus (statt sofortiger Verarbeitung)
- Zeigt Book-Type-Badge (Sammelband / Monographie), Seitenzahl
- Editierbare Kapitel-Liste: Checkbox, Titel-Input, Autor-Input, Seite-Input, Löschen-Button
- Abschnitte (is_section=true) erscheinen grau/kursiv, ohne Checkbox
- [+ Beitrag hinzufügen] für manuelle Einträge
- Accordion "TOC manuell anpassen": Seitenbereich neu einlesen ODER TOC-Text einfügen + parsen
- [← Zurück] + [N Beiträge verarbeiten →] Aktionsleiste

- Version auf 2.9.7 gesetzt
