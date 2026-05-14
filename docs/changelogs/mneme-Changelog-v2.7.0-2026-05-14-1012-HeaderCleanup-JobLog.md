---
date_created: 2026-05-14 10:12:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 10:12:00
---

# v2.7.0 — Header-Cleanup + YAML Fix + Job-Logging + Reset + Zeitmessung (2026-05-14)

## Volltext Header-Cleanup
- `_COMBINED_SYSTEM_PROMPT` erweitert: neues Feld `body_start_marker` — Claude gibt die ersten ~20 Wörter des echten Fließtexts zurück (nicht Titel/Abstract/Keywords/Instituts-Block)
- `clean_header_text(text, marker)`: schneidet alles vor `body_start_marker` ab; Fallback: Regex-Blacklist entfernt typische Header-Zeilen (ISSN, DOI:, Volume N, Impact Factor, Published by, URLs, Seitenzahlen, Department of, University of)
- `## Volltext` enthält jetzt den bereinigten Fließtext statt des rohen gesamten Texts

## YAML source_pdf Fix
- `source_pdf` Wert wird jetzt mit `yaml_str()` (single quotes) gewrappt → funktioniert korrekt bei Apostrophen im Dateinamen (z.B. `STUFFLEBEAM'S CIPP MODEL.pdf`)
- Fix gilt für Literature-Notes, Buchkapitel und Übersichts-Files

## Job-Logging
- Neues `mneme_jobs.jsonl` im Backend-Ordner — jeder bestätigte Verarbeitungsjob wird geloggt
- Felder: timestamp, filename, source_pdf, model, links, new_tokens, elapsed_s, cost_eur, status
- `log_job()` wird aus `confirm_process` aufgerufen
- Neuer Endpoint `GET /jobs` — gibt letzte 50 Jobs zurück (umgekehrt chronologisch)
- Neuer Jobs-Tab im Frontend (Uhr-Icon): zeigt Verlauf aller verarbeiteten Notizen mit Modell, Links, Kosten, Zeit

## Vault Reset Button
- Neuer Endpoint `POST /vault/reset`: löscht Personen/, Methoden/, Konzepte/ Ordner + tokens.json; Literature Notes bleiben erhalten
- Button in Token-Verwaltung mit Confirm-Dialog

## Zeitmessung Fix
- Format: `0:47` (mm:ss) statt `47.3s` im Review-Screen

## Sonstiges
- `draft["cost"]` enthält jetzt auch `cache_read_tokens` und `cache_creation_tokens` für korrekte Kostenberechnung im Job-Log
- `_process_start = datetime.datetime.now()` am Anfang von `_process_pdf_bytes` → `process_elapsed_s` im Draft gespeichert
- `import shutil` hinzugefügt

- Version auf 2.7.0 gesetzt
