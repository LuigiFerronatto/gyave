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

    Speaks sentence-by-sentence (see split_sentences()) rather than
    synthesizing the whole reply as one blob: shorter time-to-first-audio
    on long replies, and `gyave mute`/MUTE_FLAG_FILE is re-checked between
    sentences so a reply can be interrupted mid-playback, not just before
    it starts. At least one chunk must play successfully for this to
    report success overall.
    """
    try:
        import asyncio
        import edge_tts
    except ImportError:
        return False

    async def _synthesize(chunk: str, out_path: Path) -> bool:
        try:
            communicate = edge_tts.Communicate(chunk, cfg.voice, rate=cfg.rate)
            await communicate.save(str(out_path))
            return out_path.exists() and out_path.stat().st_size > 0
        except Exception:
            return False

    any_played = False
    for chunk in split_sentences(text):
        if MUTE_FLAG_FILE.exists():
            break  # interrupted mid-reply
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            if asyncio.run(_synthesize(chunk, out_path)):
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
