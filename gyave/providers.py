"""TTS provider abstraction. Each provider implements speak(text, cfg) and
returns True on success. gyave.core tries providers in priority order and
always fails open (never raises out to the caller).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from gyave.config import Config, MUTE_FLAG_FILE

# Sentence splitter for chunked/interruptible playback. Inspired by
# ricardotrevisan/ai-voice-agent's LLM-streaming TTS queue (splits on
# sentence-ending punctuation so audio can start before the whole reply is
# ready, and playback can be interrupted between sentences) - adapted here
# for GYAVE's already-fully-resolved text: we don't stream token-by-token,
# but we still gain (a) faster time-to-first-audio for long replies and
# (b) a natural interrupt point every sentence (checked via MUTE_FLAG_FILE,
# so `gyave mute` stops a reply mid-playback instead of only preventing the
# *next* one).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text into speakable chunks. Falls back to the whole text as a
    single chunk if no sentence boundaries are found.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return parts or ([text] if text.strip() else [])


def _pick_player() -> list[str] | None:
    """Return the argv prefix for whichever audio player is on PATH."""
    candidates = {
        "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
        "paplay": ["paplay"],
        "aplay": ["aplay", "-q"],
        "afplay": ["afplay"],  # macOS
    }
    for name, argv in candidates.items():
        if shutil.which(name):
            return argv
    return None


def _play_file(path: Path) -> bool:
    argv = _pick_player()
    if not argv:
        return False
    try:
        subprocess.run(argv + [str(path)], check=True, timeout=120,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def speak_edge(text: str, cfg: Config) -> bool:
    """Microsoft Edge Read-Aloud TTS via the `edge-tts` python package.
    Free, no API key, 300+ neural voices — but not offline (network call to
    Microsoft's endpoint) and unofficial/reverse-engineered.

    Speaks sentence-by-sentence (see split_sentences()) with a **pipelined
    synthesize-ahead** strategy (added 2026-08-26, after raising
    max_chars/max_bullets to 15000/12 made long replies common enough that
    the old strictly-sequential "synthesize sentence N, THEN play it, THEN
    synthesize N+1" loop produced an audible gap before every sentence —
    each gap is edge-tts's network round-trip time, and a long reply has
    many sentences, so the gaps added up to a noticeably slow/choppy
    delivery). Now sentence N+1 is synthesized on a background thread
    *while* sentence N is still playing, so by the time playback of N
    finishes, N+1's audio file is usually already sitting on disk ready to
    play — only the very first sentence pays the full synth-then-play
    latency. `gyave mute`/MUTE_FLAG_FILE is still re-checked between
    sentences so a reply can be interrupted mid-playback. At least one
    chunk must play successfully for this to report success overall.
    """
    try:
        import asyncio
        import edge_tts
    except ImportError:
        return False

    import concurrent.futures

    async def _synthesize(chunk: str, out_path: Path) -> bool:
        try:
            communicate = edge_tts.Communicate(
                chunk, cfg.voice, rate=cfg.rate,
                volume=getattr(cfg, "volume", "+0%"),
                pitch=getattr(cfg, "pitch", "+0Hz"),
            )
            await communicate.save(str(out_path))
            return out_path.exists() and out_path.stat().st_size > 0
        except Exception:
            return False

    def _synthesize_sync(chunk: str) -> Path | None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            if asyncio.run(_synthesize(chunk, out_path)):
                return out_path
        except Exception:
            pass
        out_path.unlink(missing_ok=True)
        return None

    chunks = split_sentences(text)
    if not chunks:
        return False

    any_played = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        # Kick off synthesis of the first chunk, then loop: while chunk N
        # plays, chunk N+1's synthesis future is already running.
        next_future = pool.submit(_synthesize_sync, chunks[0])
        for i, _chunk in enumerate(chunks):
            if MUTE_FLAG_FILE.exists():
                break  # interrupted mid-reply
            out_path = next_future.result()
            # Start synthesizing the NEXT sentence immediately, before
            # blocking on playback of the current one.
            if i + 1 < len(chunks):
                next_future = pool.submit(_synthesize_sync, chunks[i + 1])
            if out_path is not None:
                try:
                    if _play_file(out_path):
                        any_played = True
                except Exception:
                    pass
                finally:
                    out_path.unlink(missing_ok=True)
    return any_played


def speak_openai(text: str, cfg: Config) -> bool:
    """OpenAI TTS (`tts-1`/`gpt-4o-mini-tts`) — paid, requires
    `OPENAI_API_KEY`. Added to GYAVE's provider pool after auditing
    ricardotrevisan/ai-voice-agent, which pairs Whisper STT with OpenAI's
    LLM; OpenAI TTS is the natural paid-tier neighbor. Opt-in only — never
    in AUTO_ORDER, since it costs money and needs a credential, unlike the
    free/no-key `edge` default. Select explicitly via `GYAVE_ENGINE=openai`
    and set `GYAVE_OPENAI_VOICE` (default "alloy").
    """
    try:
        from openai import OpenAI
    except ImportError:
        return False
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        return False

    voice = os.environ.get("GYAVE_OPENAI_VOICE", "alloy")
    model = os.environ.get("GYAVE_OPENAI_TTS_MODEL", "tts-1")
    any_played = False
    try:
        client = OpenAI()
        for chunk in split_sentences(text):
            if MUTE_FLAG_FILE.exists():
                break
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                out_path = Path(tmp.name)
            try:
                with client.audio.speech.with_streaming_response.create(
                    model=model, voice=voice, input=chunk
                ) as response:
                    response.stream_to_file(str(out_path))
                if out_path.exists() and out_path.stat().st_size > 0:
                    if _play_file(out_path):
                        any_played = True
            except Exception:
                pass
            finally:
                out_path.unlink(missing_ok=True)
    except Exception:
        return False
    return any_played


def speak_polly(text: str, cfg: Config) -> bool:
    """AWS Polly neural TTS — paid, requires AWS credentials (standard
    boto3 credential chain: env vars, `~/.aws/credentials`, or an
    instance/role profile). Added to GYAVE's provider pool after auditing
    ricardotrevisan/ai-voice-agent, which uses Polly's "Camila" (pt-BR) /
    "Joanna" (en-US) neural voices. Opt-in only — never in AUTO_ORDER.
    Select explicitly via `GYAVE_ENGINE=polly` and set `GYAVE_POLLY_VOICE`
    (default "Camila") / `GYAVE_AWS_REGION` (default "us-east-1").
    """
    try:
        import boto3
    except ImportError:
        return False
    import os

    voice_id = os.environ.get("GYAVE_POLLY_VOICE", "Camila")
    region = os.environ.get("GYAVE_AWS_REGION", "us-east-1")
    any_played = False
    try:
        client = boto3.client("polly", region_name=region)
        for chunk in split_sentences(text):
            if MUTE_FLAG_FILE.exists():
                break
            try:
                response = client.synthesize_speech(
                    Text=chunk, VoiceId=voice_id, Engine="neural",
                    OutputFormat="mp3",
                )
                audio_bytes = response["AudioStream"].read()
            except Exception:
                continue
            if not audio_bytes:
                continue
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                out_path = Path(tmp.name)
                tmp.write(audio_bytes)
            try:
                if _play_file(out_path):
                    any_played = True
            finally:
                out_path.unlink(missing_ok=True)
    except Exception:
        return False
    return any_played


def speak_espeak(text: str, cfg: Config) -> bool:
    """Fully offline, robotic fallback via espeak-ng or spd-say."""
    if shutil.which("espeak-ng"):
        binname = "espeak-ng"
    elif shutil.which("espeak"):
        binname = "espeak"
    elif shutil.which("spd-say"):
        try:
            subprocess.run(["spd-say", "-w", text], check=True, timeout=60)
            return True
        except Exception:
            return False
    else:
        return False
    try:
        subprocess.run([binname, "-v", "pt-br" if _looks_pt(text) else "en", text],
                        check=True, timeout=60,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _looks_pt(text: str) -> bool:
    hints = ("ção", "não", "está", "você", "para", " de ", " que ")
    return any(h in text.lower() for h in hints)


def speak_silent(text: str, cfg: Config) -> bool:
    """No-op provider: just logs. Used on hosts with no audio device, or for
    dry-run/testing.
    """
    print(f"[gyave:silent] would speak: {text}", file=sys.stderr)
    return True


def list_edge_voices(locale_prefix: str | None = None) -> list[dict]:
    """List real available edge-tts voices via the library's own
    `list_voices()` API (same data source as the `edge-tts --list-voices`
    CLI command documented in rany2/edge-tts's README). Returns a list of
    {"name", "short_name", "gender", "locale"} dicts, optionally filtered
    to a locale prefix (e.g. "pt-" or "en-"). Fails open to [] if edge_tts
    isn't installed or the network call fails (e.g. offline).
    """
    try:
        import asyncio
        import edge_tts
    except ImportError:
        return []

    async def _fetch():
        return await edge_tts.list_voices()

    try:
        raw = asyncio.run(_fetch())
    except Exception:
        return []

    out = []
    for v in raw:
        locale = v.get("Locale", "")
        if locale_prefix and not locale.startswith(locale_prefix):
            continue
        out.append({
            "short_name": v.get("ShortName", ""),
            "gender": v.get("Gender", ""),
            "locale": locale,
            "friendly_name": (v.get("FriendlyName") or v.get("ShortName", "")),
        })
    return out


def list_openai_voices() -> list[dict]:
    """OpenAI TTS has a fixed, small voice set (not a queryable API) —
    documented at platform.openai.com/docs/guides/text-to-speech. Returned
    here as a static list so the Voice Console's voice picker can offer
    something concrete when "OpenAI TTS" is the selected provider, instead
    of silently reusing the (irrelevant) edge-tts pt-BR voice list.
    """
    names = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    return [{"short_name": n, "gender": "", "locale": "", "friendly_name": n.capitalize()} for n in names]


def list_polly_voices(locale_prefix: str | None = None) -> list[dict]:
    """List real available AWS Polly neural voices via boto3's
    `describe_voices`. Fails open to a small static fallback (Camila/
    Joanna, the two voices GYAVE's speak_polly() defaults reference) if
    boto3/credentials aren't available — keeps the picker usable even
    without a live AWS session.
    """
    fallback = [
        {"short_name": "Camila", "gender": "Female", "locale": "pt-BR", "friendly_name": "Camila (PT-BR)"},
        {"short_name": "Joanna", "gender": "Female", "locale": "en-US", "friendly_name": "Joanna (EN-US)"},
    ]
    try:
        import boto3
        import os as _os
        client = boto3.client("polly", region_name=_os.environ.get("GYAVE_AWS_REGION", "us-east-1"))
        resp = client.describe_voices(Engine="neural")
        out = []
        for v in resp.get("Voices", []):
            locale = v.get("LanguageCode", "")
            if locale_prefix and not locale.startswith(locale_prefix):
                continue
            out.append({
                "short_name": v.get("Id", ""),
                "gender": v.get("Gender", ""),
                "locale": locale,
                "friendly_name": f"{v.get('Name', v.get('Id', ''))} ({locale})",
            })
        return out or fallback
    except Exception:
        return fallback


def list_espeak_voices() -> list[dict]:
    """eSpeak/spd-say are fully offline and don't expose a rich voice
    catalog — return the two languages GYAVE's speak_espeak() actually
    selects between (pt-br / en), so the picker stays honest about what
    this provider can do instead of showing unrelated Edge/OpenAI names.
    """
    return [
        {"short_name": "pt-br", "gender": "", "locale": "pt-BR", "friendly_name": "Português (robótico)"},
        {"short_name": "en", "gender": "", "locale": "en-US", "friendly_name": "English (robotic)"},
    ]


PROVIDERS = {
    "edge": speak_edge,
    "espeak": speak_espeak,
    "openai": speak_openai,
    "polly": speak_polly,
    "silent": speak_silent,
}

# Order tried when engine == "auto". Deliberately excludes "openai"/"polly"
# — both need a paid credential, so auto-fallback must never silently
# start billing a cloud account; they're only used when explicitly
# selected via GYAVE_ENGINE=openai|polly.
AUTO_ORDER = ["edge", "espeak", "silent"]


def speak(text: str, cfg: Config) -> tuple[bool, str]:
    """Try the configured engine; fall back through AUTO_ORDER on failure.
    Returns (success, engine_used).
    """
    order = AUTO_ORDER if cfg.engine == "auto" else [cfg.engine] + [
        e for e in AUTO_ORDER if e != cfg.engine
    ]
    for engine in order:
        fn = PROVIDERS.get(engine)
        if fn and fn(text, cfg):
            return True, engine
    return False, "none"
