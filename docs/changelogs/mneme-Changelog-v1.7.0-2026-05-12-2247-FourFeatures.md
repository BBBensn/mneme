---
date_created: 2026-05-12 22:47:01
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 22:47:01
---

# v1.7.0 — Vier Verbesserungen (2026-05-12)

## 1. Flexionen / Alias
- expand_german_inflections(): generiert Standard-Flexionen pro Begriff (-s, -es, -e, -en, -er, -ern) als Python-Fallback
- KI-Prompt explizit erweitert: fordert alle Flexionsformen (Genitiv, Plural, Kasus) in aliases an, mit Beispiel
- merge_terms(): ruft expand_german_inflections() für jeden Begriff auf und merged mit KI-Formen

## 2. Kostenübersicht
- _last_run_stats global: zählt input_tokens, output_tokens, calls über alle Claude-Calls eines Runs
- call_claude(): akkumuliert Token-Usage aus message.usage
- Neuer Endpoint GET /last_run_cost: gibt tokens + Kosten in USD/EUR zurück
- Preise: $0.00025/1K input, $0.00125/1K output (claude-haiku-4-5-20251001)
- Frontend: zeigt nach Verarbeitung "Kosten: ~X¢ (Yin / Zout · N Calls)"
- Stats werden am Anfang jedes /process Calls zurückgesetzt

## 3. tokens.json persistent
- load_token_cache() / save_token_cache(): liest/schreibt Vault-Root/tokens.json
- Phase 0 in process_pdf: lädt Cache (bekannte Begriffe aus früheren Runs, keine KI nötig)
- Cache wird in merge_terms() als erste term_list mitgegeben
- Nach jedem Run: tokens.json mit allen neuen Begriffen + Flexionen erweitert
- tokens.json in /vault/tree unsichtbar (gefiltert)

## 4. Vault File Tree
- Neuer Endpoint GET /vault/tree: verschachtelte .md-Dateistruktur, max 3 Ebenen, sortiert
- Frontend: aufklappbare Tree-Karte unterhalb des Process-Buttons
- Ordner togglen per Klick, Datei-Klick zeigt Pfad im Toast
- Wird beim Start + nach jeder Verarbeitung aktualisiert
