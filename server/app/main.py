"""WhisperVM – Backend (FastAPI).

WebSocket /ws: PCM16-Audio (16 kHz, mono, little-endian) rein,
JSON-Events mit Transkript raus. Alle Nutzerdaten leben nur im RAM
der jeweiligen Session und werden bei Reset/Disconnect vernichtet.
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, auth, transcriber  # noqa: F401  (Modell laden)
from .session import Session

log = logging.getLogger("whispirvm")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="WhisperVM", version=__version__,
              docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index(request: Request):
    if auth.valid_cookie(request.cookies.get(auth.COOKIE_NAME)):
        return FileResponse(STATIC_DIR / "index.html")
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
async def login(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not auth.check_password(str(data.get("password", ""))):
        return JSONResponse({"ok": False}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE_NAME, auth.make_cookie(),
                    max_age=auth.MAX_AGE, httponly=True, secure=True,
                    samesite="lax")
    return resp


async def _sender(ws: WebSocket, out: asyncio.Queue) -> None:
    """Serielle Ausgabe Richtung Browser."""
    while True:
        await ws.send_text(json.dumps(await out.get(), ensure_ascii=False))


async def _drain(session: Session, jobs: asyncio.Queue,
                 out: asyncio.Queue) -> None:
    """Holt Transkriptions-Jobs nacheinander ab und meldet Ergebnisse."""
    while True:
        kind, audio, language, gen = await jobs.get()
        try:
            res = await asyncio.wrap_future(
                transcriber.submit(audio, language, vad=(kind == "final")))
        except Exception:
            log.exception("Transkription fehlgeschlagen")
            res = {"text": "", "words": [], "conf": None}
        if gen != session.gen:
            continue                     # Session resettet -> Ergebnis verwerfen
        if kind == "final":
            session.finish(res["text"])
            await out.put({"ev": "final", "text": res["text"],
                           "words": res["words"], "conf": res["conf"],
                           "state": session.state})
        else:
            session.committed.append(res["text"])
            await out.put({"ev": "partial",
                           "text": session.committed_text()})


async def _finalize(session: Session, jobs: asyncio.Queue,
                    out: asyncio.Queue) -> None:
    """Aufnahme beenden und Final-Pass ueber den ganzen Puffer anstossen."""
    if not session.recording:
        return
    session.recording = False
    if session.samples == 0:
        session.finish("")
        await out.put({"ev": "final", "text": "", "state": session.state})
    else:
        await jobs.put(("final", session.full_audio(),
                        session.language, session.gen))


@app.websocket("/ws")
async def ws_handler(ws: WebSocket) -> None:
    if not auth.valid_cookie(ws.cookies.get(auth.COOKIE_NAME)):
        await ws.close(code=4401)
        return
    await ws.accept()
    session = Session()
    out: asyncio.Queue = asyncio.Queue()
    jobs: asyncio.Queue = asyncio.Queue()
    tasks = [asyncio.create_task(_sender(ws, out)),
             asyncio.create_task(_drain(session, jobs, out))]
    try:
        await out.put({"ev": "state", "state": session.state})
        while True:
            msg = await ws.receive()
            if (data := msg.get("bytes")) is not None:
                if session.recording:
                    capped = not session.add_audio(data)
                    while (seg := session.pending_window()) is not None:
                        await jobs.put(("partial", seg, session.language,
                                        session.gen))
                    if capped:
                        await _finalize(session, jobs, out)
                continue
            try:
                cmd = json.loads(msg.get("text") or "{}")
            except json.JSONDecodeError:
                continue
            if cmd.get("cmd") == "start" and session.state == "ready":
                session.start(cmd.get("lang"))
                await out.put({"ev": "state", "state": session.state})
            elif cmd.get("cmd") == "stop":
                await _finalize(session, jobs, out)
            elif cmd.get("cmd") == "reset":
                session.reset()
                while not jobs.empty():
                    jobs.get_nowait()
                await out.put({"ev": "state", "state": session.state})
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        session.reset()
