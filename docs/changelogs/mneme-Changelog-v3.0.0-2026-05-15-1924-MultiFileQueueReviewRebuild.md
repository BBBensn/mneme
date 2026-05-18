---
date_created: 2026-05-15 19:24:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 19:24:00
---

# v3.0.0 — Multi-File Queue + Review-Rebuild (2026-05-15)

## Neu

### Multi-File Drop Zone
- Drop-Zone akzeptiert mehrere PDFs gleichzeitig (multiple-Attribut auf file-input)
- Alle gedropten PDFs landen in der Queue → direkt zum Queue-Screen

### Queue-Screen (#page-queue)
- Dateiliste mit per-File Typ-Toggle (Artikel/Buch)
- Automatisch "Buch" wenn File > 3 MB (änderbar)
- Globaler Modell-Selektor (Auto/Ollama/Claude) für alle Queue-Jobs
- Warnung wenn Buch-Dateien in der Queue
- × zum Entfernen einzelner Dateien
- "Verarbeiten" → startet Artikel-Queue, Bücher werden übersprungen mit Toast
- Einzelnes Buch → direkt zum TOC-Screen

### Parallele Verarbeitung (Backend)
- Neuer Endpoint POST /process/queue — akzeptiert mehrere Files, startet asyncio.create_task pro File
- Neuer Endpoint GET /process/queue/status — pollt Job-Status (pending/processing/done/error)
- _queue_jobs globales Dict: {job_id → {status, filename, draft, error, stage}}
- Jeder Job läuft parallel; _process_queue_job() ruft _process_pdf_bytes() auf und speichert Draft

### Progress-Screen (#page-queue-progress)
- Zeigt alle Jobs mit Status-Dots (grau/orange/grün/rot) und Stage-Text
- Polling alle 2s auf /process/queue/status
- "Ergebnisse reviewen →" Button erscheint wenn alle Jobs fertig

### Review-Screen Rebuild
- Navigationsleiste oben wenn Queue > 1 Job (Prev/Next)
- Bereich 1: Term-Liste (einklappbar per Header-Klick)
- Bereich 2: Metadaten editierbar (Titel, Autor, Jahr)
- Bereich 3: MD-Vorschau (Accordion, default zugeklappt)
- "Token-Verwaltung" Link statt inline Dup-Karten
- "Nochmal mit Claude" nur im Legacy-Single-File-Flow sichtbar

### Neuer Backend-Confirm-Endpoint
- POST /process/queue/confirm — job_id + selected_terms + merged_terms + meta_override
- meta_override: überschreibt Titel/Autor/Jahr im Frontmatter vor dem Speichern
- Rebuild output_filename wenn Titel sich ändert

## Rückwärtskompatibilität
- Legacy single-file flow (/process → /process/confirm) bleibt erhalten
- Bulk-Mode bleibt unverändert
- Buch-Preview-Screen unverändert
- MNEME_VERSION → 3.0.0
