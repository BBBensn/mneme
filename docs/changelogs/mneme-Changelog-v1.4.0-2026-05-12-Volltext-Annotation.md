---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.4.0 — Volltext-Annotation statt Summarizing (2026-05-12)

- Kernkonzept geändert: kein Summarizing mehr — KI gibt den Originaltext vollständig zurück und bettet [[Wikilinks]] direkt im Text ein
- Neuer Verarbeitungsflow: Metadata-Extraktion → Chunk-weise Annotation → Frontmatter + Volltext zusammensetzen
- build_metadata_prompt(): extrahiert title/author/year als JSON aus dem ersten Teil des Textes
- build_annotation_prompt(): minimaler Prompt pro Chunk — "gib Text wortgetreu zurück, nur [[Links]] hinzufügen"
- parse_metadata(): parst JSON-Antwort mit Regex-Fallback
- chunk_text(): vereinfacht auf non-overlapping (Overlap würde zu doppeltem Text im Output führen)
- call_claude(): max_tokens Parameter, 8192 für Annotation, 256 für Metadata
- Frontmatter enthält jetzt source_pdf Feld (originaler PDF-Dateiname)
- derive_output_filename() nimmt jetzt metadata dict statt raw markdown
- Frontend: zeigt "Wikilinks gesetzt" (tatsächliche Link-Zahl im Output) statt "Wikilinks verfügbar"
- Log zeigt Links pro Chunk und Gesamtzahl
