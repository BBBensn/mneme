---
date_created: 2026-05-13
type: changelog
tags:
  - project
  - changelog
---

# v2.0.1 — Bugfix: NameError chunks + robuste Fehleranzeige (2026-05-13)

- Kritischer Fix: return statement referenzierte `len(chunks)` aber Variable wurde in v2.0.0 auf `p1_chunks` umbenannt → NameError → 500 → "[object Object]" im Frontend
- Zusätzlicher Guard: wenn phase1_model=="claude" aber api_key leer → saubere HTTPException statt AuthenticationError
- Metadata-Call: try/except mit Regex-Fallback wenn Claude-Call fehlschlägt
- Frontend: `data.detail` Array (FastAPI 422 Validierungsfehler) wird jetzt lesbar dargestellt statt "[object Object],[object Object]"
