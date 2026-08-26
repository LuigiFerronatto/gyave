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


def evaluate(raw_text: str, cfg: Config) -> Verdict:
    if not raw_text or not raw_text.strip():
        return Verdict(False, reason="empty")

    stripped = raw_text.strip()

    if len(stripped) > cfg.max_chars:
        return Verdict(False, reason=f"too long ({len(stripped)} chars)")

    if len(_BULLET_LINE_RE.findall(stripped)) >= cfg.max_bullets:
        return Verdict(False, reason="structured list, better read than heard")

    if _code_fence_ratio(stripped) > cfg.max_code_fence_ratio:
        return Verdict(False, reason="mostly code")

    if _looks_like_tool_output(stripped):
        return Verdict(False, reason="looks like raw tool/log output")

    clean = strip_markdown(stripped)
    if not clean:
        return Verdict(False, reason="nothing left after cleanup")

    if cfg.identity_prefix:
        clean = f"{cfg.identity_prefix}{clean}"

    return Verdict(True, text=clean)
