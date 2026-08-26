"""GYAVE — Give Your Agents Voices.

A tiny, CLI-agnostic TTS harness that lets any coding-agent CLI (Claude Code,
GitHub Copilot CLI, Gemini CLI, or a raw subprocess invocation) talk back.

Design goals:
  * No API key required by default (uses Microsoft Edge's free TTS endpoint).
  * Works fully offline as a degraded fallback (espeak-ng / spd-say / silent-log).
  * One core engine, thin per-CLI adapters — never fork the filtering/speak logic.
  * Safe by construction: never speaks code, secrets-shaped text, or long walls
    of text; always fails open (never blocks or crashes the calling agent).
"""

__version__ = "0.1.0"
