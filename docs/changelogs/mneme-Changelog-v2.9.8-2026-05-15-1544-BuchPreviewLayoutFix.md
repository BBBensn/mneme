---
date_created: 2026-05-15 15:44:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 15:44:00
---

# v2.9.8 — Buch-Preview Layout, Spalten, Warnung-Fix (2026-05-15)

- Layout-Fix: Kapitel-Zeilen nutzen jetzt vollständiges Flex-Layout (Checkbox 20px, Von 52px, Bis 52px, Titel flex:3, Autoren flex:2, × 24px)
- Neues Feld "Bis" (page_end) pro Kapitel: Von/Bis-Inputs ersetzen das einzelne Seiten-Feld
- Backend: `parse_toc_regex()` setzt `page_end: None`; `process_book_preview()` befüllt page_end automatisch (nächstes Kapitel - 1, letztes → total_pages)
- Backend: `find_chapter_boundaries()` reicht page_end durch; letztes Kapitel nutzt page_end als PDF-Seitengrenze
- Autoren-Toggle-Button: Ein-/Ausblenden der Autoren-Spalte, Zustand wird in localStorage gespeichert; Default: sichtbar wenn irgendein Kapitel einen Autor hat
- Abschnitts-Zeilen (is_section): kein Checkbox/×, grauer Label mit Seitenzahl rechts
- Warnung-Fix: Klick auf "Buch"-Toggle blendet den Buch-Hinweis aus; Warnung verschwindet auch beim Droppen einer neuen Datei (war bereits implementiert via clearStatus)
- Frontend: bkpAutoFillPageEnds() befüllt fehlende page_end nach Reparse
