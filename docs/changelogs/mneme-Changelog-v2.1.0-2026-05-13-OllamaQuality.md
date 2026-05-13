---
date_created: 2026-05-13
type: changelog
tags:
  - project
  - changelog
---

# v2.1.0 — Ollama-Qualität + Progress-Anzeige (2026-05-13)

- Ollama-Begriffsliste bereinigt: Blacklist für Impressumsbegriffe (ISSN, DOI, Verlag, Druck…), Abbildungsreferenzen (Abb., Fig., Tab.) und Begriffe unter 4 Zeichen
- Dateiname-Extraktion bei Ollama-only gefixt: `extract_metadata_regex()` erkennt jetzt Autorname via Regex (Vorname Nachname-Muster), wählt längste nicht-namensartige Zeile als Titel, sucht Jahr im Bereich 2000–2030
- Claude Phase 1 aggressiver: Prompt fordert explizit ≥30 Begriffe, benennt 'Wahrnehmung', 'Reflexion' etc. als Fachbegriffe, max_tokens von 1024 auf 2048 erhöht
- Progress-Anzeige: Polling auf GET /process/status alle 1,5s — zeigt animierten Statustext ("Chunk 2/6 wird analysiert…") + Fortschrittsbalken der bei >19% auf echten Prozentwert umschaltet
- Auto-Modus ist Default (war er bereits, jetzt explizit dokumentiert)
- Version auf 2.1.0 gesetzt
