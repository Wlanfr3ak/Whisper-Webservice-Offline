# Machbarkeitsstudie & Konzept – WhisperVM

> Status: **Machbarkeit bestaetigt** – PoC implementiert und auf
> Test-LXC (192.168.2.98:8443) verifiziert: Live-Transkription,
> 60-s-Limit und Export-Zwang funktionieren Ende-zu-Ende.
> Version: 0.5.1

## 1. Ziel & Anforderungen

Webanwendung zum Diktieren mit folgenden harten Anforderungen:

| # | Anforderung |
|---|-------------|
| A1 | Aufnahme eines Diktats im Browser, **max. 60 Sekunden** |
| A2 | Audio wird **live** an den Server gestreamt |
| A3 | Server verschriftet **chunkweise** mit Whisper |
| A4 | Transkript erscheint nahezu live in einem **Logging-Fenster** |
| A5 | Nach Diktatende muss der Text **kopiert/exportiert** werden, bevor weiter diktiert werden darf |
| A6 | **Datensparsamkeit:** keine Nutzerdaten auf Datenträger – alles im RAM, danach vergessen |

Rahmenbedingungen (geklärt): Deutsch + Englisch, 2–10 gleichzeitige Nutzer,
Einsatz lokal/VM oder öffentlich denkbar, Hardware (CPU/GPU) noch offen.

## 2. Machbarkeitsbewertung

**Kurzfazit: Machbar, kein technisches No-Go.** Alle Anforderungen sind mit
etablierter Technik lösbar. Projektumfang ist klein (wenige hundert Zeilen).

### A1 – Aufnahme & 60-s-Limit

- `getUserMedia` + `AudioWorklet` liefert Roh-PCM (16 kHz, mono, int16 →
  ~32 kB/s). Kein Container-Format, dadurch beliebig chunkbar.
- Alternative: `MediaRecorder` mit Stop/Start pro Zeitfenster (Chrome: webm/opus,
  Safari: mp4/aac) – einfacher, aber Codec-Vielfalt und Header-Problem bei
  `timeslice`-Chunks.
- **Empfehlung: PCM via AudioWorklet** – umgeht Codec-Probleme komplett.
- 60 s: clientseitiger Timer mit Auto-Stop + serverseitigem Hartlimit
  (Buffer-Cap, dann Verbindungsende). Doppelt abgesichert.
- Hinweis: Mikrofonzugriff erfordert HTTPS – Ausnahme nur `localhost`.

### A2 – Live-Transport

- **WebSocket** (Binär-Frames) ist die naheliegende Wahl: bidirektional
  (Audio hoch, Teilergebnisse runter), kein Datei-Zwischenschritt nötig.
- Alternativen (HTTP-Chunked-POST, WebRTC) sind halbduplex bzw. überdimensioniert.

### A3/A4 – Chunk-Transkription mit Whisper

Geeignete Whisper-Laufzeiten:

| Variante | Stärke | Schwäche |
|---|---|---|
| **faster-whisper** (CTranslate2) | CPU-tauglich, int8-Quantisierung, wenig RAM | Python-Binding |
| whisper.cpp | Sehr leichtgewichtig, eigener Server-Modus | C++-Integration |
| openai-whisper (Referenz) | – | zu schwer/langsam auf CPU |

- **Decoding komplett im RAM:** faster-whisper/PyAV öffnet `BytesIO` –
  kein Tempfile nötig. PCM-Pfad braucht nicht mal Decoder (direktes NumPy-Array).
- **Chunking-Strategie (Hybrid, empfohlen):**
  1. *Live-Pfad:* alle ~3–5 s wird der wachsende Puffer teiltranskribiert
     (mit ~1 s Überlappung oder "Local Agreement", damit keine Wörter an
     Chunk-Grenzen zerrissen werden) → Anzeige im Logfenster.
  2. *Final-Pfad:* bei Stop wird der gesamte Puffer (≤ 60 s) einmal komplett
     transkribiert → bestmögliche Qualität, ersetzt die Provisorien.
- **Modellwahl (festgelegt): `large-v3-turbo`** – Entscheidung des Users:
  "immer das beste Modell". Turbo liefert nahezu large-v3-Qualität
  (~1–2 % Unterschied, in Benchmarks teils besser) bei ca. 8× höherer
  Geschwindigkeit. `large-v3` selbst bleibt Option, sobald GPU gesichert ist.
- **Latenz-Schätzung:** auf moderner CPU (int8) ca. 4–8× Echtzeit → ein
  5-s-Live-Chunk in ~1 s, Final-Pass über 60 s in ~10–20 s. Auf GPU:
  Final-Pass in ~2–5 s. Modellbedarf ~1,6 GB (int8) bzw. ~3,2 GB (float16)
  im RAM/VRAM.
