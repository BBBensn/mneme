---
date_created: 2026-05-16 00:44:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-16 00:44:00
---

# v3.0.2 — UI Cleanup, Duplikat-Batch, Cancel, Fortschritt (2026-05-16)

## UI Cleanup
- Home-Screen: Artikel/Buch-Toggle entfernt (Typ wird per File in der Queue eingestellt)
- Home-Screen: Modell-Toggle entfernt (nur Info-Text "Automatisch: Ollama..." bleibt)
- Modell wird ausschließlich im Queue-Screen pro Queue gesetzt

## Duplikat-Check (Batch)
- Neuer Endpoint POST /check/duplicates (Plural): prüft alle Files auf einmal, ein Vault-Scan
- _build_vault_source_map() — lädt source_pdf und title aus erstem 30 Zeilen jeder .md Datei
- Response: {results: {filename: {exists, existing_file, match_type}}}
- Frontend: checkQueueDuplicates() wird nach addToQueue() aufgerufen
- Queue-Zeilen zeigen ⚠ Duplikat Badge (orange, mit Tooltip auf existing_file)
- check_duplicate (singular) aktualisiert: gibt jetzt match_type zurück

## Cancel-Verbesserung
- _process_pdf_bytes bekommt cancel_job_id Parameter
- _check_cancel() Helfer: prüft _cancel_flags, wirft HTTPException(499) wenn gesetzt
- Cancel-Check nach jedem Batch (Ollama-Auto + Ollama-Only) und jedem Chunk (Claude-Only)
- _process_queue_job fängt "cancelled_by_user" ab → status = "cancelled"
- _process_queue_job: vor dem Start prüfen ob cancel_flag gesetzt

## Fortschrittsanzeige
- stage_callback Parameter in _process_pdf_bytes: aktualisiert _queue_jobs[job_id]["stage"]
- _stage() ruft stage_callback auf → Queue-Zeilen zeigen echten Phase-Text (Batch 2/8, Claude...)
- Elapsed-Zeit: t0 = time.time() am Start; elapsed = round(time.time()-t0) bei done
- GET /process/queue/status gibt elapsed mit zurück
- Frontend: "Fertig (0:47)" bei abgeschlossenen Jobs; Client-Timer bei laufenden Jobs
- Gesamtzeit: queueStartTime seit Queue-Launch → "X/N fertig · 1:23" oben im Progress-Screen
- MNEME_VERSION → 3.0.2
