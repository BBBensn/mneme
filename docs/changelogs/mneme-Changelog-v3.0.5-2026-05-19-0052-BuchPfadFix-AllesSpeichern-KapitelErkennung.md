---
date_created: 2026-05-19 00:52:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-19 00:52:00
---

# v3.0.5 — Buch-Pfad-Fix, Alles-Speichern, Kapitel-Erkennung (2026-05-19)

- **Kritischer Bug-Fix: Kapitel-Files im Vault-Root**: In `confirm_queue_job` wurde `draft["output_filename"]` überschrieben durch `derive_output_filename()` wenn `meta_override.title` gesetzt war — das liefert nur einen einfachen Dateinamen, kein Unterordner-Pfad. Fix: `output_filename` wird nur neu berechnet wenn kein `/` im Pfad steht (Artikel), bei Buch-Kapiteln (`Bücher/folder/kapitel.md`) bleibt der Pfad erhalten.
- **Alle speichern Button**: Im Review-Screen neuer Button "Alle speichern" — erscheint wenn mehr als ein ungespeicherter fertiger Job vorhanden ist. Iteriert über alle unsaved Jobs, schickt für jeden `/process/queue/confirm` mit aktiv selektierten Begriffen und gespeichertem/vorausgefülltem meta_override. Warnung wenn unreviewed Jobs dabei. Schließt mit Book-Finalize ab falls Buch.
- **Kapitel-Erkennung: Volltext-Suche**: `find_chapter_boundaries` nutzt jetzt primär `page.search_for()` (pymupdf) statt regex auf `get_text()`. Das erkennt Kapitelanfänge die mitten auf einer Seite beginnen. Suche mit ersten 6 Wörtern des Titels in einem ±5/+10-Seiten-Fenster um die erwartete Seite. Regex-Fallback bleibt für hyphenierte/gesplittete Titel.