- Deutsch+Englisch → turbo ist mehrsprachig. Sprache fest `de` oder per
  `language`-Option umschaltbar; Auto-Erkennung pro Session möglich.

### A5 – Export-Zwang

- UI als **Zustandsautomat**: `bereit → aufnehmend → gesperrt(Ergebnis)
  → exportiert → bereit`. Im Zustand `gesperrt` ist Aufnahme blockiert,
  nur Kopieren (Clipboard API) oder Export (.txt via client-seitigem
  Blob-Download – **kein** Server-Roundtrip nötig).
- Serverseitig: Session hält den Finaltext im RAM; er wird erst durch
  explizites `reset` oder Disconnect vernichtet.

### A6 – Datensparsamkeit (Kernpunkt)

| Ebene | Maßnahme |
|---|---|
| Server-RAM | PCM-Ringbuffer + Ergebnis-Strings pro Session; Vernichtung bei `reset`/Disconnect |
| Server-Platte | **keine** Tempfiles, keine Audio-/Textablage; Modell-Dateien sind kein Nutzerdatum |
| Server-Logs | Transkripte niemals loggen; Log-Level so setzen, dass keine Inhalte landen |
| Client | kein localStorage/IndexedDB, keine Cookies, keine Accounts |
| Export | client-seitig generiert (Blob/Clipboard) |

- *Caveat:* OS-Swap kann RAM auf Platte schreiben. Für maximale Härte:
  Swap deaktivieren bzw. `mlock` (Deployment-Entscheidung, VM konfigurierbar).
- Passt zu AGENTS.md Regel 10: keine personenbezogenen Daten persistent.

### Skalierung 2–10 Nutzer

- RAM pro Session: 60 s × 32 kB/s ≈ **2 MB** – trivial.
- Engpass ist die Inferenz: 1 Whisper-Worker arbeitet seriell.
  → Eine Queue pro Server, ggf. N Worker. Mit `large-v3-turbo` auf CPU
  entstehen bei vielen gleichzeitigen Nutzern spürbare Queue-Wartezeiten –
  für 2–5 Nutzer tragbar; ab ~5+ wird GPU zur Empfehlung (dann wäre auch
  `large-v3` denkbar). Jeder zusätzliche Worker belegt ~1,6 GB RAM (int8).

### Hardware-Optionen (Diskussionsstand 2026-11)

Schaetzwerte fuer `large-v3-turbo` (int8/fp16), RT-Faktor = Echtzeitfaktor:

| Setup | RT-Faktor | 60-s-Final-Pass | Bemerkung |
|---|---|---|---|
| Aktuell: 4-Core-LXC (Debian 13) | ~1–2× (gemessen) | ~15–25 s | Referenz – erfuellt Anforderung bereits |
| i7-11700K (8C/16T, AVX-512) | ~3–5× | ~15–20 s | CPU-only; CTranslate2 nutzt AVX512_VNNI |
| i7-11700K + Arc A770 16 GB | ~10–30× | ~2–6 s | GPU nur via whisper.cpp-SYCL o. OpenVINO; macht `large-v3` live-tauglich; ~30–40 W GPU-Idle |
| Core Ultra 7 255H + 32 GB (Mini-PC) | ~3–6× CPU / ~5–15× iGPU | ~10–20 s / ~4–12 s | Arc-140T-iGPU via SYCL/OpenVINO; NPU praktisch ungenutzt; idle ~7–15 W → 24/7-tauglich |

- **Wichtig:** faster-whisper/CTranslate2 kann **keine Intel-GPUs**
  (GPU nur via CUDA). Jeder Intel-GPU-Pfad erfordert Backend-Wechsel zu
  whisper.cpp (SYCL) oder OpenVINO – `transcriber.py` ist dafuer
  austauschbar aufgebaut (gleiche Schnittstelle).
- **Empfehlung:** 255H-Klasse = bester Fit fuer 2–10 Nutzer (CPU-only
  bereits ausreichend, iGPU als Reserve, sehr sparsam im Dauerbetrieb).
  A770 = maximale Geschwindigkeit + echtes `large-v3`, aber fuer
  ≤60-s-Diktate Overkill.
- **Passthrough:** Intel-iGPU per `/dev/dri`-Render-Node auch in LXC
  moeglich (einfacher als NVIDIA); A770 eher VM + PCIe-Passthrough.

### Einsatzszenarien

- **Lokal/VM:** `http://localhost` genügt (Browser-Ausnahme für Mikrofon).
  LAN nur über HTTPS (self-signed) oder Port-Forward.
