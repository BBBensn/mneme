---
date_created: 2026-05-13 11:10:11
type: changelog
tags:
  - project
  - changelog
date_modified: 2026-05-13 11:10:11
---

# v1.9.0 — Stub-Cleanup + Klassifizierung + Duplikat-UI (2026-05-13)

## 1. Stubs nur noch YAML
- create_stubs(): schreibt nur noch YAML-Frontmatter (title, tags, created), kein Body-Text
- cleanup_existing_stubs(): bereinigt bestehende Concept-Stubs in Personen/Methoden/Konzepte
- Neuer Endpoint POST /stubs/cleanup mit Response {"cleaned": N}
- Frontend Token-Seite: "Stubs bereinigen" Button

## 2. Klassifizierung verbessert
- _NOT_PERSON_WORDS Set: verhindert false positives (Soziale Medien, Universität Wien → Konzepte)
- should_create_stub(): einzelne Kleinbuchstaben-Wörter (Adjektive/Flexionen) bekommen keinen Stub
- get_stub_folder(): prüft jetzt >= 2 Wörter statt == 2, und schließt bekannte Non-Person-Wörter aus

## 3. Duplikat-Erkennung UI
- find_duplicate_pairs(): erkennt alle Begriffspaare wo A als ganzes Wort in B enthalten (regex \b)
- Neuer Endpoint GET /tokens: gibt token cache + Duplikat-Paare zurück
- Neuer Endpoint POST /tokens/merge: merged zwei Begriffe, löscht Stub des entfernten Begriffs
- Neuer Frontend-Tab "Token-Verwaltung" (Listen-Icon in Nav)
- Zeigt Duplikat-Paare als Karten mit [→ A] [→ B] [Ignorieren] Buttons
- "Ignorieren" ist session-lokal (kein Server-Call nötig)
- Merge kombiniert Aliases beider Begriffe und löscht den entfernten Stub

## 4. Kostenberechnung
- Bereits in v1.8.0 korrekt: $0.0000008/token input, $0.000004/token output — bestätigt
