---
date_created: 2026-05-12 22:27:25
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-12 22:27:25
---

# v1.6.0 — Zweiphasen-Ansatz: KI erkennt, Python ersetzt (2026-05-12)

- Kernarchitektur geändert: KI liefert nur noch eine JSON-Begriffsliste (kurzer Output), Python macht die eigentliche Textersetzung (0 weitere API-Calls)
- Phase 1a: Metadata-Extraktion (title/author/year) wie bisher
- Phase 1b: build_recognition_prompt() — pro Chunk eine Liste {"canonical", "aliases"} als JSON
- parse_terms(): parst JSON-Array aus KI-Antwort mit Fallback
- merge_terms(): dedupliziert Begriffe über alle Chunks, merged psych_base_links + vault_links
- Phase 2: apply_wikilinks() — Python-Regex ersetzt alle Aliases im Originaltext
- _tag_line(): single-pass Regex mit longest-match-first, schützt bestehende [[...]] automatisch
- Alias-Logik: canonical form → [[Begriff]], abweichende Form → [[Begriff|Alias]]
- YAML-Frontmatter und Überschriften (#) werden nicht getaggt
- Output: vollständiger Originaltext + Frontmatter + Wikilinks inline
- max_tokens für KI-Calls von 8192 auf 1024 reduziert (nur noch JSON-Listen, kein Volltext)
