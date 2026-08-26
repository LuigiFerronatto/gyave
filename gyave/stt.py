"""Optional server-side STT via faster-whisper (local Whisper inference).

Added to GYAVE's pool of tools after auditing ricardotrevisan/ai-voice-agent,
which runs Whisper locally for PT-BR transcription instead of a cloud STT
API. This is a *complement* to the Voice Console's default browser-native
Web Speech API STT (`app.js`), not a replacement:

- Web Speech API: zero-install, free, works in Chrome/Edge, requires no
  server-side model - the default push-to-talk path.
- This module: works in any browser (including Firefox, which has no
  Web Speech API), fully offline once the model is downloaded, and keeps
  audio off any third-party network - useful for privacy-sensitive
  sessions or non-Chromium browsers.

Deliberately lazy: the whisper model is only loaded on first use (import of
`faster_whisper` + model download can take real time/disk), so importing
this module has no cost unless a caller actually invokes transcribe().
Fails open (returns None) if faster-whisper isn't installed or inference
fails - callers should fall back to typed input, exactly like the browser
STT path already does for unsupported browsers.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

_MODEL = None  # lazy-loaded singleton


def _get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    size = os.environ.get("GYAVE_WHISPER_SIZE", "small")
    device = os.environ.get("GYAVE_WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("GYAVE_WHISPER_COMPUTE_TYPE", "int8")
    try:
        _MODEL = WhisperModel(size, device=device, compute_type=compute_type)
    except Exception:
        return None
    return _MODEL


def transcribe_file(path: str | Path, language: str = "pt") -> Optional[str]:
    """Transcribe an audio file (wav/mp3/ogg/webm - anything ffmpeg can
    read) to text. Returns None on any failure (missing dependency, bad
    audio, inference error) so callers can fail open.
    """
    model = _get_model()
    if model is None:
        return None
    try:
        segments, _ = model.transcribe(
            str(path), language=language, vad_filter=True,
            beam_size=1, temperature=0.0,
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text or None
    except Exception:
        return None


def transcribe_bytes(audio_bytes: bytes, suffix: str = ".webm", language: str = "pt") -> Optional[str]:
    """Convenience wrapper for API/upload handlers: writes bytes to a temp
    file, transcribes, cleans up.
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)
    try:
        return transcribe_file(tmp_path, language=language)
    finally:
        tmp_path.unlink(missing_ok=True)


def is_available() -> bool:
    """Cheap check for whether local Whisper STT can even be attempted,
    without paying the full model-load cost. Used by /api/health-style
    probes to report capability without loading the model.
    """
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False
