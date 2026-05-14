---
date_created: 2026-05-14 13:50:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 13:50:00
---

# v2.9.0 — Dataview-Fix, Alias-Konflikt, Kosten-Optimierung (2026-05-14)

## Dataview-Fix (Autoren-Link-Format)

- `_dataview_block()` WHERE-Klausel geändert: `contains(string(author), "Name")` → `author = [[Name]] OR contains(authors, [[Name]])`
- Damit matcht Dataview korrekt gegen Wikilinks statt String-Literals
- `POST /authors/fix-stubs`: repariert jetzt auch alte Query-Formate in bestehenden Autoren-Stubs (v2.8 → v2.9 Migration)
- Neuer Endpoint `POST /authors/fix-author-field`: geht durch alle Literature-Notes, ersetzt `author: "[[...]]"` (double quotes) durch `author: '[[...]]'` (single quotes)
- Neuer Button "Autoren-Felder reparieren" in Token-Verwaltung

## Alias-Konflikt (Stufflebeam-Bug)

- Neue Funktion `check_alias_conflict(new_canonical, existing_tokens)`: prüft ob ein neuer kanonischer Name bereits als Alias/Form eines bestehenden Tokens bekannt ist
- `save_token_cache()`: nutzt `check_alias_conflict` — wenn neuer Term Alias eines bestehenden ist, wird er in diesen gemergt statt als neuer Eintrag gespeichert
- `_process_pdf_bytes()`: baut `cached_alias_map` (lowercase form → canonical) aus token_cache — Terms die bereits als Form eines bestehenden Tokens bekannt sind, werden nicht als "new" markiert
- `is_new`, `truly_new`, `new_terms` berücksichtigen jetzt `cached_alias_map` (nicht nur `cached_canonical`)

## Kosten-Optimierung

- **Ollama-Batching**: Statt 1 Call pro Chunk (800 Wörter) → bis zu 3 Chunks pro Ollama-Call gebündelt (`OLLAMA_BATCH_SIZE = 3`). Ollama-Calls von N auf ceil(N/3) reduziert.
- Gilt für Auto-Modus (Ollama→Claude) und Ollama-only-Modus
- Phase 2 Claude: bereits 1 Call — bestätigt, kein Handlungsbedarf
- Quality Pass: bereits 1 Call — bestätigt, kein Handlungsbedarf
- **Cost-Cap-Warnung**: Im Claude-Modus bei Dateien > 300 KB → Confirm-Dialog vor Start: "~X MB, geschätzte Kosten ~Y¢. Auto-Modus wäre ~0.1¢. Fortfahren?"
- **Logging**: `[mneme] Claude calls this run: total=N | input=X tokens | cache_read=Y tokens` am Ende jeder Verarbeitung

- Version auf 2.9.0 gesetzt
