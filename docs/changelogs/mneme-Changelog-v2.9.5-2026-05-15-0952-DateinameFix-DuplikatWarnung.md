---
date_created: 2026-05-15 09:52:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 09:52:00
---

# v2.9.5 — Dateiname-Fix, Duplikat-Warnung (2026-05-15)

## derive_output_filename Fix

- `author`: `split(",")[0]` entfernt (war Artefakt aus APA-Format-Annahme; plain text seit v2.9.4); `[:30]` → `[:40]`
- `title`: `[:60]` → `[:80]`
- Null-Sicherheit: `meta.get("author") or ""` statt `meta.get("author", "")` (schützt gegen explizites `None`)
- Leerzeichen in Teilen werden zu Bindestrichen: `re.sub(r'\s+', '-', safe_name)` statt `"-".join(parts)`
- Ergebnis-Beispiel: `"Philipp Niemann"`, 2023, `"Evaluationsmethoden der Wissenschaftskommunikation"` → `Philipp-Niemann-2023-Evaluationsmethoden-der-Wissenschaftskommunikation.md`

## Duplikat-Warnung

- Neues Pydantic-Modell `DuplicateCheckRequest`
- Neuer Endpoint `POST /check/duplicate`: prüft ob Output-Dateiname oder Buch-Ordner bereits im Vault existiert; liefert auch ähnliche Dateinamen (erste 10 Zeichen des Stems als Heuristik)
- Frontend: nach File-Drop asynchroner Duplikat-Check; bei Treffer → gelbe Info-Meldung mit existierendem Dateinamen; bei ähnlichen → schwacher grauer Hinweis
- Buch-Modus-Hinweis (>3 MB) hat Vorrang, kein zusätzlicher Duplikat-Check bei großen Dateien

- Version auf 2.9.5 gesetzt
