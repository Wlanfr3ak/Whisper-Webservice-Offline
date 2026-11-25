"""Smoke-Test: WAV-Datei ueber den /ws-Endpunkt transkribieren.

Aufruf im venv auf dem Server:
    python test_ws.py /pfad/test.wav [PASSWORT]
WAV wird (grob) auf 16 kHz mono int16 gebracht und in 500-ms-Stuecken
gesendet; Teil- und Final-Ergebnisse werden ausgegeben.
Passwort: sonst WHISPIRVM_PASSWORD aus der Umgebung / .env.
"""

import asyncio
import json
import os
import ssl
import sys
import urllib.request
import wave

import numpy as np
import websockets

RATE = 16000
URI = "wss://127.0.0.1:8443/ws"
LOGIN = "https://127.0.0.1:8443/login"


def login_cookie(ctx: ssl.SSLContext, password: str) -> str:
    req = urllib.request.Request(
        LOGIN, method="POST",
        data=json.dumps({"password": password}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ctx) as r:
        return r.headers["Set-Cookie"].split(";")[0]


def load_pcm16(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    assert sw == 2, "nur 16-bit-WAV"
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if rate != RATE:
        idx = np.linspace(0, len(a) - 1, int(len(a) * RATE / rate))
        a = np.interp(idx, np.arange(len(a)), a)
    return a.astype(np.int16).tobytes()


async def main(path: str, password: str) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE          # selbstsigniertes Testzertifikat
    cookie = login_cookie(ctx, password)
    async with websockets.connect(
            URI, ssl=ctx, additional_headers={"Cookie": cookie}) as ws:
        pcm = load_pcm16(path)
        await ws.send(json.dumps({"cmd": "start", "lang": None}))
        step = RATE                          # 500 ms int16
        for i in range(0, len(pcm), step):
            await ws.send(pcm[i:i + step])
            await asyncio.sleep(0.05)
        await ws.send(json.dumps({"cmd": "stop"}))
        while True:
            ev = json.loads(await ws.recv())
            if ev["ev"] == "partial":
                print("TEIL :", ev["text"])
            elif ev["ev"] == "final":
                print("FINAL:", ev["text"])
                if ev.get("conf") is not None:
                    print("CONF :", ev["conf"])
                for w in ev.get("words", []):
                    if w["p"] < 0.5:
                        print(f"  unsicher: {w['w']!r} ({w['p']:.0%})")
                return


if __name__ == "__main__":
    pw = (sys.argv[2] if len(sys.argv) > 2
          else os.environ.get("WHISPIRVM_PASSWORD", ""))
    asyncio.run(main(sys.argv[1], pw))
