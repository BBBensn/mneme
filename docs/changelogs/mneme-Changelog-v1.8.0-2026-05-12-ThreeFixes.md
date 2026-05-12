---
date_created: 2026-05-12
type: changelog
tags:
  - project
  - changelog
---

# v1.8.0 — Drei Fixes + Stub-File Erstellung (2026-05-12)

## 1. Flexionen repariert
- expand_german_inflections() nimmt jetzt full_text Parameter
- Alle generierten Kandidaten werden gegen den Volltext geprüft — nur Formen die wirklich vorkommen bleiben
- Nonsense wie "Soziologiee" wird sofort herausgefiltert
- Umlaut-Varianten (ä/ö/ü) kommen primär von der KI (Phase 1), Python-Expansion als Fallback für einfache +s/+es/+en Suffixe
- merge_terms() leitet full_text an expand_german_inflections weiter
- tokens.json wird automatisch invalidiert wenn MNEME_VERSION nicht übereinstimmt (_mneme_version Feld)

## 2. Kostenberechnung korrigiert
- Korrekte Preise: $0.80/MTok input = $0.0000008/token, $4.00/MTok output = $0.000004/token
- Formel: cost = input_tokens * 0.0000008 + output_tokens * 0.000004
- Alte Konstanten HAIKU_PRICE_INPUT/OUTPUT entfernt, neue HAIKU_PRICE_INPUT_PER_TOKEN/OUTPUT_PER_TOKEN

## 3. Stub-Files
- create_stubs(): erstellt minimale .md-Files für alle [[Wikilinks]] ohne existierende Notiz
- Ordner-Routing: Vor-Nachname → /Personen/, Methode/Analyse/etc. → /Methoden/, Rest → /Konzepte/
- Stub enthält YAML-Frontmatter (title, tags, created) + Heading + "Verlinkt in: [[source]]"
- Pre-Built Set aller existierenden Note-Namen für Performance (statt rglob pro Link)
- Response enthält stubs_created + stubs_existing
- Frontend zeigt "+ N neue Concept-Files erstellt"
