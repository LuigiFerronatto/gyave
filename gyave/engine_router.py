"""Self-contained, project-agnostic multi-CLI engine router for GYAVE.

Ported from `lao_core/engine_router.py` (the lab-autonomous-officer repo)
on 2026-08-26, specifically to remove GYAVE's hard dependency on that
repo being checked out at a fixed path. Before this module existed,
`ui_server.py` did `sys.path.insert(0, DEFAULT_REPO)` and
`from lao_core import engine_router` — meaning the Voice Console only
worked for LAO's own repo, and speaking with ANY other project (or the
same repo from a different clone path) silently failed or required an
env var pointing back at that one repo. GYAVE's whole premise is being
CLI/project-agnostic (see docs/GYAVE.md), so hardcoding one project's
internal module was a design bug, not a shortcut.

This module intentionally keeps only what GYAVE's Voice Console/hooks
actually need: the engine registry, availability/health checks, and
argv-building for a one-shot headless invoke. It deliberately drops
lao_core's task-type routing heuristics and supervised_invoke() —
those are LAO-pipeline-specific orchestration concerns, out of scope
for a generic voice harness. If a project wants LAO's richer routing,
it can still keep using its own `lao_core.engine_router` directly and
just pass GYAVE plain text/hook payloads.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from gyave.config import GYAVE_HOME

HEALTH_FILE = GYAVE_HOME / ".engine_health.json"
COOLDOWN_SECONDS = int(os.getenv("GYAVE_ENGINE_COOLDOWN_SECONDS", str(30 * 60)))

# Same engine set GYAVE's hooks/adapters already know how to speak for,
# plus every headless CLI GYAVE has been wired to at least once. Keep
# this list and adapters.py's supported-hook-kinds list roughly in sync.
ENGINES = {
    "claude": {"binary": "claude"},
    "copilot": {"binary": "copilot"},
    "gemini": {"binary": "gemini"},
    "opencode": {"binary": "opencode"},
    "codex": {"binary": "codex"},
    "grok": {"binary": "grok"},
    "agy": {"binary": "agy"},
}

_RISK_SIGNAL_RE = re.compile(
    r"credit balance|insufficient_quota|quota exceeded|resource_exhausted|"
    r"rate.?limit|429|payment required|billing",
    re.IGNORECASE,
)


def is_risk_signal(stderr_text: str) -> bool:
    return bool(stderr_text and _RISK_SIGNAL_RE.search(stderr_text))


def _load_health() -> dict:
    if not HEALTH_FILE.exists():
        return {}
    try:
        return json.loads(HEALTH_FILE.read_text())
    except Exception:
        return {}


def _save_health(health: dict) -> None:
    GYAVE_HOME.mkdir(parents=True, exist_ok=True)
    tmp = HEALTH_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(health, indent=2))
    os.replace(tmp, HEALTH_FILE)


def record_failure(engine: str, reason: str) -> None:
    health = _load_health()
    health[engine] = {
        "unhealthy_until": time.time() + COOLDOWN_SECONDS,
        "reason": reason[:300],
        "recorded_at": time.time(),
    }
    _save_health(health)


def _is_healthy(engine: str) -> bool:
    entry = _load_health().get(engine)
    if not entry:
        return True
    return time.time() >= entry.get("unhealthy_until", 0)


def is_available(engine: str) -> bool:
    spec = ENGINES.get(engine)
    if not spec:
        return False
    if not shutil.which(spec["binary"]):
        return False
    return _is_healthy(engine)


def pick_engine(preferred: Optional[str], priority_order: list) -> str:
    if preferred and preferred in ENGINES and is_available(preferred):
        return preferred
    for engine in priority_order:
        if is_available(engine):
            return engine
    return preferred if preferred in ENGINES else (priority_order[0] if priority_order else "claude")


def binary_for(engine: str) -> str:
    return ENGINES.get(engine, {}).get("binary", engine)


def build_invoke_command(engine: str, prompt: str, model: Optional[str] = None) -> list:
    """Minimal headless invocation argv for `engine` — deliberately
    permissive (yolo/auto-approve flags), matching lao_core's shape 1:1
    so behavior doesn't change for the LAO repo itself. Only run this
    against a project/cwd you already trust, same caveat as upstream."""
    binary = binary_for(engine)
    if engine == "claude":
        cmd = [binary, "-p", prompt, "--dangerously-skip-permissions"]
    elif engine == "gemini":
        cmd = [binary, "-p", prompt, "--approval-mode", "yolo"]
    elif engine == "opencode":
        cmd = [binary, "run", prompt, "--auto"]
        if model:
            cmd += ["--model", model]
        return cmd
    elif engine == "codex":
        cmd = [binary, "exec", "--full-auto", prompt]
    elif engine == "grok":
        cmd = [binary, "-p", prompt, "--always-approve"]
    elif engine == "agy":
        cmd = [binary, "-p", prompt, "--dangerously-skip-permissions"]
    else:  # copilot (and unknown engines fall through to copilot's shape)
        cmd = [binary, "-p", prompt, "--allow-all-tools", "--no-color"]
    if model:
        cmd += ["--model", model]
    return cmd
