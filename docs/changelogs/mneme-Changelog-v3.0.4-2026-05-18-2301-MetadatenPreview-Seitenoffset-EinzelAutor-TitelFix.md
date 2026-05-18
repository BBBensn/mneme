---
date_created: 2026-05-18 23:01:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-18 23:01:00
---

# v3.0.4 — Metadaten-Preview, Seitenoffset, Einzel-Autor, Titel-Fix (2026-05-18)

- **Metadaten-Preview in Queue**: Beim Drop werden Metadaten automatisch via `/extract/metadata` extrahiert (Claude-Call, nur erste Seiten). Jede Artikel-Zeile in der Queue hat ein ✎-Icon — Klick öffnet Inline-Formular mit Titel, Autor, Jahr, DOI. Geänderte Werte werden im Review-Screen vorausgefüllt und beim Confirm als meta_override übergeben.
- **Buch-Modus: Seitenoffset**: Neues Feld im Book-Preview-Screen: „Seite 1 beginnt auf PDF-Seite [N]". Standard: 1. Bei Büchern mit römischen Vorziffern (z.B. 20 Seiten Vorwort) entsprechend anpassen. `find_chapter_boundaries` und `_pdf_page_from_printed` nutzen den Offset.
- **Buch-Modus: Einzel-Autor**: Toggle Monographie / Sammelband im Book-Preview-Screen (auto-erkannt, aber änderbar). Bei Monographie: globales Autor-Feld, Autoren-Spalte in Kapitelliste ausgeblendet, alle Kapitel bekommen den globalen Autor. Bei Sammelband: bisheriges Verhalten.
- **Titel-Fix im Dateinamen**: Limit in `derive_output_filename` entfernt — Titel wird nicht mehr nach 80 Zeichen abgeschnitten. Autor-Limit auf 60 Zeichen erhöht. Alle internen `[:80]`-Limits bei Titelstrings entfernt. macOS erlaubt 255 Zeichen im Dateinamen.
