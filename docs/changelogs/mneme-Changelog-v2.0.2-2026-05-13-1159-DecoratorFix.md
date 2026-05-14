---
date_created: 2026-05-13 11:59:22
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-13 11:59:22
---

# v2.0.2 — Bugfix: @app.post("/process") auf falsche Funktion (2026-05-13)

- Kritischer Fix: @app.post("/process") Decorator lag auf resolve_models() statt auf process_pdf()
- FastAPI registrierte resolve_models(requested, api_key, ollama_model) als /process-Endpoint
  → alle drei Parameter required → "Field required · Field required · Field required"
- Fix: Decorator eine Funktion nach unten verschoben auf process_pdf()
- Ursache: der Decorator wurde beim Einfügen von resolve_models() in v2.0.0 nicht mit der Funktion mitbewegt
