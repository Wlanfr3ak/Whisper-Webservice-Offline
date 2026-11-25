# AGENTS.md 

## Generische AGENTS.MD

## Regeln für Änderungen (verbindlich)

1. **Versionsnummer hochzählen:** Bei JEDER Änderung am Code oder an den
   Konfigurationsvorlagen erhöhen
   (Semantic Versioning: MAJOR.MINOR.PATCH).
2. **Changelog pflegen:** Bei JEDER Änderung einen ausführlichen Eintrag
   im Changelog unten ergänzen – was, warum, betroffene Dateien.
3. **Keine externen Abhängigkeiten** ohne ausdrückliche Freigabe des Users –
   das Projekt soll ohne externe Abhängigkeiten und Offline lauffähig bleiben.
   Ausnahmen müssen abgesprochen und in requirements und der README. deutlich sein-
5. **Geheimnisse niemals in committete Dateien** schreiben. Passwörter
   ausschließlich über `.env` / `env:VARIABLE`-Referenzen in config.json.
6. **Kommentare und Nutzertexte auf Deutsch** (persönliches Projekt des Users).
7. **README.md pflegen** Es soll bei allen Schritten immer die README.md mit gepflegt werden.
8. **Release erstellen:** Zu jeder neuen `__version__` gehört ein Git-Tag
   `vX.Y.Z` plus GitHub-Release `$projektname X.Y.Z` auf
   github.com/Wlanfr3ak/$reponame. Release-Text in der bisherigen Form
   (`## Aenderungen gegenueber <vorherige>`, ASCII ohne Umlaute, Verweis auf
   den AGENTS.md-Changelog); der Tag zeigt auf den Versions-Commit.
9. **GitHub Kompatibilität** Immer die Projekte so pflegen das sensible Inhalte nie mit ins Repo kommen, alles was sensibel .gitignore sind usw.
10. **Datenschutz** Keine Inhalte oder Hinweise auf diese die mit Personenbezogenen Daten, Verlinkungen, Erwähnungen usw. aus gründen der Datensparsamkeit. Auf mögliche Informationen dieser Art immer verweisen.

## Projektspezifische Anpassungen (WhisperVM)

- **Regel 3 aufgeweicht:** Externe Abhängigkeiten sind erlaubt unter den
  Bedingungen: (a) einmaliger Download bei Setup/Build ist okay
  (pip-Pakete, Whisper-Modell), (b) **keine dauerhaften Verbindungen**
  zu Abhängigkeiten zur Laufzeit – Betrieb vollständig lokal (keine
  Cloud-APIs, keine Telemetrie, kein Registry-/Repo-Zugriff im laufenden
  Betrieb), (c) Abhängigkeiten gepinnt und in requirements + README
  deutlich gemacht. Konkret: Whisper-Modell einmalig bündeln und per
  lokalem Pfad laden (z. B. `HF_HUB_OFFLINE=1` zur Laufzeit).

## Changelog

### 0.5.1 - 2026-11-25
- MACHBARKEIT.md: neuer Abschnitt "Hardware-Optionen" – Bewertung
  i7-11700K (+Arc A770) vs. Core Ultra 7 255H vs. aktueller LXC,
  inkl. Hinweis dass faster-whisper keine Intel-GPUs kann
  (Backend-Wechsel whisper.cpp-SYCL/OpenVINO noetig).
  Risikopunkt Hardware entsprechend aktualisiert.
- Betroffene Dateien: MACHBARKEIT.md, AGENTS.md

### 0.5.0 - 2026-11-24
- Feature: Umfassende Testsuite server/test_suite.py (End-to-End gegen
  laufenden Dienst): HTTP-Auth (Login-Seite, 401, Cookie-Attribute,
  falsches Cookie/JSON), WS-Reject ohne Cookie, Zustandsautomat,
  Audio-vor-Start ignoriert, Sprach-Partial+Final+Konfidenz,
  Stille-Gating, Start-bei-Locked, Reset, lang-Option, Session-Isolation
  (2 parallele Clients), Zweit-Diktat-Zyklus, 60-s-Cap-Autofinal.
- Feature: "Neu laden"-Button im UI (Reload-Shortcut).
- sync.sh pusht test_suite.py mit.
- Betroffene Dateien: server/test_suite.py (neu),
  server/app/static/{index.html,app.js}, server/app/__init__.py, sync.sh

### 0.4.0 - 2026-11-24
- Feature: Passwort-Schutz mit Session-Cookie.
  - auth.py (neu): statelesses HMAC-Cookie (kein Server-Session-State),
    Passwort aus WHISPIRVM_PASSWORD (serverseitige .env, nie committet);
    Passwortwechsel invalidiert alle Cookies automatisch.
  - main.py: / zeigt login.html ohne gueltiges Cookie, POST /login setzt
    Cookie (HttpOnly, Secure, SameSite=lax, 30 Tage), /ws schliesst ohne
    Cookie mit Code 4401.
  - login.html (neu): Anmeldeformular (Deutsch).
  - whispirvm.service: EnvironmentFile=/opt/whispirvm/.env.
  - test_ws.py: loggt sich ein und sendet Cookie im WS-Handshake.
  - .env.example als Vorlage; sync.sh pusht sie mit (echte .env bleibt
    server-lokal, .gitignore).
- Betroffene Dateien: server/app/{auth.py,main.py,__init__.py},
  server/app/static/{login.html,app.js}, server/whispirvm.service,
  server/test_ws.py, server/.env.example, sync.sh

