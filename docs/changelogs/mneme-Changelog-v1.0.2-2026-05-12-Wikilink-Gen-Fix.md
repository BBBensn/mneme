---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.0.2 — Wikilink-Generierung Fix (2026-05-12)

- build_prompt(): Text auf erste 2 Chunks und max. 8000 Zeichen begrenzt — verhindert Kontextverlust bei llama3.1:8b
- Wikilink-Instruktion vereinfacht: kurze, direkte WICHTIG-Anweisung mit explizitem Minimum von 8 Links
- Vault leer: Modell erhält klaren Auftrag, Konzepte selbst zu erkennen
- Vault befüllt: Modell kombiniert passende Vault-Links mit neu erkannten Konzepten
- call_claude(): Modell von nicht-existentem "claude-opus-4-7" auf "claude-haiku-4-5" korrigiert
