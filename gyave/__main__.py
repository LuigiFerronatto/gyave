"""GYAVE CLI entrypoint.

Usage:
  gyave speak "some text"              # speak arbitrary text directly
  echo "some text" | gyave speak       # speak text from stdin (plain text)
  <hook payload json> | gyave hook copilot   # Copilot CLI agentStop hook
  <hook payload json> | gyave hook claude    # Claude Code Stop hook
  gyave test                            # play a short confirmation phrase
  gyave mute / gyave unmute              # toggle the session-wide mute flag
  gyave ui [--port=8765] [--no-browser]  # launch the Voice Console (web UI)
"""
from __future__ import annotations

import sys

from gyave import core
from gyave.config import Config, MUTE_FLAG_FILE
from gyave.adapters import read_stdin_json


def _cmd_speak(argv: list[str]) -> int:
    if argv:
        text = " ".join(argv)
    else:
        text = sys.stdin.read()
    ok = core.speak_text(text)
    return 0  # always exit 0 — never block/fail the calling agent


def _cmd_hook(argv: list[str]) -> int:
    hook_kind = argv[0] if argv else "auto"
    payload = read_stdin_json()
    core.speak_from_hook(hook_kind, payload)
    # agentStop/Stop hooks: emit no output -> "allow" (don't force another turn)
    print("{}")
    return 0


def _cmd_test(argv: list[str]) -> int:
    phrase = " ".join(argv) or "GYAVE está funcionando. Seu agente agora pode falar."
    ok = core.speak_text(phrase, Config.load())
    print("OK" if ok else "FAILED (check ~/.gyave/gyave.log)")
    return 0 if ok else 1


def _cmd_mute(_argv: list[str]) -> int:
    MUTE_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    MUTE_FLAG_FILE.touch()
    print("GYAVE muted.")
    return 0


def _cmd_unmute(_argv: list[str]) -> int:
    MUTE_FLAG_FILE.unlink(missing_ok=True)
    print("GYAVE unmuted.")
    return 0


def _cmd_ui(argv: list[str]) -> int:
    from gyave import ui_server

    port = 8765
    no_browser = "--no-browser" in argv
    for a in argv:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    print(f"[gyave] Voice Console em http://127.0.0.1:{port}  (ctrl+c para sair)")
    ui_server.run(port=port, open_browser=not no_browser)
    return 0


COMMANDS = {
    "speak": _cmd_speak,
    "hook": _cmd_hook,
    "test": _cmd_test,
    "mute": _cmd_mute,
    "unmute": _cmd_unmute,
    "ui": _cmd_ui,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    try:
        return COMMANDS[cmd](rest)
    except Exception as exc:  # fail open, always
        print(f"[gyave] internal error (ignored): {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
