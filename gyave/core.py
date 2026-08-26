"""Core orchestration: given raw text (or a hook payload), decide whether to
speak, and do it. Designed to never raise — a GYAVE failure must never break
the calling agent's turn.
"""
from __future__ import annotations

import datetime as _dt
import sys

from gyave import adapters, filters, providers
from gyave.config import Config, GYAVE_HOME, LOG_FILE


def _log(msg: str, cfg: Config) -> None:
    if not cfg.log_enabled:
        return
    try:
        GYAVE_HOME.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().isoformat(timespec="seconds")
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def speak_text(raw_text: str, cfg: Config | None = None) -> bool:
    """Main entry point: filter + speak arbitrary text. Returns True if audio
    was actually played.
    """
    cfg = cfg or Config.load()

    if cfg.mute:
        _log("muted, skipping", cfg)
        return False

    verdict = filters.evaluate(raw_text, cfg)
    if not verdict.speak:
        _log(f"skip: {verdict.reason}", cfg)
        return False

    ok, engine_used = providers.speak(verdict.text, cfg)
    _log(f"{'spoke' if ok else 'FAILED'} via {engine_used}: {verdict.text[:120]!r}", cfg)
    return ok


def speak_from_hook(hook_kind: str, payload: dict, cfg: Config | None = None) -> bool:
    """Entry point for CLI hook adapters (agentStop / Stop). Resolves the
    text from the transcript referenced in the payload, then delegates to
    speak_text.
    """
    cfg = cfg or Config.load()
    text = adapters.resolve_text(hook_kind, payload)
    if not text:
        _log(f"hook={hook_kind}: no resolvable text in payload", cfg)
        return False
    return speak_text(text, cfg)
