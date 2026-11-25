# WhisperVM

**Status: lauffaehiges Test-Deployment auf LXC, Version 0.5.2.**

Webbasiertes Diktier-Tool mit Live-Transkription:

- Diktat im Browser aufnehmen (max. 60 Sekunden)
- Audio wird live als PCM16 (16 kHz mono) per WebSocket an den Server gestreamt
- Server verschriftet chunkweise (4-s-Fenster) mit faster-whisper
  `large-v3-turbo` (int8, CPU); bei Stopp Final-Pass ueber das Gesamtdiktat
- Transkript erscheint nahezu live in einem Logging-Fenster
- Text muss **kopiert UND exportiert** werden, bevor weiter diktiert werden darf
- Datensparsam: Audio/Text nur im RAM; Audio wird nach dem Final-Pass sofort
  vernichtet, Text bei Reset/Disconnect. Keine Ablage, kein Access-Log,
  kein localStorage im Browser.

Details zum Konzept siehe [MACHBARKEIT.md](MACHBARKEIT.md).
Verbindliche Regeln in [AGENTS.md](AGENTS.md).

## Aufruf

`https://whispirvm.local:8443` – selbstsigniertes Zertifikat, Warnung im Browser
einmalig bestaetigen (Mikrofon braucht sicheren Kontext).

**Passwort-Schutz:** Ohne Login kein Zugriff auf Tool und WebSocket.
Passwort steht in `/opt/whispirvm/.env` (`WHISPIRVM_PASSWORD`, nicht im
Repo). Nach erfolgreichem Login setzt der Server ein Cookie
(`whispirvm_session`, HttpOnly, 30 Tage) – kein erneutes Einloggen noetig.
Cookie ist ein stateless HMAC-Token: Passwortaenderung invalidiert alle
Sitzungen automatisch.

## Struktur

```
server/app/main.py         FastAPI: Login, statische Seite + WebSocket /ws
server/app/auth.py         Passwort-Auth (stateless HMAC-Cookie)
server/app/session.py      RAM-Session: PCM-Puffer, 60s-Cap, Zustandsautomat
server/app/transcriber.py  faster-whisper Worker (seriell, 1 Thread-Pool)
server/app/static/         index.html, app.js, pcm-worklet.js (AudioWorklet)
server/test_ws.py          Smoke-Test: WAV ueber WS transkribieren
server/test_suite.py       Umfassende Testsuite (Auth, WS, Zustaende, Limits)
server/whispirvm.service   systemd-Unit (HF_HUB_OFFLINE=1, kein Access-Log)
server/requirements.txt    gepinnte Abhaengigkeiten
sync.sh                    Dateien -> Server pushen + Dienst neustarten
```

## Server-Setup (Debian 13 LXC, bereits eingerichtet)

```bash
apt install python3-venv openssl
python3 -m venv /opt/whispirvm/venv
/opt/whispirvm/venv/bin/pip install -r /opt/whispirvm/requirements.txt
# Modell einmalig laden (landet in /root/.cache/huggingface):
/opt/whispirvm/venv/bin/python -c \
  "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"
# Self-Signed-Zertifikat -> /opt/whispirvm/certs/{cert,key}.pem
# systemd-Unit installieren + starten (macht sync.sh mit)
```

Zur Laufzeit ist alles offline: `HF_HUB_OFFLINE=1`, Modell aus lokalem Cache,
keine dauerhaften Verbindungen zu Abhaengigkeiten (Regel-3-Aufweichung, siehe
AGENTS.md).

## Sync-Workflow

Lokal aendern, dann `./sync.sh` (Git Bash): pusht `server/` nach
`/opt/whispirvm` via pscp/plink (PuTTY-Key `fabian.ppk`, Hostkey gepinnt) und
startet `whispirvm.service` neu.

## Tests

Auf dem Server:

```bash
cd /opt/whispirvm
./venv/bin/python test_suite.py          # ganze Suite (liest .env selbst)
./venv/bin/python test_ws.py test.wav    # einzelner Transkript-Smoke-Test
```

Die Suite testet End-to-End: Login/Auth (401, Cookie-Flags, falsche
Cookies), WS-Gating, Session-Zustandsautomat, Stille-Skip, Sprach-Partial
und Final mit Konfidenz, 60-s-Cap, Session-Isolation, Reset-/Zweit-Zyklus,
Fehlertoleranz bei kaputten Frames.

## Externe Abhaengigkeiten (freigegeben, Regel 3 aufgeweicht)

fastapi, uvicorn[standard], faster-whisper, numpy (+ transitive, siehe
requirements.txt). Einmaliger Download okay, zur Laufzeit keine dauerhaften
Verbindungen.
