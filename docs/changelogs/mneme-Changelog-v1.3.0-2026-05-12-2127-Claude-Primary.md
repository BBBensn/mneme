---
date_created: 2026-05-12 21:27:31
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 21:27:31
---

# v1.3.0 — Claude API als primäres Modell (2026-05-12)

- Claude claude-haiku-4-5-20251001 ist jetzt primäres Modell für beide Stufen (Extraktion + Linking)
- Ollama bleibt automatischer Fallback wenn API Key fehlt oder Claude-Call fehlschlägt
- ANTHROPIC_API_KEY wird aus .env geladen (python-dotenv), Fallback auf config.json
- Neue Hilfsfunktion get_anthropic_key(): prüft erst env, dann config
- Neue interne run_stage()-Funktion kapselt Modellauswahl + Fallback-Logik für beide Stufen
- .env Datei angelegt (in .gitignore), plaintext "Claude API"-Datei entfernt
- backend/mneme.log und "Claude API" in .gitignore eingetragen
- requirements.txt: python-dotenv>=1.0 hinzugefügt
