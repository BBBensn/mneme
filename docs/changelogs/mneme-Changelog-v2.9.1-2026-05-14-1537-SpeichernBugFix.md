---
date_created: 2026-05-14 15:37:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 15:37:00
---

# v2.9.1 — Bugfix: Speichern-Button ausgegraut nach Speichern (2026-05-14)

## Speichern-Bug

- **Ursache:** In der `r.ok`-Success-Branch des `btn-confirm-review` Click-Handlers wurde `btn.disabled` nie zurückgesetzt. Der DOM-Button blieb dauerhaft `disabled=true` mit Text "Speichert…". Beim nächsten `/process` lädt derselbe DOM-Button in den Review-Screen — und ist von Beginn an ausgegraut.
- **Fix:** `btn.disabled = false; btn.textContent = 'Speichern';` am Anfang des `r.ok`-Blocks eingefügt (vor Navigation zu Home).

- Version auf 2.9.1 gesetzt
