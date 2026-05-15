---
date_created: 2026-05-15 10:04:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 10:04:00
---

# v2.9.6 — Dateiname-Fix, Duplikat-Warnung via source_pdf (2026-05-15)

## derive_output_filename Fix (kritisch)

- Leerzeichen im Dateinamen BEHALTEN — macOS und Obsidian unterstützen sie problemlos
- v2.9.5 hatte Leerzeichen zu Bindestrichen umgewandelt → erzeugte doppelte Files zu älteren Notes
- Resultat: `"Ogwudile Chinenye Linda-2025-Stufflebeam's CIPP Model of Evaluation.md"` (Leerzeichen erhalten)
- `author[:40]`, `title[:80]`, `author.split(",")[0]` entfernt, None-Schutz via `or ""`

## Duplikat-Warnung via source_pdf

- `DuplicateCheckRequest`: Feld umbenannt von `filename` → `pdf_filename`
- `POST /check/duplicate`: prüft jetzt `source_pdf`-Feld in bestehenden Notes (erste 30 Zeilen, case-insensitive) statt Dateinamen-Heuristik
- Durchsucht Vault-Root `.md` + `Bücher/` (nicht rekursiv in Personen/Konzepte/Methoden/)
- Frontend: sendet `pdf_filename` statt `filename`; zeigt Warnung wenn `exists=true`; kein `similar`-Hinweis mehr
- Check läuft im Hintergrund, ist kein Blocker für den Verarbeiten-Button

- Version auf 2.9.6 gesetzt
