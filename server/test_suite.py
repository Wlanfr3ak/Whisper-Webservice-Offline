"""Umfassende Testsuite fuer WhisperVM – End-to-End gegen den laufenden Dienst.

Quertestet: HTTP-Auth, Login, Cookie, WS-Gating, Session-Zustandsautomat,
Stille-Skip, 60-s-Cap, Reset-Flow, Zweit-Diktat, Session-Isolation,
Fehlertoleranz (kaputte JSON/Frames), Sprach-Option.

Aufruf auf dem Server:
    ./venv/bin/python test_suite.py [/pfad/test.wav]

Passwort: argv[2] > WHISPIRVM_PASSWORD env > ./.env neben dem Skript.
Sprach-Test braucht eine WAV mit gesprochenem Text (z. B. TTS); ohne
Datei wird nur dieser eine Test uebersprungen, der Rest laeuft.
"""

import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import wave

import numpy as np
import websockets

BASE = "127.0.0.1:8443"
HTTPS = f"https://{BASE}"
WSS = f"wss://{BASE}/ws"
RATE = 16000

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

RESULTS = []


def report(name: str, ok: bool, info: str = "") -> None:
    RESULTS.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<38} {info}")


def password() -> str:
    if len(sys.argv) > 2:
        return sys.argv[2]
    if os.environ.get("WHISPIRVM_PASSWORD"):
        return os.environ["WHISPIRVM_PASSWORD"]
    envf = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if line.startswith("WHISPIRVM_PASSWORD="):
                return line.strip().split("=", 1)[1]
    return ""


