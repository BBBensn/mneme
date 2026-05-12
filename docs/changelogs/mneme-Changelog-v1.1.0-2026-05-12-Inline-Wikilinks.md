---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.1.0 — Vollständiges Inline-Wikilink-Tagging (2026-05-12)

- Prompt komplett neu: Ziel ist nicht mehr Zusammenfassung, sondern strukturierte Notiz mit Wikilinks direkt im Fließtext bei jedem relevanten Begriff
- Mindest-Linkzahl: 20-50+ Links pro Dokument, verteilt über alle Abschnitte
- Alias-Logik explizit im Prompt: Synonyme und fremdsprachige Varianten auf denselben Link mappen
- Neues ## Methoden-Abschnitt (optional, wird nur gesetzt wenn relevant)
- Separater ## Wikilinks-Abschnitt am Ende entfernt — Links gehören in den Text
- Neue Datei backend/psych_base_links.json: 60 kuratierte Grundbegriffe der Psychologie die immer verlinkt werden
- load_psych_base_links() lädt die Basisliste beim /process-Aufruf
- build_prompt() erhält jetzt vault_links + base_links als getrennte Parameter, kombiniert beide
- Debug-Log zeigt jetzt Gesamtzahl der [[Links]] im Output statt Wikilinks-Abschnitt
