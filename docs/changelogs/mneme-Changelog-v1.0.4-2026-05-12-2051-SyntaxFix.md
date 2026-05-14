---
date_created: 2026-05-12 20:51:47
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 20:51:47
---

# v1.0.4 — SyntaxFix (2026-05-12)

- SyntaxError behoben: else-Branch des use_model-Blocks war durch die print-Statements aus v1.0.3 aus dem if/elif/else-Verbund herausgerutscht
- Korrekte Reihenfolge: PROMPT-Log vor if-Block, RAW RESPONSE + WIKILINKS SECTION nach dem if/elif/else-Block
- uvicorn startet wieder sauber, /process Endpoint funktional verifiziert
