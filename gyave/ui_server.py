"""GYAVE Voice Console — backend.

A tiny local web app (FastAPI + a single WebSocket) that lets a human talk
to LAO through whichever CLI engine they pick (Claude Code / Copilot CLI /
Gemini CLI, via lao_core.engine_router), see a mascot react to what's
happening, and hear the reply spoken back via GYAVE.

Deliberately turn-based (not a full interactive pty session): each user
message becomes one `engine_router.py invoke` call. This is a conscious v1
scope cut — see docs/GYAVE.md "Known limitations" — full tool-by-tool
streaming would require per-engine stream-json parsing that's only
confirmed for Claude today.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gyave import core, stt
from gyave.config import Config, GYAVE_HOME

STATIC_DIR = GYAVE_HOME / "ui" / "static"

# lao_core.engine_router lives inside the LAO repo, not inside ~/.gyave.
# GYAVE_LAO_REPO lets the console point at whichever checkout is active;
# falls back to the well-known path used throughout this machine's setup.
import os

DEFAULT_REPO = os.environ.get(
    "GYAVE_LAO_REPO",
    "/home/luigiferronatto/Desktop/Workspace/lab-autonomous-officer",
)
if DEFAULT_REPO not in sys.path:
    sys.path.insert(0, DEFAULT_REPO)

try:
    from lao_core import engine_router
except Exception as exc:  # pragma: no cover - surfaced to the UI instead
    engine_router = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = None

app = FastAPI(title="GYAVE Voice Console")

VOICES = [
    {"id": "pt-BR-AntonioNeural", "label": "Antônio (PT-BR, masculino)"},
    {"id": "pt-BR-FranciscaNeural", "label": "Francisca (PT-BR, feminino)"},
    {"id": "pt-BR-ThalitaMultilingualNeural", "label": "Thalita (PT-BR, feminino, multilíngue)"},
    {"id": "en-US-AriaNeural", "label": "Aria (EN-US, feminino)"},
    {"id": "en-US-GuyNeural", "label": "Guy (EN-US, masculino)"},
]


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/engines")
def api_engines():
    if engine_router is None:
        return {"error": _IMPORT_ERROR, "engines": []}
    out = []
    for name in engine_router.ENGINES:
        out.append({
            "id": name,
            "available": engine_router.is_available(name),
        })
    return {"engines": out}


@app.get("/api/voices")
def api_voices():
    return {"voices": VOICES}


@app.post("/api/stt")
async def api_stt(file: UploadFile = File(...), language: str = "pt"):
    """Server-side STT fallback via local Whisper (faster-whisper) —
    complements the browser-native Web Speech API push-to-talk path for
    browsers without SpeechRecognition (e.g. Firefox) or for
    privacy-sensitive sessions that shouldn't rely on a Chromium build's
    cloud STT round-trip. Added after auditing
    ricardotrevisan/ai-voice-agent's local Whisper transcribe endpoint.
    Returns {"text": null} (not an error) if faster-whisper isn't
    installed - callers should fall back to typed input either way.
    """
    audio_bytes = await file.read()
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    text = stt.transcribe_bytes(audio_bytes, suffix=suffix, language=language)
    return {"text": text, "whisper_available": stt.is_available()}


@app.get("/api/health")
def api_health():
    """Lightweight liveness probe (pattern borrowed from
    ricardotrevisan/ai-voice-agent's /health) - useful for a monitoring
    script or a second-screen dashboard to confirm the Voice Console
    backend is actually up before attempting a WebSocket connection.
    """
    return {
        "status": "ok",
        "engine_router_loaded": engine_router is not None,
        "engines_available": (
            sum(1 for n in engine_router.ENGINES if engine_router.is_available(n))
            if engine_router is not None else 0
        ),
        "whisper_stt_available": stt.is_available(),
    }


def _run_invoke(engine: str, prompt: str, cwd: str | None) -> dict:
    """Blocking call — run on a worker thread from the websocket handler."""
    if engine_router is None:
        return {"ok": False, "text": f"engine_router indisponível: {_IMPORT_ERROR}"}
    resolved_engine = engine if engine != "auto" else None
    priority = ["copilot", "claude", "gemini"]
    try:
        chosen = engine_router.pick_engine(resolved_engine, priority)
    except Exception:
        chosen = resolved_engine or "claude"
    binary = engine_router.binary_for(chosen)
    import shutil
    if not shutil.which(binary):
        return {"ok": False, "text": f"CLI {binary!r} não encontrado no PATH."}
    cmd = engine_router.build_invoke_command(chosen, prompt)
    import subprocess
    try:
        result = subprocess.run(
            cmd, cwd=cwd or DEFAULT_REPO, timeout=300,
            capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "Tempo esgotado esperando a resposta do CLI."}
    if result.returncode != 0:
        stderr = (result.stderr or "")[:400]
        return {"ok": False, "text": f"Erro ({chosen}): {stderr or 'sem detalhes'}"}
    return {"ok": True, "text": result.stdout.strip(), "engine": chosen}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") != "user_message":
                continue

            text = (msg.get("text") or "").strip()
            engine = msg.get("engine") or "auto"
            voice = msg.get("voice") or "pt-BR-AntonioNeural"
            mute = bool(msg.get("mute"))
            cwd = msg.get("cwd") or DEFAULT_REPO
            if not text:
                continue

            await websocket.send_json({"type": "state", "value": "thinking"})
            await websocket.send_json({"type": "user_echo", "text": text})

            result = await loop.run_in_executor(None, _run_invoke, engine, text, cwd)

            if not result.get("ok"):
                await websocket.send_json({"type": "state", "value": "error"})
                await websocket.send_json({"type": "assistant_message", "text": result["text"], "error": True})
                await websocket.send_json({"type": "state", "value": "idle"})
                continue

            reply_text = result["text"]
            await websocket.send_json({
                "type": "assistant_message",
                "text": reply_text,
                "engine": result.get("engine"),
            })
            await websocket.send_json({"type": "state", "value": "speaking"})

            cfg = Config.load()
            cfg.voice = voice
            cfg.mute = mute
            await loop.run_in_executor(None, core.speak_text, reply_text, cfg)

            await websocket.send_json({"type": "state", "value": "idle"})
    except WebSocketDisconnect:
        pass


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    import uvicorn

    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