- **Öffentlich:** HTTPS-Pflicht (Reverse Proxy + Let's Encrypt) und dann
  zwingend: Zugangsschutz (z. B. Token aus `.env`), Rate-Limiting.
  → Bei öffentlichem Betrieb entsteht ein echter Server, der Nutzerdaten
  verarbeitet → Datenschutz-Hinweis/DSGVO-Einordnung nötig (siehe AGENTS.md #10).
- **Proxmox-Deployment:** LXC-Container reicht für den CPU-Pfad und ist
  pragmatischer (native CPU-Performance, ~4–6 GB RAM, einfache Backups).
  GPU-Passthrough ist in LXC möglich, aber frickelig → falls GPU für
  `large-v3`/Mehrnutzer-Betrieb geplant oder maximale Isolation bei
  öffentlichem Betrieb gewünscht: VM mit PCIe-Passthrough. App selbst ist
  deployment-neutral; die RAM-only-Garantie (Host-Swap) gilt in beiden
  Fällen auf Host-Ebene.

## 3. Architektur-Skizze (theoretisch)

```
Browser (statische Seite, kein Framework)
┌─────────────────────────────────────────────┐
│ Mic → AudioWorklet → PCM16-Chunks (≈500 ms) │─── WS (binär) ───┐
│ UI-Zustandsautomat + Logfenster             │◄── WS (JSON) ───┐│
│ Kopieren (Clipboard) / Export (.txt-Blob)   │                 ││
└─────────────────────────────────────────────┘                 ││
                                                                ││
Server (Python, FastAPI + uvicorn)                              ││
┌──────────────────────────────────────────────┐                ││
│ /ws-Endpoint → Session (BytesIO-Ringbuffer,  │◄───────────────┘│
│   60-s-Cap, lebt nur zur WS-Verbindung)      │                 │
│ WhisperWorker-Queue → faster-whisper (RAM)   │─────────────────┘
│   Modell: large-v3-turbo (int8/float16)      │
│   Teil-Pass alle ~3–5 s / Final-Pass @Stop   │
└──────────────────────────────────────────────┘
```

- Frontend: `index.html`, `recorder.js` (AudioWorklet), `ui.js` – bewusst
  frameworkfrei, passt zur Offline-/Minimal-Regel.
- Backend: ein Prozess, Whisper-Modell einmal beim Start in den RAM geladen.
- Alternative Server-Variante: `whisper.cpp`-Server als Inferenz-Dienst.

## 4. Risiken & offene Punkte

1. **Abhängigkeiten (geklärt):** Regel 3 wurde projektspezifisch aufgeweicht
   (siehe AGENTS.md): einmaliger Download okay, **keine dauerhaften
   Verbindungen** zur Laufzeit. Konsequenzen: `faster-whisper`, `fastapi`,
   `uvicorn` freigegeben; Modell einmalig bündeln + per lokalem Pfad laden
   (zur Laufzeit offline, z. B. `HF_HUB_OFFLINE=1`); keine Cloud-APIs oder
   Telemetrie; Pakete gepinnt in `requirements`.
2. **Modell-Bezug:** `large-v3-turbo` ≈ 1,6–3,2 GB je nach Quantisierung
   → einmalig bei Setup/Build von Hugging Face laden, ins Deployment
   bündeln und zur Laufzeit per lokalem Pfad verwenden (kein dauerhafter
   Bezug, Offline-Garantie z. B. `HF_HUB_OFFLINE=1`).
3. **Chunk-Grenzen:** Wortabschnitte im Live-Pfad – gelöst durch Überlappung
   + Final-Pass über den Gesamtpuffer.
4. **Hardware:** Auf dem aktuellen Test-LXC (4 Cores) verifiziert –
   `large-v3-turbo` laeuft echtzeitnah. Alternativ-Hardware bewertet
   in Abschnitt "Hardware-Optionen"; GPU-Pfade (Intel) erfordern
   Backend-Wechsel auf whisper.cpp/OpenVINO.
5. **Swap:** RAM-only-Garantie hängt an OS/VM-Konfiguration.
6. **Öffentlicher Betrieb:** Zugangsschutz + DSGVO-Einordnung offen.

## 5. Nächste Schritte (wenn Umsetzung freigegeben wird)

1. PoC: Single-User, localhost, PCM-Streaming,
   `faster-whisper large-v3-turbo` (int8) – Ziel: Live-Tauglichkeit auf der
   Zielhardware verifizieren.
2. Zustandsautomat + Export-Zwang + Session-Handling.
3. Härtung: TLS, Zugangstoken, Log-Konfiguration, Deployment (VM/Reverse-Proxy).
