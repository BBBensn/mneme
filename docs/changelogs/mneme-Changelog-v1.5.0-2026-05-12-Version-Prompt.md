---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.5.0 — Versionierung + Prompt-Präzisierung (2026-05-12)

- Neuer Endpoint GET /version → {"version": "1.5.0"}
- MNEME_VERSION Konstante in app.py, zentrale Versionsverwaltung
- Frontmatter enthält jetzt mneme_version Feld
- UI: Versionsnummer wird beim Start von /version geladen und oben links neben Ollama-Status angezeigt
- Annotation-Prompt auf exakt spezifizierten Wortlaut umgestellt: "KEINEN Satz, KEIN Wort, KEINE Reihenfolge" — kein textwrap.dedent mehr, direkte String-Konkatenation für exakte Kontrolle
