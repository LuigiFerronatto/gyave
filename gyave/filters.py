"""Decides WHETHER a piece of agent text should be spoken, and cleans it up
if so. Ported/adapted from the filtering heuristics popularized by
talkback-win (Zhijing Eu), generalized to be engine-agnostic.

The philosophy: speak short, conversational replies and status updates.
Stay silent on long analysis, structured lists, code, and raw tool output —
those are meant to be read, not heard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from gyave.config import Config

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_BULLET_LINE_RE = re.compile(r"^\s*([-*•]|\d+[.)])\s+", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_URL_RE = re.compile(r"https?://\S+")
_TOOL_OUTPUT_HINTS = re.compile(
    r"(^\s*\$\s|^\s*[{\[]|^\s*[+-]{1,2}\s|Traceback \(most recent|"
    r"^\s*[\w./-]+:\d+:|exit code \d+)",
    re.MULTILINE,
)


@dataclass
class Verdict:
    speak: bool
    text: str = ""
    reason: str = ""


def _code_fence_ratio(text: str) -> float:
    if not text:
        return 0.0
    fenced = sum(len(m.group(0)) for m in _CODE_FENCE_RE.finditer(text))
    return fenced / max(len(text), 1)


def _looks_like_tool_output(text: str) -> bool:
    hits = len(_TOOL_OUTPUT_HINTS.findall(text))
    # A couple of incidental hits (e.g. one inline path) shouldn't veto a
    # normal sentence; a text dominated by them is a log/diff dump.
    return hits >= 3


def _is_code_heavy(text: str, fence_ratio: float) -> bool:
    """True only when the reply is a pure code dump, not "explanation with
    a code example" — a gap explicitly called out as a pain point in
    Null-Phnix/claude-voice's README ("the heuristic is crude and
    sometimes skips useful explanations that include code examples").
    GYAVE's version: also require the prose OUTSIDE the fences to be thin
    (not just a one-line intro like "Here's the fix:") before vetoing on
    fence ratio alone.
    """
    prose_outside = _CODE_FENCE_RE.sub("", text).strip()
    return fence_ratio > 0.4 and len(prose_outside) < 60


def strip_markdown(text: str) -> str:
    """Best-effort plain-text conversion for TTS (not a full MD parser)."""
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_BOLD_ITALIC_RE.sub(r"\2", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _URL_RE.sub("um link", text)
    text = text.replace("—", ",").replace("–", ",")
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_at_sentence(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` chars, backing up to the last
    sentence-ending punctuation found so the spoken truncation doesn't
    stop mid-word/mid-thought. Falls back to a hard character cut if no
    sentence boundary exists in range."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    for punct in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        idx = window.rfind(punct)
        if idx > limit * 0.5:  # don't cut absurdly short just to land on a boundary
            return window[: idx + 1]
    return window


def evaluate(raw_text: str, cfg: Config) -> Verdict:
    if not raw_text or not raw_text.strip():
        return Verdict(False, reason="empty")

    stripped = raw_text.strip()

    if len(stripped) > cfg.max_chars:
        # Truncate-and-speak instead of going silent (added 2026-08-26):
        # a hard skip here means ANY reply that creeps even slightly past
        # max_chars — e.g. 15794 vs. a 15000 cap — produces total silence
        # with no feedback, which just moves the "why didn't it talk?"
        # confusion to a slightly higher threshold instead of fixing it.
        # Speaking a truncated-but-real opening (up to max_chars, cut at
        # the last sentence boundary so it doesn't stop mid-word) is
        # almost always more useful than nothing. Only give up entirely
        # past `hard_max_chars` (a genuinely huge dump — a full file
        # listing, a giant diff) where even a truncated read wouldn't be
        # a a meaningful reply anymore.
        if len(stripped) > cfg.hard_max_chars:
            return Verdict(False, reason=f"too long ({len(stripped)} chars, exceeds hard cap)")
        truncated = _truncate_at_sentence(stripped, cfg.max_chars)
        stripped = truncated + " ... resposta completa disponível na tela."

    if len(_BULLET_LINE_RE.findall(stripped)) >= cfg.max_bullets:
        return Verdict(False, reason="structured list, better read than heard")

    fence_ratio = _code_fence_ratio(stripped)
    if fence_ratio > cfg.max_code_fence_ratio and _is_code_heavy(stripped, fence_ratio):
        return Verdict(False, reason="mostly code")

    if _looks_like_tool_output(stripped):
        return Verdict(False, reason="looks like raw tool/log output")

    clean = strip_markdown(stripped)
    if not clean:
        return Verdict(False, reason="nothing left after cleanup")

    if cfg.identity_prefix:
        clean = f"{cfg.identity_prefix}{clean}"

    return Verdict(True, text=clean)
