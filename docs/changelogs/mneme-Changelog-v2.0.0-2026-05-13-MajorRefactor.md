---
date_created: 2026-05-13
type: changelog
tags:
  - project
  - changelog
---

# v2.0.0 — Merge-Fix + Granulareres Tagging + Ollama rehabilitiert (2026-05-13)

## 1. Stub-Merge Bugfix (kritisch)
- rename_wikilinks_in_vault(): ersetzt alle [[A]] → [[B|A]] und [[A|display]] → [[B|display]] in allen Vault-Dateien
- count_backlinks(): zählt Backlinks nach Merge
- merge_token_terms Endpoint: führt jetzt Vault-wide Link-Rename durch, löscht Stub, zählt Backlinks
- Response enthält files_updated + backlinks
- Frontend Toast zeigt: "X Files aktualisiert · Y Backlinks"

## 2. Granulareres Tagging
- build_recognition_prompt(): explizit auch Nachnamen allein, scheinbar allgemeine Fachbegriffe, Institutionen, Werktitel, Komposita
- "Im Zweifel: taggen. Lieber zu viele als zu wenige Links."

## 3. Ollama rehabilitiert
- resolve_models(): bestimmt phase1_model (ollama/claude) + meta_model (claude/regex) aus requested + Verfügbarkeit
- Ollama für Phase 1: CHUNK_MAX_WORDS_OLLAMA = 800 (kleinere Chunks), build_recognition_prompt_ollama() (simpler Text-Prompt ohne JSON)
- parse_terms_simple(): parst kommagetrennte oder zeilenweise Ollama-Ausgabe robust
- extract_metadata_regex(): regex-basierter Metadaten-Fallback wenn kein Claude Key
- Auto-Modus: Ollama für Phase 1 wenn verfügbar, Claude für Metadata wenn Key vorhanden, sonst regex
- process_pdf: völlig neu strukturiert mit getrennten Pfaden pro Modell
- chunk_text(): max_words Parameter (default CHUNK_MAX_WORDS)
- _last_run_stats + last_run_cost Endpoint: phase1_model + meta_model enthalten
- Frontend Kostenanzeige: "~0.00¢ (Ollama) + X¢ (Claude Meta)" wenn Ollama für Phase 1
