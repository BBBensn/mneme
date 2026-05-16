---
date_created: 2026-05-16 17:39:19
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-16 17:39:19
---

# v3.0.3 — Cancel-Fix, Buch-Fortschritt, Metadaten (2026-05-16)

- Cancel-Fix: Wenn alle Queue-Jobs cancelled/error (kein done) → automatisch zurück zu Home, Poll-Timer wird gestoppt
- Buch-Fortschrittsanzeige: Nach Klick "N Beiträge verarbeiten" sofort auf eigene Processing-Seite wechseln mit Stage-Text, Fortschrittsbalken und Laufzeit-Counter
- Inputs nach Buch-Start locken: Alle Inputs + Checkboxen in Kapitelliste disabled, Opacity 0.5, ← Zurück disabled
- Buch-Titel editierbar: Im Book-Preview-Header als Input-Feld statt statischem Text; wird beim POST mitgesendet und im Backend als Ordnername verwendet
- Metadaten-Fix A: Steuerzeichen (\x00–\x1f, \x7f) werden aus chapter_title bereinigt
- Metadaten-Fix B: chapter_title wird als meta_override an _process_pdf_bytes übergeben — Claude-Extraktion überschreibt TOC-Titel nicht mehr
- Metadaten-Fix C: author-Feld in meta_override nur wenn chapter_author non-empty
- BookRunRequest: Neues optionales Feld book_title für Frontend-Eingabe
- Duplikat-Check bei Multi-Drop: bereits in v3.0.2 implementiert, verifiziert vorhanden
