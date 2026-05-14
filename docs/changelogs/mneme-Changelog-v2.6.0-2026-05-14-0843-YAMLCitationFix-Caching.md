---
date_created: 2026-05-14 08:43:00
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-14 08:43:00
---

# v2.6.0 — YAML Citation Fix + Volltext + Prompt-Caching + Zeitmessung (2026-05-14)

## YAML Citation Fix
- `citation_apa` und `citation_chicago` wurden in YAML mit doppelten Anführungszeichen geschrieben → brach bei Zitaten mit inneren Anführungszeichen
- Neue `yaml_str()` Funktion: wraps Strings in YAML single quotes, escaped innere Apostrophe als `''`
- Combined Prompt ergänzt: "citation_apa und citation_chicago OHNE äußere Anführungszeichen zurückgeben"

## Volltext-Erkennung verbessert
- Zweispaltige Layouts: `extract_page_text_smart()` nutzt `page.get_text("blocks")`, trennt linke (x < mid) und rechte (x ≥ mid) Spalte, liest links- dann rechts-spaltig korrekt durch
- Plausibilitätsprüfung: nur als zweispaltig erkannt wenn beide Spalten mind. 2 Blöcke haben und y-Overlap ≥ 25% der Seitenhöhe
- Fallback auf `page.get_text()` wenn kein echtes Zwei-Spalten-Layout erkannt
- `## Volltext` enthält jetzt immer den vollständigen Text ab Seite 1 (nicht mehr `main_body` nach dem Abstract-Abschnitt)

## Prompt-Caching (Anthropic SDK)
- `call_claude_with_cache()`: Neue Funktion mit `system=[{..., "cache_control": {"type": "ephemeral"}}]`
- `_COMBINED_SYSTEM_PROMPT`: Konstante mit den Task-Instruktionen — wird als System-Prompt mit Cache-Control gesendet
- `build_combined_user_blocks()`: Ersetzt `build_combined_prompt()` — gibt User-Content-Blöcke zurück (Termliste als gecachter Block, Kontext-Text als variabler Block)
- Neue Preiskonstanten: `HAIKU_PRICE_CACHE_WRITE_PER_TOKEN` ($1.00/MTok), `HAIKU_PRICE_CACHE_READ_PER_TOKEN` ($0.08/MTok)
- `_last_run_stats` erweitert: `cache_read_tokens`, `cache_creation_tokens`
- `/last_run_cost` gibt neu zurück: `cache_read_tokens`, `cache_creation_tokens`, `saved_eur`
- Erwartete Ersparnis: ~90% der System-Prompt-Tokens gecacht bei wiederholten Calls

## Zeitmessung Frontend
- `processStartTime = performance.now()` beim Klick auf "Verarbeiten"
- Review-Screen zeigt "Verarbeitungszeit: 47.3s" unter den Kosteninformationen
- Timer wird beim Verlassen des Review-Screens zurückgesetzt
- Cache-Einsparung sichtbar: "Cache: 0.42¢ gespart" in Kostenanzeige

- Version auf 2.6.0 gesetzt
