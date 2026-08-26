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
    model: str = "auto"           # generic model setting, e.g. "eleven_v3"
    rate: str = "+0%"             # edge-tts rate adjustment, e.g. "+15%"
    volume: str = "+0%"           # edge-tts volume adjustment, e.g. "-20%" (from edge-tts README)
    pitch: str = "+0Hz"           # edge-tts pitch adjustment, e.g. "-10Hz" (from edge-tts README)
    max_chars: int = 25000
    hard_max_chars: int = 40000   # past this, even a truncated read isn't worth it — stay silent
    max_bullets: int = 99
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
            model=_get("model", "auto", j),
            rate=_get("rate", "+0%", j),
            volume=_get("volume", "+0%", j),
            pitch=_get("pitch", "+0Hz", j),
            max_chars=int(_get("max_chars", "15000", j)),
            hard_max_chars=int(_get("hard_max_chars", "40000", j)),
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


ALIASES_FILE = GYAVE_HOME / "aliases.json"

BUILTIN_ALIASES = {
    "lao": {"id": "bdb4986093f8403d8dad0858c0628aa1", "provider": "fishaudio", "friendly_name": "Lao / Rick & Morty"},
    "picapau": {"id": "5160b0e8ca854d7e94403b2500ee582b", "provider": "fishaudio", "friendly_name": "Pica Pau"},
    "mordecai": {"id": "03715d7c27cc4c95849ef3957c9ef46c", "provider": "fishaudio", "friendly_name": "Mordecai"},
    "bonner": {"id": "7d172aacf0154382a7cf02f6a540878d", "provider": "fishaudio", "friendly_name": "William Bonner"},
    "jarvis": {"id": "a5b93aeddcc948c19ea04f0afe9d178c", "provider": "fishaudio", "friendly_name": "Jarvis"},
    "mentalista": {"id": "1a975db6f1be40f4bed2bcc5e495301d", "provider": "fishaudio", "friendly_name": "Mentalista"},
}


def load_aliases() -> dict:
    aliases = BUILTIN_ALIASES.copy()
    if ALIASES_FILE.exists():
        try:
            custom = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
            aliases.update(custom)
        except Exception:
            pass
    return aliases


def get_alias(name: str) -> dict | None:
    return load_aliases().get(name.lower().strip())


def save_alias(name: str, voice_id: str, provider: str, friendly_name: str = "") -> None:
    name = name.lower().strip()
    custom = {}
    if ALIASES_FILE.exists():
        try:
            custom = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    custom[name] = {
        "id": voice_id,
        "provider": provider,
        "friendly_name": friendly_name or name.capitalize(),
    }
    GYAVE_HOME.mkdir(parents=True, exist_ok=True)
    ALIASES_FILE.write_text(json.dumps(custom, indent=2, ensure_ascii=False), encoding="utf-8")
