"""Configuration for GYAVE, loaded from env vars with a JSON file fallback.

Precedence: environment variable > ~/.gyave/config.json > built-in default.
Kept deliberately simple (no config framework) — same philosophy as
talkback-win's env-var-only design, since this is a small utility, not a
product.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

GYAVE_HOME = Path(os.environ.get("GYAVE_HOME", Path.home() / ".gyave"))
CONFIG_FILE = GYAVE_HOME / "config.json"
LOG_FILE = GYAVE_HOME / "gyave.log"
MUTE_FLAG_FILE = GYAVE_HOME / ".mute"


def _load_json_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _get(key: str, default: str, json_cfg: dict) -> str:
    env_key = f"GYAVE_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    if key in json_cfg:
        return str(json_cfg[key])
    return default


@dataclass
class Config:
    engine: str = "edge"          # edge | espeak | say | silent | auto
    voice: str = "pt-BR-AntonioNeural"
    rate: str = "+0%"             # edge-tts rate adjustment, e.g. "+15%"
    max_chars: int = 800
    max_bullets: int = 3
    max_code_fence_ratio: float = 0.4
    mute: bool = False
    player: str = "auto"          # auto | ffplay | aplay | paplay
    identity_prefix: str = ""     # optional spoken prefix, e.g. "LAO diz: "
    log_enabled: bool = True

    @classmethod
    def load(cls) -> "Config":
        j = _load_json_config()
        muted = MUTE_FLAG_FILE.exists() or _get("mute", "0", j) in ("1", "true", "True")
        return cls(
            engine=_get("engine", "edge", j),
            voice=_get("voice", "pt-BR-AntonioNeural", j),
            rate=_get("rate", "+0%", j),
            max_chars=int(_get("max_chars", "800", j)),
            max_bullets=int(_get("max_bullets", "3", j)),
            max_code_fence_ratio=float(_get("max_code_fence_ratio", "0.4", j)),
            mute=muted,
            player=_get("player", "auto", j),
            identity_prefix=_get("identity_prefix", "", j),
            log_enabled=_get("log", "1", j) not in ("0", "false", "False"),
        )
