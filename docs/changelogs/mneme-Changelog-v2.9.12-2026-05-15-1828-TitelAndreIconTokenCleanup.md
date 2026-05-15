---
date_created: 2026-05-15 18:28:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 18:28:00
---

# v2.9.12 — Titel-Fix, André-Fix, Icon-Fix, Token-Cleanup, Doku (2026-05-15)

- derive_chapter_filename: kein Zeichenlimit mehr (war [:80], jetzt ohne Limit) — macOS erlaubt 255 Zeichen
- _is_author_line: Unicode-sichere Character Class — r'^[^\s\d<>:"/\\|?*;!?()\[\]]+$' statt ASCII-Liste; "André Weiß", "Žižek" etc. werden jetzt korrekt erkannt
- Nav-Icons: Positionsstabilität via .btn-icon.hidden (visibility:hidden + pointer-events:none) statt display:none/flex — Icons wandern nicht mehr beim Seitenwechsel
- Token-Verwaltung aufgeräumt: Buttons "Auf v2.4 migrieren", "Autoren-Stubs reparieren", "Autoren-Felder reparieren", "Dataview-Queries reparieren", "Stubs bereinigen" entfernt (alle obsolet). Nur noch "Vault neu verlinken" + "Vault Reset" sichtbar.
- docs/mneme.md: Roadmap auf v3.0.0/v3.0.1 aktualisiert, behobene Probleme entfernt
