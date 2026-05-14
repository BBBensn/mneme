---
date_created: 2026-05-12 21:35:03
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 21:35:03
---

# v1.3.1 — Dotenv Fix (2026-05-12)

- get_anthropic_key(): load_dotenv() mit override=True direkt in der Funktion — Key wird bei jedem Aufruf frisch aus .env gelesen, nicht nur beim Server-Start
- /config/has_api_key: prüft jetzt via get_anthropic_key() statt cfg direkt — UI zeigt korrekt an ob Key vorhanden
