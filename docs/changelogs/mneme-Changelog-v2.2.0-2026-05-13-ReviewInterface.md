---
date_created: 2026-05-13
type: changelog
tags:
  - project
  - changelog
---

# v2.2.0 — Review-Interface + Noise-Filter (2026-05-13)

- /process speichert nicht mehr sofort — gibt stattdessen `{status: "review_ready", draft: {...}}` zurück
- Neuer Review-Screen nach dem Run: Begriffsliste mit Checkboxen, Duplikat-Vorschläge, Aktionsbuttons
- Noise-Filter vor dem Review (5 Regeln): Impressums-Blacklist, Abbildungsrefs, URLs/technische Strings, <4 Zeichen, reine Zahlen
- Checkbox-Liste: alle erkannten Begriffe mit [cache]-Badge für bekannte Begriffe, [gefiltert]-Badge für rausgefilterte (initial deaktiviert)
- "Alle ✓ / Alle ☐" Toggle für Masse-Selektion
- Mögliche Duplikate im Review direkt auflösen: Merge-Richtung wählen oder ignorieren
- [Nochmal mit Claude]: sendet aktive Begriffe an Claude Quality Pass → Claude deaktiviert eindeutige False Positives
- [Speichern]: POST /process/confirm mit selected_terms + merged_terms → schreibt Datei + tokens.json + Stubs
- [✕ Verwerfen]: verwirft Draft, nichts wird gespeichert
- Navigations-Guard: Verlassen des Review-Screens mit currentDraft zeigt Confirm-Dialog
- Version auf 2.2.0 gesetzt
