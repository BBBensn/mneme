---
date_created: 2026-05-13 17:00:19
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-13 17:00:19
---

# v2.3.0 — Optimierte Arbeitsteilung + Bulk-Verarbeitung (2026-05-13)

## Neuer Auto-Modus Workflow (Phase 0–4)
- Phase 0 (Python): PDF extrahieren, Token-Cache laden, chunken
- Phase 1 (Ollama): Rohe Begriffsliste per Chunk (günstig, lokal)
- Phase 2 (Claude, 1 Call): Bereinigung + Normalisierung + Klassifizierung + Metadaten in einem einzigen API-Call — statt vorher N Calls pro Chunk. Erwartete Kosten: ~0.05–0.1¢/Paper
- Phase 3 (Python): JSON parsen, Textstruktur (## Abstract / ## Volltext / ## Literatur), Wikilinks setzen, Stubs erstellen mit Typ-Info
- Phase 4: Review-Screen wie v2.2.0

## Neuer kombinierter Claude-Prompt
- Nimmt Ollama-Rohterm-Liste + Text-Kontext
- Gibt JSON zurück: `{metadata: {title, author, year, journal, doi}, tokens: [{term, type, aliases, keep}]}`
- Claude klassifiziert: person / concept / method / null
- Claude setzt keep:false für Noise (ersetzt Python-only Noise-Filter für Auto-Modus)
- Fallback auf Python-Noise-Filter wenn Claude-Call fehlschlägt

## Text-Strukturierung
- Neue Funktion `structure_text_sections()`: erkennt Abstract, Haupttext, Literaturverzeichnis per Regex
- Output-MD hat jetzt ## Abstract / ## Volltext / ## Literatur Sektionen

## Typ-aware Stubs
- Stubs werden in korrekten Ordner geschrieben basierend auf Claude-Klassifikation (person→Personen, method→Methoden, concept→Konzepte)
- Stub-Tag wird entsprechend gesetzt (person/method/concept statt immer "concept")

## Frontmatter-Erweiterung
- journal und doi werden in Frontmatter geschrieben wenn Claude sie extrahiert

## Bulk-Verarbeitung
- Neuer Endpoint GET /vault/raw_pdfs: listet PDFs aus {vault}/RAW-Data/
- Neuer Endpoint POST /process/bulk: verarbeitet PDFs sequenziell, sammelt alle neuen Tokens
- Neuer Endpoint POST /process/bulk_confirm: speichert alle PDFs mit ausgewählten Begriffen
- Bulk-Review nutzt bestehenden Review-Screen: alle Tokens aus allen PDFs de-dupliziert, mit Source-Label (welches PDF)
- Frontend: neuer Bulk-Button in Nav, #page-bulk mit PDF-Liste + Checkboxen

## Review-UI Updates
- Typ-Badges: [Person] [Konzept] [Methode] in Grün/Blau/Orange
- Source-Label bei Bulk-Review zeigt welches PDF den Begriff gefunden hat
- claude_noise als neuer Filtergrund (wenn Claude keep:false setzt)

## Refactoring
- `_process_pdf_inner` → thin wrapper um neues `_process_pdf_bytes(bytes, filename, model, stage_prefix)`
- `_process_pdf_bytes` shared zwischen single-file und bulk processing
- `create_stubs()` akzeptiert optionales `term_types` dict für Typ-aware Stub-Erstellung
- confirm_process verwendet `sections_text` statt `full_text` für strukturierten Output

- Version auf 2.3.0 gesetzt
