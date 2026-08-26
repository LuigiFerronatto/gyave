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
ENV_FILE = GYAVE_HOME / ".env"


def _load_dotenv() -> None:
    """Load ~/.gyave/.env into os.environ (only keys not already set —
    real exported env vars always win). Minimal hand-rolled parser (no
    python-dotenv dependency) so credentials like OPENAI_API_KEY /
    AWS_* / GYAVE_POLLY_VOICE can live in a gitignored file instead of
    needing to be exported in every shell (mirrors VoiceMode's
    ~/.voicemode/voicemode.env pattern from kumaran srinivasan's article).
    Fails open — a malformed .env is silently ignored, never raised.
    """
    if not ENV_FILE.exists():
        return
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


_load_dotenv()


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
    engine: str = "edge"          # edge | espeak | openai | polly | silent | auto
    voice: str = "pt-BR-AntonioNeural"
    rate: str = "+0%"             # edge-tts rate adjustment, e.g. "+15%"
    volume: str = "+0%"           # edge-tts volume adjustment, e.g. "-20%" (from edge-tts README)
    pitch: str = "+0Hz"           # edge-tts pitch adjustment, e.g. "-10Hz" (from edge-tts README)
    max_chars: int = 15000
    max_bullets: int = 12
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
            volume=_get("volume", "+0%", j),
            pitch=_get("pitch", "+0Hz", j),
            max_chars=int(_get("max_chars", "15000", j)),
            max_bullets=int(_get("max_bullets", "12", j)),
            max_code_fence_ratio=float(_get("max_code_fence_ratio", "0.4", j)),
            mute=muted,
            player=_get("player", "auto", j),
            identity_prefix=_get("identity_prefix", "", j),
            log_enabled=_get("log", "1", j) not in ("0", "false", "False"),
        )


def save_setting(key: str, value: str) -> None:
    """Persist a single setting to ~/.gyave/config.json (merges with any
    existing file). Mirrors claude-voice's `claude-voice provider <name>` /
    `claude-voice voice <name>` pattern: a quick CLI command that switches
    the *default* provider/voice for future runs, without needing an env
    var exported in every shell. Env vars still always win at read time
    (see `_get()` precedence) — this only changes the on-disk fallback.
    """
    j = _load_json_config()
    j[key] = value
    GYAVE_HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(j, indent=2, ensure_ascii=False), encoding="utf-8")
