"""GYAVE Voice Console — backend.

A tiny local web app (FastAPI + a single WebSocket) that lets a human talk
to whichever project/agent they're pointed at, through whichever CLI
engine they pick (Claude Code / Copilot CLI / Gemini CLI / etc, via
GYAVE's own `gyave.engine_router`), see a mascot react to what's
happening, and hear the reply spoken back via GYAVE.

Deliberately turn-based (not a full interactive pty session): each user
message becomes one headless CLI invoke call. This is a conscious v1
scope cut — see docs/GYAVE.md "Known limitations" — full tool-by-tool
streaming would require per-engine stream-json parsing that's only
confirmed for Claude today.

Project-agnostic by design (fixed 2026-08-26): GYAVE used to hard-import
`lao_core.engine_router` from a fixed path
(`/home/.../lab-autonomous-officer`), meaning the Console only ever
"spoke with" that one repo/project regardless of which `cwd` a message
carried — a wrong project's agent could be invoked while GYAVE silently
routed through LAO's own module. `gyave.engine_router` (this package) is
now the default, self-contained router; the request's own `cwd` (sent by
the frontend, defaulting to wherever the GYAVE server process itself was
started) is what's passed to the invoked CLI, not any hardcoded repo path.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gyave import core, stt
from gyave import engine_router
from gyave.config import Config, GYAVE_HOME

STATIC_DIR = GYAVE_HOME / "ui" / "static"
_IMPORT_ERROR = None

# The working directory the invoked CLI runs in when a websocket message
# doesn't specify its own `cwd` — defaults to wherever the GYAVE server
# process itself was launched from (i.e. `cd my-project && gyave ui`),
# NOT a hardcoded repo. GYAVE_DEFAULT_CWD is an explicit opt-in override
# for anyone who wants a different fallback without touching launch cwd.
DEFAULT_REPO = os.environ.get("GYAVE_DEFAULT_CWD", os.getcwd())

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
def api_voices(provider: str = "edge"):
    """Return the voice list for the SELECTED TTS provider — each engine
    has a different, incompatible voice namespace (edge-tts ShortNames
    like "pt-BR-AntonioNeural" vs. OpenAI's "alloy" vs. Polly's "Camila"
    vs. espeak's bare language codes), so the picker must refresh whenever
    the provider changes instead of always showing the fixed edge-tts list.
    """
    from gyave.providers import list_edge_voices, list_openai_voices, list_polly_voices, list_espeak_voices, list_elevenlabs_voices

    if provider == "edge":
        voices = list_edge_voices("pt-") + list_edge_voices("en-")
        if not voices:  # network unavailable — fail open to the static curated list
            voices = VOICES
        else:
            voices = [
                {"id": v["short_name"], "label": f"{v['friendly_name']} ({v['locale']}, {v['gender'] or '?'})"}
                for v in voices
            ]
    elif provider == "openai":
        voices = [{"id": v["short_name"], "label": v["friendly_name"]} for v in list_openai_voices()]
    elif provider == "polly":
        voices = [{"id": v["short_name"], "label": v["friendly_name"]} for v in list_polly_voices()]
    elif provider == "espeak":
        voices = [{"id": v["short_name"], "label": v["friendly_name"]} for v in list_espeak_voices()]
    elif provider == "elevenlabs":
        voices = [{"id": v["short_name"], "label": v["friendly_name"]} for v in list_elevenlabs_voices()]
    else:  # silent — no real voice concept
        voices = [{"id": "silent", "label": "N/A (modo silencioso)"}]

    return {"voices": voices}


@app.get("/api/tts-providers")
def api_tts_providers():
    """List TTS providers the Voice Console can switch between, with
    whether each is actually usable right now (installed + credentialed).
    Powers the frontend's provider picker so switching isn't limited to
    `GYAVE_ENGINE=...`/`gyave provider ...` on the CLI.
    """
    import os as _os
    from gyave.providers import PROVIDERS

    def _available(name: str) -> bool:
        if name in ("edge", "espeak", "silent"):
            return True  # edge/espeak fail open at speak-time; always offer
        if name == "openai":
            try:
                import openai  # noqa: F401
            except ImportError:
                return False
            return bool(_os.environ.get("OPENAI_API_KEY"))
        if name == "polly":
            try:
                import boto3  # noqa: F401
            except ImportError:
                return False
            return bool(_os.environ.get("AWS_ACCESS_KEY_ID")) or Path.home().joinpath(".aws/credentials").exists()
        if name == "elevenlabs":
            try:
                import elevenlabs  # noqa: F401
            except ImportError:
                return False
            return bool(_os.environ.get("ELEVENLABS_API_KEY"))
        return True

    labels = {
        "edge": "Microsoft Edge (gratuito, neural)",
        "openai": "OpenAI TTS (pago)",
        "polly": "AWS Polly (pago)",
        "elevenlabs": "ElevenLabs (pago, streaming)",
        "espeak": "eSpeak (offline, robótico)",
        "silent": "Silencioso (log apenas)",
    }
    out = [
        {"id": name, "label": labels.get(name, name), "available": _available(name)}
        for name in PROVIDERS
    ]
    return {"providers": out}


LAO_REALTIME_INSTRUCTIONS = os.environ.get(
    "GYAVE_REALTIME_INSTRUCTIONS",
    """# Role and Objective
Você é o LAO (Lab Autonomous Officer), agente autônomo de pesquisa e inovação H3 da Blip.
Responda perguntas sobre tecnologia, inovação, pesquisa e estratégia de produto da Blip.

# Personality and Tone
Direto, curioso, levemente técnico mas sempre acessível.
Fale como um colega de time — não como um assistente formal nem como um robô.
Demonstre entusiasmo genuíno por tecnologia emergente.

# Language
Padrão: português brasileiro natural e fluente.
Se o usuário mudar de idioma, acompanhe após uma confirmação breve.

# Reasoning
Para respostas diretas e confirmações simples, responda rápido sem raciocinar.
Para perguntas multi-step, análises ou decisões, raciocine brevemente antes de falar.
Se o áudio estiver pouco claro, peça clarificação — não adivinhe.

# Preambles
Use preambles curtos somente quando estiver consultando algo ou raciocinando:
- Prefira: 'Deixa eu verificar...' / 'Vou checar aqui...'
- Evite: 'Hmm...' / 'Um momento enquanto processo...'
Para respostas diretas ou confirmações, responda sem preamble.

# Verbosity
Respostas diretas: 1-2 frases curtas (~5 segundos de fala).
Se precisar de mais detalhes, pergunte 'Quer que eu aprofunde?' antes de falar muito.
Troubleshooting: um passo por vez.

# Unclear Audio
Se o áudio estiver pouco claro, peça para repetir com naturalidade: 'Pode repetir? Não ouvi bem.'
Não tente adivinhar o que foi dito.""",
)


@app.post("/api/realtime/session")
async def api_realtime_session(instructions: str | None = None):
    """Create an OpenAI Realtime API ephemeral client_secret for a WebRTC
    session. The browser connects directly to OpenAI using this token
    (browser ↔ OpenAI), so audio never passes through the GYAVE server
    — low latency, no server-side audio processing.

    Requires OPENAI_API_KEY in the environment.
    Returns: {client_secret, session_id, voice, model} on success,
             {error: str} with status 400/503 on failure.
    """
    import httpx
    from fastapi.responses import JSONResponse

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse({"error": "OPENAI_API_KEY não configurada no servidor GYAVE."}, status_code=503)

    session_instructions = instructions or LAO_REALTIME_INSTRUCTIONS
    voice = os.environ.get("GYAVE_REALTIME_VOICE", "ballad")
    model = os.environ.get("GYAVE_REALTIME_MODEL", "gpt-4o-realtime-preview")

    payload = {
        "session": {
            "type": "realtime",
            "instructions": session_instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "gpt-realtime-whisper"},
                    "noise_reduction": None,
                    "turn_detection": {"type": "semantic_vad", "eagerness": "medium"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": voice,
                },
            },
            "output_modalities": ["audio"],
            "tools": [],
            "max_output_tokens": 4096,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:
        return JSONResponse({"error": f"Erro ao contatar OpenAI: {exc}"}, status_code=503)

    if resp.status_code != 200:
        return JSONResponse({"error": f"OpenAI retornou {resp.status_code}: {resp.text[:300]}"}, status_code=resp.status_code)

    data = resp.json()
    # client_secrets endpoint returns: {"value": "ek_...", "session": {"id": ...}}
    # sessions endpoint returns: {"client_secret": {"value": "ek_..."}, "id": "sess_..."}
    client_secret = (
        data.get("value")                                   # client_secrets format
        or (data.get("client_secret") or {}).get("value")  # sessions format
        or data.get("client_secret")                        # fallback string
    )
    session_id = (data.get("session") or {}).get("id") or data.get("id") or data.get("session_id")
    return {"client_secret": client_secret, "session_id": session_id, "voice": voice, "model": model}


@app.post("/api/stt")
async def api_stt(file: UploadFile = File(...), language: str = Form("pt"), provider: str = Form("local")):
    """Server-side STT — complements the browser-native Web Speech API
    push-to-talk path for browsers without SpeechRecognition (e.g.
    Firefox), for low-quality mic captures where Web Speech mis-hears, or
    for privacy-sensitive sessions. Two providers, both opt-in:

    - `provider=local` (default): faster-whisper, fully offline once the
      model is cached. Added after auditing ricardotrevisan/ai-voice-agent.
    - `provider=openai`: OpenAI's hosted Whisper API (`whisper-1`), same
      service used by the VoiceMode MCP server (kumaran srinivasan's
      article) — needs `OPENAI_API_KEY`, costs ~$0.006/min, but skips the
      local model download/inference cost entirely.

    Returns {"text": null} (not an HTTP error) if the requested provider
    isn't available - callers should fall back to typed input either way.
    """
    audio_bytes = await file.read()
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    if provider == "openai":
        text = stt.transcribe_openai(audio_bytes, suffix=suffix, language=language)
        err = None if text else "OpenAI Whisper indisponível (defina OPENAI_API_KEY) ou áudio não reconhecido"
    else:
        text = stt.transcribe_bytes(audio_bytes, suffix=suffix, language=language)
        err = None if text else "Whisper local indisponível (pip install faster-whisper) ou áudio não reconhecido"
    return {"text": text, "provider": provider, "error": err}


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
        "openai_stt_available": stt.openai_available(),
    }


def _run_invoke(engine: str, prompt: str, cwd: str | None) -> dict:
    """Blocking call — run on a worker thread from the websocket handler."""
    if engine_router is None:
        return {"ok": False, "text": f"engine_router indisponível: {_IMPORT_ERROR}"}
    resolved_engine = engine if engine != "auto" else None
    priority = ["copilot", "claude", "gemini"]

    tried = set()
    while True:
        try:
            chosen = engine_router.pick_engine(resolved_engine, priority)
        except Exception:
            chosen = resolved_engine or "claude"

        if chosen in tried:
            # We already tried this engine in this call, avoid infinite loop
            break
        tried.add(chosen)

        binary = engine_router.binary_for(chosen)
        import shutil
        if not shutil.which(binary):
            if engine == "auto":
                engine_router.record_failure(chosen, f"CLI binary '{binary}' not found on PATH")
                continue
            return {"ok": False, "text": f"CLI {binary!r} não encontrado no PATH."}

        cmd = engine_router.build_invoke_command(chosen, prompt)
        import subprocess
        try:
            result = subprocess.run(
                cmd, cwd=cwd or DEFAULT_REPO, timeout=300,
                capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            if engine == "auto":
                engine_router.record_failure(chosen, "Timeout expired")
                continue
            return {"ok": False, "text": "Tempo esgotado esperando a resposta do CLI."}

        if result.returncode != 0:
            stderr = result.stderr or ""
            if engine == "auto":
                engine_router.record_failure(chosen, stderr)
                continue
            return {"ok": False, "text": f"Erro ({chosen}): {stderr[:400] or 'sem detalhes'}"}

        return {"ok": True, "text": result.stdout.strip(), "engine": chosen}

    return {"ok": False, "text": "Todos os mecanismos de CLI disponíveis falharam (erros de quota ou indisponibilidade)."}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    
    chunk_events = {}
    user_msg_queue = asyncio.Queue()
    
    async def receiver():
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("type") == "audio_ended":
                    cid = msg.get("chunk_id")
                    if cid in chunk_events:
                        chunk_events[cid].set()
                elif msg.get("type") == "user_message":
                    await user_msg_queue.put(msg)
        except WebSocketDisconnect:
            # Set all pending events to unblock any waiting thread
            for evt in list(chunk_events.values()):
                evt.set()
    
    recv_task = asyncio.create_task(receiver())
    
    try:
        while True:
            msg = await user_msg_queue.get()
            text = (msg.get("text") or "").strip()
            engine = msg.get("engine") or "auto"
            voice = msg.get("voice") or "pt-BR-AntonioNeural"
            tts_provider = msg.get("tts_provider") or "edge"
            rate = msg.get("rate")
            volume = msg.get("volume")
            mute = bool(msg.get("mute"))
            audio_output = msg.get("audio_output") or "system"
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
            cfg.engine = tts_provider
            if rate:
                cfg.rate = rate
            if volume:
                cfg.volume = volume
            # The Voice Console is an active conversation, not passive hook
            # narration — talkback-win's ~800-char "skip long analytical
            # output" heuristic was silently swallowing normal-length
            # replies here with zero feedback in the UI (bug found
            # 2026-08-26: a 1350-char reply was logged as "skip: too
            # long" but the console just stayed silent). Global defaults
            # were raised to 15000 chars / 12 bullets (config.py) so every
            # hook (Claude/Copilot/Gemini) and the Console behave the same
            # way; these env vars remain as an optional per-surface
            # override on top of that shared default.
            import os as _os
            cfg.max_chars = int(_os.environ.get("GYAVE_CONSOLE_MAX_CHARS", str(cfg.max_chars)))
            cfg.max_bullets = int(_os.environ.get("GYAVE_CONSOLE_MAX_BULLETS", str(cfg.max_bullets)))
            
            def _browser_play_fn(out_path) -> bool:
                import base64
                import uuid
                try:
                    with out_path.open("rb") as f:
                        data = f.read()
                    b64 = base64.b64encode(data).decode("utf-8")
                    
                    mime = "audio/mpeg"
                    if out_path.suffix == ".wav":
                        mime = "audio/wav"
                    elif out_path.suffix == ".ogg":
                        mime = "audio/ogg"
                    
                    cid = str(uuid.uuid4())
                    evt = asyncio.Event()
                    chunk_events[cid] = evt
                    
                    asyncio.run_coroutine_threadsafe(
                        websocket.send_json({
                            "type": "audio_chunk",
                            "chunk_id": cid,
                            "data": b64,
                            "mime_type": mime
                        }),
                        loop
                    )
                    
                    try:
                        asyncio.run_coroutine_threadsafe(evt.wait(), loop).result(timeout=60)
                    except Exception:
                        pass
                    finally:
                        chunk_events.pop(cid, None)
                    return True
                except Exception:
                    return False
            
            play_fn = _browser_play_fn if audio_output == "browser" else None
            spoken, skip_reason = await loop.run_in_executor(None, core.speak_text, reply_text, cfg, play_fn)
            if not spoken and not mute:
                await websocket.send_json({
                    "type": "tts_skipped",
                    "text": f"Áudio não tocado ({skip_reason or 'motivo desconhecido'}).",
                })

            await websocket.send_json({"type": "state", "value": "idle"})
    except Exception:
        pass
    finally:
        recv_task.cancel()


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    import uvicorn

    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
