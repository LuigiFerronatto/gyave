"""Per-CLI adapters: extract "the text the agent just said" from whatever
each host CLI's hook payload gives us. This is the ONLY place that should
know about a specific CLI's transcript format — everything else in GYAVE
(filters, providers) is CLI-agnostic on purpose.

Supported today:
  * GitHub Copilot CLI `agentStop` hook — payload has `transcriptPath`
    pointing at `~/.copilot/session-state/<id>/events.jsonl`; the last
    `assistant.message` event's `data.content` is the spoken text.
  * Claude Code `Stop` hook — payload has `transcript_path`/`transcriptPath`
    pointing at a JSONL transcript where assistant turns look like
    `{"type": "assistant", "message": {"content": [{"type": "text", ...}]}}`.
  * Direct text — used by anything that already has the string in hand
    (e.g. lao_core/engine_router.py after a subprocess invoke()), passed via
    `--text` or plain stdin.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _last_matching(lines_iter, predicate, extract):
    result = None
    for line in lines_iter:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if predicate(d):
            val = extract(d)
            if val:
                result = val
    return result


def extract_from_copilot_transcript(transcript_path: str) -> str | None:
    p = Path(transcript_path).expanduser()
    if not p.exists():
        return None
    with p.open(encoding="utf-8", errors="replace") as fh:
        return _last_matching(
            fh,
            lambda d: d.get("type") == "assistant.message",
            lambda d: (d.get("data") or {}).get("content"),
        )


def extract_from_claude_transcript(transcript_path: str) -> str | None:
    p = Path(transcript_path).expanduser()
    if not p.exists():
        return None

    def extract(d):
        msg = d.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            return "\n".join(t for t in texts if t)
        return None

    with p.open(encoding="utf-8", errors="replace") as fh:
        return _last_matching(fh, lambda d: d.get("type") == "assistant", extract)


def resolve_text(hook_kind: str, payload: dict) -> str | None:
    """hook_kind: 'copilot' | 'claude' | 'auto'. Returns the text to speak,
    or None if nothing could be resolved (fail open — caller just skips).
    """
    transcript_path = (
        payload.get("transcriptPath")
        or payload.get("transcript_path")
    )
    if not transcript_path:
        return None

    tries = []
    if hook_kind in ("copilot", "auto"):
        tries.append(extract_from_copilot_transcript)
    if hook_kind in ("claude", "auto"):
        tries.append(extract_from_claude_transcript)
    if hook_kind == "auto":
        # try the other order too, cheap and side-effect free
        tries = [extract_from_copilot_transcript, extract_from_claude_transcript]

    for fn in tries:
        try:
            text = fn(transcript_path)
        except Exception:
            text = None
        if text:
            return text
    return None


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}
