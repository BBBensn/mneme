---
date_created: 2026-05-13
type: changelog
tags:
  - project
  - changelog
---

# v2.4.0 — Multilingual Tokens + Titelextraktion + Autoren-DB (2026-05-13)

## Multilingual tokens.json
- Neues Format: `{canonical: {type, aliases, translations: {de, en}, forms: [...]}}`
- `forms[]` enthält alle sprachlichen Varianten: Flexionen + Übersetzungen
- Phase 0 nutzt `forms[]` als Alias-Liste → englische Begriffe aus alten Papers werden auch in deutschen Texten verlinkt (und umgekehrt)
- Verlinkung cross-lingual: `[[Lernen|Learning]]` wenn "Learning" im EN-Text vorkommt
- `load_token_cache()` liest sowohl altes (flaches Listen-Format) als auch neues Dict-Format
- `save_token_cache()` schreibt immer im neuen Format, merged translations und forms korrekt
- `merge_token_terms()` Endpoint korrekt auf neues Format aktualisiert
- Migrations-Endpoint `POST /tokens/migrate`: konvertiert altes Format → neues Format (ohne Claude-Call, Übersetzungen werden ab jetzt bei neuen Papers automatisch ergänzt)
- Frontend: "Auf v2.4 migrieren" Button in Token-Verwaltung

## Claude Prompt Erweiterungen (Phase 2)
- Jeder Begriff bekommt jetzt `de` und `en` Felder → landen in `translations`
- Metadaten erweitert: `affiliation` (Institution des Erstautors), `citation_apa`, `citation_chicago`
- Titelextraktion verbessert: expliziter Hinweis dass Titel ≠ erster Abstract-Satz; Claude gibt `null` zurück wenn kein sicherer Titel → Fallback auf Dateiname

## Titel-Fallback
- Wenn Claude-Titel null/leer: automatisch Dateiname (bereinigt) als Titel
- `extract_metadata_regex()` ebenfalls verbessert (bestehend)

## Autoren-Datenbank
- `update_author_stub()`: Erstellt oder aktualisiert Author-Stub in Personen/ mit erweitertem YAML
  - Felder: title, type, tags [person, author], affiliation, works[], created
  - Bei existierendem Stub: works-Liste wird ergänzt (nicht überschrieben)
- `confirm_process` und `bulk_confirm` rufen `update_author_stub` automatisch auf
- Neuer Endpoint `GET /authors`: listet alle Author-Stubs aus Personen/
- `cleanup_existing_stubs()` erkennt jetzt auch `-person` und `-method` Tags

## Zitationen im Review
- Review-Screen zeigt APA-Zitation unter den Token-Sektionen
- Frontmatter der Literature-Note enthält `citation_apa` und `citation_chicago` Felder
- Frontmatter auch erweitert mit `affiliation` wenn vorhanden

## Stub-System
- `create_stubs()` schreibt korrekte Tags: person/method/concept statt immer "concept"
- Ollama-only und Claude-only Pfade liefern jetzt explizit `translations: {}` in claude_tokens

- Version auf 2.4.0 gesetzt
