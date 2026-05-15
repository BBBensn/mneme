---
date_created: 2026-05-15 23:55:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-15 23:55:00
---

# v3.0.1 — Queue-Fixes, Buch-Review, Freie Navigation (2026-05-15)

## Queue

- Neue Files droppen wenn Queue-Screen bereits offen → werden angehängt statt ersetzt
- Drag & Drop Sortierung auf Queue-Zeilen (native HTML5, kein externes Library)
- Fortschrittsanzeige: stage-Text pro Job, Zeitmessung "läuft seit X:XX" für laufende Jobs, "X/N fertig" Summary
- Cancel-Button (×) pro Job im Progress-Screen → POST /process/queue/cancel
- Backend: _cancel_flags Set; pending-Jobs sofort abbrechen, processing-Jobs nach aktuellem Chunk

## Buch-Review (neuer Flow)

- _execute_book_chapters() schreibt keine Dateien mehr direkt
- Stattdessen: pro Kapitel ein Draft in _queue_jobs gespeichert; Frontmatter mit Book-Link
- process_book_run() gibt book_review_ready zurück mit chapter_summaries und book_id
- _pending_book_drafts speichert Book-Metadaten bis finalize aufgerufen wird
- POST /process/book/finalize schreibt 00-Uebersicht.md, räumt _pending_book_drafts auf
- Frontend: btn-bkp-run erkennt book_review_ready → baut activeJobs aus chapters, bookReviewBookId setzen
- Fortschrittsanzeige während Buchverarbeitung (startPolling)
- Nach Speichern aller Kapitel: /process/book/finalize automatisch aufrufen
- confirm_queue_job: output_path.parent.mkdir() — Bücher/Subfolder werden automatisch angelegt

## Review: Freie Navigation

- reviewDrafts Dict: Änderungen an Tokens + Meta werden gespeichert beim Navigieren
- saveCurrentReviewState() / loadReviewState() — Zustand pro Job persistiert
- Prev/Next Navigation ohne Speicherzwang — wechseln jederzeit möglich
- savedJobIds Set verfolgt gespeicherte Jobs; nav-label zeigt ✓

## Weitere Fixes

- Home-Icon Bug: .hidden wird nicht mehr auf Home-Seite gesetzt; btn-home ohne initial hidden
- showPage(): btnHome.classList.toggle('hidden', onReview || onBkp) — sichtbar auf Home
- Wikilink-Highlighting in MD-Vorschau: [[Link]] → <span style="color:var(--accent)">Link</span>
- beforeunload Warning wenn Queue oder ungespeicherte Review-Jobs vorhanden
- Kommentar in start_queue_processing: Parallel tasks — Ollama serializes internally
- MNEME_VERSION → 3.0.1
