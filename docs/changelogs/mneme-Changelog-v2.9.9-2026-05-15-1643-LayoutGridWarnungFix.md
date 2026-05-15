---
date_created: 2026-05-15 16:43:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 16:43:00
---

# v2.9.9 — Buch-Preview Layout Grid, Warnung-Logik Fix (2026-05-15)

- Layout Final Fix: Kapitel-Liste nutzt jetzt CSS Grid statt Flexbox
  - grid-template-columns: 20px 56px 56px 1fr 0.6fr 24px (Checkbox|Von|Bis|Titel|Autoren|×)
  - CSS-Variable --bkp-cols auf #bkp-chapter-list, dynamisch per bkpSetAuthorVisible() geändert
  - Autoren-Spalte collapsed korrekt (0.6fr fällt weg wenn ausgeblendet)
  - Abschnitts-Zeilen: grid-column: 1/-1 für volle Breite, Titel links / Seite rechts
- Warnung-Logik reaktiv: updateBookWarning() ersetzt einmaligen setStatus()-Aufruf
  - Warnung erscheint/verschwindet korrekt beim Umschalten Artikel↔Buch (auch zurück zu Artikel)
  - setFile() und type-toggle rufen beide updateBookWarning() auf
  - Link "→ Zum Buch-Modus wechseln" ruft ebenfalls updateBookWarning() auf (statt clearStatus)
- MNEME_VERSION auf "2.9.9" aktualisiert