### 0.3.0 - 2026-11-24
- Feature: Wort-Konfidenzen aus Whisper (word_timestamps=True).
  - transcriber.py: transcribe_sync liefert jetzt dict {text, words, conf};
    words = pro Wort Wahrscheinlichkeit, conf = Mittelwert.
  - main.py: final-Event enthaelt words + conf.
  - app.js/index.html: Woerter mit p < 0,5 werden rot gewellt
    unterstrichen (Tooltip mit %), Status zeigt Gesamt-Sicherheit;
    Legende im Hinweistext.
  - test_ws.py: gibt conf + unsichere Woerter aus.
- Betroffene Dateien: server/app/transcriber.py, server/app/main.py,
  server/app/static/app.js, server/app/static/index.html,
  server/test_ws.py, server/app/__init__.py

### 0.2.1 - 2026-11-24
- Fix: Whisper-Halluzination ("Untertitelung des ZDF") bei Stille.
  - session.py: Stille-Gating – Teilfenster mit Peak < 0,3% werden nicht
    mehr an Whisper gegeben (MIN_PEAK), Audio-Daten bleiben fuer den
    Final-Pass im Puffer.
  - app.js: `ctx.resume()` falls AudioContext suspended; Pegel-Meter im
    UI zeigt live den Eingangspegel (Diagnose: kommt Mikro-Audio an?).
  - index.html: Pegel-Balken neben dem Timer.
- Fix sync.sh: `enable --now` -> `restart` (alter Code lief sonst weiter).
- Betroffene Dateien: server/app/session.py, server/app/static/app.js,
  server/app/static/index.html, server/app/__init__.py, sync.sh

### 0.2.0 - 2026-11-24
- Erste Umsetzung (PoC) auf Test-LXC root@192.168.2.98 (Debian 13,
  4 Cores, 8 GB RAM, CPU-only):
  - server/app/: FastAPI + WebSocket /ws, RAM-Session mit 60-s-Cap,
    faster-whisper Worker (large-v3-turbo, int8, seriell), Teilfenster
    4 s + Final-Pass, Export-Zwang serverseitig erzwungen.
  - server/app/static/: index.html + app.js (AudioWorklet -> PCM16 ->
    WebSocket), pcm-worklet.js; UI auf Deutsch, Zustandsautomat mit
    Kopieren+Export-Pflicht.
  - server/whispirvm.service: systemd-Unit, HTTPS (self-signed,
    Port 8443), HF_HUB_OFFLINE=1, --no-access-log.
  - server/requirements.txt: gepinnt via pip freeze des produktiven venv.
  - server/test_ws.py: WS-Smoke-Test (WAV -> Transkript).
  - sync.sh: pscp/plink-basierter Dateiabgleich + Service-Restart.
  - .gitignore angelegt (venv, Keys, WAV, Zertifikate).
- Verifiziert: HTTPS-Seite + E2E-Transkription TTS-WAV -> erwartetes
  Transkript (teil + final).
- README.md: Deployment-Doku, Struktur, Sync-Workflow, Setup-Schritte.
- MACHBARKEIT.md: Status auf "Machbarkeit bestaetigt" gesetzt.
- Betroffene Dateien: server/**, sync.sh, .gitignore, README.md,
  MACHBARKEIT.md, AGENTS.md

### 0.1.3 - 2026-11-24
- MACHBARKEIT.md: Deployment-Hinweis Proxmox ergaenzt (LXC fuer CPU-Pfad
  ausreichend und pragmatischer; VM bei GPU-Passthrough oder gewuenschter
  staerkerer Isolation im oeffentlichen Betrieb). Version 0.1.3.
- Betroffene Dateien: MACHBARKEIT.md, AGENTS.md

### 0.1.2 - 2026-11-24
- Regel 3 projektspezifisch aufgeweicht (Abschnitt "Projektspezifische
  Anpassungen" ergaenzt): externe Abhaengigkeiten erlaubt – einmaliger
  Download okay, keine dauerhaften Verbindungen zur Laufzeit
  (Entscheidung User).
- MACHBARKEIT.md: Risikopunkte Abhaengigkeiten + Modell-Bezug auf
  Freigabe unter Auflagen aktualisiert; Version 0.1.2.
- README.md: Stack-Hinweis auf Freigabe aktualisiert.
- Betroffene Dateien: AGENTS.md, MACHBARKEIT.md, README.md

### 0.1.1 - 2026-11-24
- Modellwahl festgelegt: `large-v3-turbo` als Zielmodell ("immer das beste
  Modell", Entscheidung User); `large-v3` bleibt Option sobald GPU gesichert.
- MACHBARKEIT.md: Latenz-/RAM-Schaetzungen, Skalierungs-, Risiko- und
  Architekturabschnitt sowie PoC-Plan auf turbo angepasst.
- README.md: geplanter Stack aktualisiert.
- Betroffene Dateien: MACHBARKEIT.md, README.md, AGENTS.md

### 0.1.0 - 2026-11-24
- AGENTS.md aus Wlanfr3ak/mixed-scripts uebernommen und Changelog-Abschnitt ergaenzt (Regel 2).
- MACHBARKEIT.md erstellt: Machbarkeitsstudie und theoretische Architekturskizze
  fuer das Diktier-Tool (Browser-Aufnahme, Live-Streaming via WebSocket,
  chunkweise Whisper-Transkription, 60-s-Limit, Export-Zwang, RAM-only).
- README.md initial angelegt (Projektziel, Status Konzeptphase, geplanter Stack).
- Noch keine Umsetzung; externe Abhaengigkeiten (FastAPI, faster-whisper)
  als freigabepflichtig markiert (Regel 3).
