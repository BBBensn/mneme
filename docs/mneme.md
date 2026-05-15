---
date_created: 2026-05-13 11:31:32
type: project
status: active
bereich: coding
tags: [project]
date_modified: 2026-05-14 10:12:00
---

---
# mneme

## Was ist das Projekt?

Lokales MacBook-Tool das wissenschaftliche PDFs automatisch in Obsidian-Notizen mit Wikilinks umwandelt. PDF wird per Drag & Drop eingeworfen, Text wird vollständig extrahiert und mit [[Wikilinks]] für Personen, Konzepte, Methoden und Fachbegriffe angereichert — kein Summarizing, sondern Annotation des Volltexts. Output landet direkt im Vault.

Teilprojekt von [[J-Vault]].

## Ziel / Done-Definition

- PDF droppen → annotiertes .md im Vault, ready to use in Obsidian
- Wikilinks konsistent gesetzt, Stub-Files automatisch erstellt
- Kosten unter 1¢ pro Paper im Auto-Modus
- Graph View in Obsidian zeigt sinnvolle Themenkomplexe
- Sprachübergreifende Token-Datenbank (DE/EN unified)
- Autoren-Datenbank für einfaches Zitieren

## Scope

**Dazu gehört:**

- PDF-Extraktion und Chunking (pymupdf)
- KI-gestützte Begriff-Erkennung: Ollama (lokal, Begriffe) + Claude (Qualität, Metadaten)
- Python-basierte konsequente Linksetzung im Volltext
- Stub-File Erstellung mit Ordnerstruktur (Personen/, Konzepte/, Methoden/)
- Persistente Token-Datenbank (tokens.json) die über PDFs hinweg wächst
- Multilingual: DE/EN Aliases damit Begriffe nicht doppelt auftauchen
- Duplikat-Erkennung, Tag-Merge UI, Token-Review Tab
- Review-Screen vor dem Speichern
- Bulk-Verarbeitung mehrerer PDFs
- Vault File Tree im Frontend
- Autoren-Datenbank + Zitationshilfe + Autoren-Links in YAML

**Zukünftig:**

- Literatursuche via Claude: "Welche Textstellen sind relevant für Thema X?"
- Claude sucht in tokens.json, lädt relevante Files, findet Textstellen

**Nicht dazu:**

- Cloud-Deploy, Server, Multi-User
- Vollautomatisches Vault-Management
- Direkte Obsidian-Plugin-Integration (vorerst)

## Meilensteine

- [x] v1.0 MVP: PDF → MD → Vault (Ollama + Claude) ✅ 2026-05-12
- [x] v1.x Kernkonzept: Volltext statt Zusammenfassung, Wikilinks inline ✅ 2026-05-12
- [x] v1.6 Zweiphasen-Ansatz: KI erkennt, Python setzt konsequent ✅ 2026-05-12
- [x] v1.7–1.9 Stub-Files, Vault Tree, Token-Persistenz, Duplikat-UI ✅ 2026-05-12
- [x] v2.0 Ollama rehabilitiert, Auto-Modus (Ollama + Claude Meta) ✅ 2026-05-13
- [x] v2.1 Progress-Anzeige, Noise-Filter ✅ 2026-05-13
- [x] v2.2 Review-Interface vor dem Speichern ✅ 2026-05-13
- [x] v2.3 Optimierte Arbeitsteilung: Phase 0-3, strukturierte MD-Sections ✅ 2026-05-13
- [x] v2.4 Multilingual Tokens (DE/EN Aliases), Autoren-DB, Zitation ✅ 2026-05-13
- [x] v2.5 YAML Fix, Dataview Autoren, Sections-Erkennung, Buch-Modus ✅ 2026-05-14
- [x] v2.6 YAML Citation Fix, 2-Spalten-Extraktion, Prompt-Caching, Timer ✅ 2026-05-14
- [x] v2.7 Header-Cleanup, Job-Log, Vault Reset, Jobs-Tab ✅ 2026-05-14
- [x] v2.8 Bugfixes: Titel, Header, Autoren-Links, fix-stubs Endpoint ✅ 2026-05-14
- [x] v2.9 Dataview-Fix, Alias-Konflikt, Kosten-Optimierung ✅ 2026-05-14
- [x] v2.9.1 Speichern-Bug Fix ✅ 2026-05-14
- [x] v2.9.2 Author-Parse Fix, Dataview Fix, Buch-Modus Debug ✅ 2026-05-14
- [x] v2.9.3 Titel-Fix, Dataview-Fix, Buch-Kapitel-Fix, Token-Accumulation ✅ 2026-05-14
- [x] v2.9.4 Author Plain Text, Buch-Crash Fix, Buch-Warnung ✅ 2026-05-15
- [ ] v3.0 Vault Explorer: Token-Liste, Merge-UI
- [ ] v3.1 Buch-Modus Review-Screen
- [ ] v3.2 Bulk-Verarbeitung (RAW-Data Batch)
- [ ] v3.1 Bulk-Verarbeitung (RAW-Data Batch)
- [ ] v3.x Graph-UI, Literatursuche via Claude API

## Offene Fragen / Bekannte Probleme

- **Speichern-Bug:** Behoben in v2.9.1. Ursache war fehlender Button-Reset (`btn.disabled = false`) in der Success-Branch des Confirm-Handlers — DOM-Button blieb disabled und war beim nächsten Review ausgegraut.
- **tokens.json Skalierung:** Wie gut skaliert bei 100+ Papers? Ab wann wird Lookup langsam?
- **Ollama-Qualität bei sehr langen Papers:** Bei >15 Chunks (gebatchte Aufrufe: >5 Batches) noch ungeprüft ob Ollama die größeren Input-Texte korrekt verarbeitet.
- **Buch-Modus Kapitel-Fehler:** Kapitel-Erkennung in v2.9.3 verbessert (progressives Matching, 25 Seiten TOC). Beim nächsten Auftreten mneme.log prüfen (exc_info=True aktiv).

## Stack & Infrastruktur

**Stack:** FastAPI (Python, Port 5050) + Vanilla JS Frontend + pymupdf + Ollama (llama3.1:8b) + Anthropic SDK (claude-haiku-4-5)

**Workflow Auto-Modus:**

1. Phase 0 — Python: PDF extrahieren (mit 2-Spalten-Erkennung), tokens.json laden
2. Phase 1 — Ollama: neue Begriffe erkennen (kostenlos, lokal)
3. Phase 2 — Claude: 1 gecachter API-Call — bereinigen, normalisieren, Metadaten, Sections-Info (~0.05-0.1¢)
4. Phase 3 — Python: Volltext bereinigen (Header-Cleanup via body_start_marker), verlinken, Stubs erstellen
5. Review-Screen: User bestätigt → Speichern schreibt Dateien + Autoren-Stubs + Job-Log

**Kosten Sweet Spot:** ~0.05-0.1¢ pro Paper im Auto-Modus (mit Prompt-Caching)

**Vault-Struktur:**

```
Vault/
├── Personen/       ← Autoren-Stubs (YAML + Dataview ## Werke Block)
├── Konzepte/       ← Konzept-Stubs
├── Methoden/       ← Methoden-Stubs
├── Bücher/         ← Buchkapitel-Ordner
├── RAW-Data/       ← Original PDFs
├── [Autor-Jahr-Titel].md
└── tokens.json
```

**Repo:** https://github.com/BBBensn/mneme **Lokaler Pfad:** `~/Documents/Coding/J-Vault/mneme/` **Port:** 5050

---

<!-- status: planning / active / paused / done / cancelled --> <!-- bereich: coding / music / fashion / creative / homelab / other -->
