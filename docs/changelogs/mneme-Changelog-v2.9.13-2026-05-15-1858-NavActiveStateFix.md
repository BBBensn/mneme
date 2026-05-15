---
date_created: 2026-05-15 18:58:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 18:58:00
---

# v2.9.13 — Nav-Icon Active State Fix (2026-05-15)

- showPage(): Nav-Icons bleiben immer sichtbar (kein .hidden auf aktiver Seite mehr)
- Aktives Icon erhält .active → color: var(--accent) (Blau-Highlight)
- .hidden wird nur noch für review/book-preview (alle Icons) und home (Home-Icon) gesetzt
- CSS: .btn-icon.active { color: var(--accent); } ergänzt
- MNEME_VERSION → 2.9.13