def load_pcm16(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
    assert sw == 2
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if rate != RATE:
        idx = np.linspace(0, len(a) - 1, int(len(a) * RATE / rate))
        a = np.interp(idx, np.arange(len(a)), a)
    return a.astype(np.int16).tobytes()


def http_get(path: str, cookie: str | None = None):
    req = urllib.request.Request(HTTPS + path)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, context=CTX) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def http_login(pw: str):
    req = urllib.request.Request(
        HTTPS + "/login", method="POST",
        data=json.dumps({"password": pw}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=CTX) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


async def ws_open(cookie: str | None):
    kw = {"ssl": CTX, "open_timeout": 10}
    if cookie:
        kw["additional_headers"] = {"Cookie": cookie}
    return await websockets.connect(WSS, **kw)


async def recv_ev(ws, timeout: float = 60.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def maybe_ev(ws, timeout: float):
    """Event oder None bei Timeout."""
    try:
        return await recv_ev(ws, timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return None


async def send_pcm(ws, pcm: bytes, chunk_ms: int = 500, delay: float = 0.01):
    step = RATE * 2 * chunk_ms // 1000
    for i in range(0, len(pcm), step):
        await ws.send(pcm[i:i + step])
        await asyncio.sleep(delay)


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


# ----------------------------- HTTP-Tests ---------------------------------

def t_http(pw: str) -> str | None:
    st, body, _ = http_get("/")
    report("http_index_ohne_cookie->login", st == 200 and "Anmeldung" in body)

    st, _ = http_login("definitiv-falsch")
    report("http_login_falsches_pw->401", st == 401, f"status={st}")

    st, body, _ = http_get("/", cookie="whispirvm_session=fake123")
    report("http_index_falsches_cookie->login",
           st == 200 and "Anmeldung" in body)

    req = urllib.request.Request(HTTPS + "/login", method="POST",
                                 data=b"{kaputtes json")
    try:
        urllib.request.urlopen(req, context=CTX)
        st = 200
    except urllib.error.HTTPError as e:
        st = e.code
    report("http_login_kaputtes_json->401", st == 401, f"status={st}")

    st, hdrs = http_login(pw)
    sc = hdrs.get("set-cookie", "")
    ok = (st == 200 and "whispirvm_session=" in sc and "HttpOnly" in sc
          and "Secure" in sc)
    report("http_login_ok->cookie", ok, f"status={st}")
    if not ok:
        return None
    cookie = sc.split(";")[0]

    st, body, _ = http_get("/", cookie=cookie)
    report("http_index_mit_cookie->tool", st == 200 and "Aufnahme" in body)
    return cookie


# ----------------------------- WS-Tests -----------------------------------

async def t_ws_rejects():
    for name, cookie in [("ohne", None),
                         ("falsch", "whispirvm_session=abc")]:
        try:
            ws = await ws_open(cookie)
            ev = await maybe_ev(ws, 3)
            await ws.close()
            ok = False
        except Exception as e:  # Handshake-Reject oder sofortiger Close
            ok = True
            ev = type(e).__name__
        report(f"ws_reject_cookie_{name}", ok, str(ev)[:40])


async def t_ws_flow(cookie: str, pcm_speech: bytes | None):
    ws = await ws_open(cookie)
    ev = await recv_ev(ws)
    report("ws_state_ready", ev.get("ev") == "state"
           and ev.get("state") == "ready", str(ev))

    # Audio vor 'start' muss ignoriert werden
    await send_pcm(ws, pcm_speech or silence(5))
    ev = await maybe_ev(ws, 6)
    report("ws_audio_vor_start_ignoriert", ev is None)

    # kaputtes JSON -> kein Crash
    await ws.send("kein-json")
    await ws.send(json.dumps({"cmd": "bogus"}))
    await asyncio.sleep(0.3)

    await ws.send(json.dumps({"cmd": "start", "lang": "de"}))
    ev = await recv_ev(ws)
    report("ws_start->recording", ev.get("state") == "recording")

    if pcm_speech:
        await send_pcm(ws, pcm_speech)
        partials = []
        while (ev := await maybe_ev(ws, 30)) is not None:
            if ev["ev"] == "partial":
                partials.append(ev["text"])
            else:
                break
        ok = partials and all(len(p) > 2 for p in partials)
        report("ws_partial_sprache", ok,
               f"{len(partials)} Teil-Events" if partials else "keine")
    await ws.send(json.dumps({"cmd": "stop"}))
    ev = await recv_ev(ws, 90)
    ok = ev["ev"] == "final" and ev["state"] == "locked"
    if pcm_speech:
        ok = ok and len(ev["text"]) > 3
    report("ws_stop->final+locked", ok, (ev.get("text") or "")[:50])
    report("ws_final_conf+words",
           ev.get("conf") is None or isinstance(ev.get("conf"), float),
           f"conf={ev.get('conf')}")

    # start bei locked darf nicht aufnehmen -> naechstes Event muss
    # state=ready (vom reset) sein, nicht recording
    await ws.send(json.dumps({"cmd": "start"}))
    await ws.send(json.dumps({"cmd": "reset"}))
    ev = await recv_ev(ws)
    report("ws_start_bei_locked_ignoriert+reset",
           ev.get("state") == "ready", str(ev))
    await ws.close()


async def t_silence(cookie: str):
    ws = await ws_open(cookie)
    await recv_ev(ws)
    await ws.send(json.dumps({"cmd": "start"}))
    await recv_ev(ws)
    await send_pcm(ws, silence(6))          # > 1 Fenster, alles Stille
    ev = await maybe_ev(ws, 10)
    report("ws_stille_kein_partial", ev is None,
           "kein Event" if ev is None else str(ev)[:40])
    await ws.send(json.dumps({"cmd": "stop"}))
    ev = await recv_ev(ws, 90)
    report("ws_stille_final_leer", ev["ev"] == "final" and ev["text"] == "",
           (ev.get("text") or "<leer>")[:40])
    await ws.send(json.dumps({"cmd": "reset"}))
    await recv_ev(ws)
    await ws.close()


async def t_cap60(cookie: str):
    ws = await ws_open(cookie)
    await recv_ev(ws)
    await ws.send(json.dumps({"cmd": "start"}))
    await recv_ev(ws)
    await send_pcm(ws, silence(62), chunk_ms=2000, delay=0.001)
    ev = await recv_ev(ws, 120)             # Final ohne 'stop'!
    report("ws_cap_60s_autofinal", ev["ev"] == "final"
           and ev["state"] == "locked", str(ev)[:50])
    await ws.send(json.dumps({"cmd": "reset"}))
    await recv_ev(ws)
    await ws.close()


async def t_isolation(cookie: str):
    a, b = await ws_open(cookie), await ws_open(cookie)
    ea, eb = await recv_ev(a), await recv_ev(b)
    await a.send(json.dumps({"cmd": "start"}))
    ra = await recv_ev(a)
    eb2 = await maybe_ev(b, 3)
    ok_b_unberuehrt = eb2 is None           # b bekommt nichts von a
    await b.send(json.dumps({"cmd": "start"}))
    rb = await recv_ev(b)
    await a.send(json.dumps({"cmd": "stop"}))
    await b.send(json.dumps({"cmd": "stop"}))
    fa = await recv_ev(a, 90)
    fb = await recv_ev(b, 90)
    ok = (ea["state"] == "ready" and eb["state"] == "ready"
          and ra["state"] == "recording" and rb["state"] == "recording"
          and ok_b_unberuehrt
          and fa["ev"] == "final" and fb["ev"] == "final")
    report("ws_session_isolation", ok,
           f"a={fa.get('state')} b={fb.get('state')}")
    for w in (a, b):
        await w.send(json.dumps({"cmd": "reset"}))
        await w.close()


async def t_cycle(cookie: str):
    """Zweites Diktat nach Reset: kompletter Kreislauf."""
    ws = await ws_open(cookie)
    await recv_ev(ws)
    for i in range(2):
        await ws.send(json.dumps({"cmd": "start"}))
        await recv_ev(ws)
        await send_pcm(ws, silence(1))
        await ws.send(json.dumps({"cmd": "stop"}))
        ev = await recv_ev(ws, 90)
        if ev["ev"] != "final":
            report("ws_zweit_diktat", False, f"Runde {i}: {ev}")
            break
        await ws.send(json.dumps({"cmd": "reset"}))
        ev = await recv_ev(ws)
        if ev["state"] != "ready":
            report("ws_zweit_diktat", False, f"Runde {i}: {ev}")
            break
    else:
        report("ws_zweit_diktat", True, "2 Zyklen ok")
    await ws.close()


async def t_lang_option(cookie: str):
    ws = await ws_open(cookie)
    await recv_ev(ws)
    await ws.send(json.dumps({"cmd": "start", "lang": "en"}))
    ev = await recv_ev(ws)
    ok = ev.get("state") == "recording"
    await ws.send(json.dumps({"cmd": "stop"}))
    await recv_ev(ws, 90)
    await ws.send(json.dumps({"cmd": "reset"}))
    await recv_ev(ws)
    report("ws_lang_option_en", ok)
    await ws.close()


# --------------------------------- Main ------------------------------------

async def main() -> int:
    wav = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test.wav"
    pcm_speech = None
    if os.path.exists(wav):
        pcm_speech = load_pcm16(wav)
        print(f"Sprach-WAV: {wav} ({len(pcm_speech) / 2 / RATE:.1f} s)")
    else:
        print(f"HINWEIS: {wav} fehlt – Sprach-Teiltest wird uebersprungen")

    pw = password()
    if not pw:
        print("FEHLER: kein Passwort (env/.env/argv)")
        return 2

    cookie = t_http(pw)
    if cookie is None:
        print("ABBRUCH: Login kaputt – WS-Tests unmoeglich")
    else:
        await t_ws_rejects()
        await t_ws_flow(cookie, pcm_speech)
        await t_silence(cookie)
        await t_lang_option(cookie)
        await t_isolation(cookie)
        await t_cycle(cookie)
        await t_cap60(cookie)

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\n{len(RESULTS)} Tests, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
