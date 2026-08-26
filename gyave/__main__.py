"""GYAVE CLI entrypoint.

Usage:
  gyave speak "some text"              # speak arbitrary text directly
  echo "some text" | gyave speak       # speak text from stdin (plain text)
  <hook payload json> | gyave hook copilot   # Copilot CLI agentStop hook
  <hook payload json> | gyave hook claude    # Claude Code Stop hook
  <hook payload json> | gyave hook gemini    # Gemini CLI AfterAgent hook
  gyave test                            # play a short confirmation phrase
  gyave mute / gyave unmute              # toggle the session-wide mute flag
  gyave ui [--port=8765] [--no-browser]  # launch the Voice Console (web UI)
  gyave status                           # show current engine/voice/rate/mute
  gyave provider <name>                  # switch default TTS provider (persists)
  gyave voice <name>                     # switch default voice (persists)
  gyave voices [locale-prefix]           # list real edge-tts voices (e.g. "pt-")
  gyave rate <+N%|-N%>                   # set edge-tts speech rate (persists)
  gyave volume <+N%|-N%>                 # set edge-tts volume (persists)
  gyave pitch <+NHz|-NHz>                # set edge-tts pitch (persists)
  gyave doctor                           # diagnose a broken install
  gyave codex-exec "<prompt>"            # one-shot Codex CLI invoke + speak
                                          #   (Codex has no Stop-style hook —
                                          #   see docs/GYAVE.md "Codex CLI")
"""
from __future__ import annotations

import sys
from pathlib import Path

from gyave import core
from gyave.config import Config, MUTE_FLAG_FILE, save_setting
from gyave.adapters import read_stdin_json


def _cmd_speak(argv: list[str]) -> int:
    if argv:
        text = " ".join(argv)
    else:
        text = sys.stdin.read()
    ok, _reason = core.speak_text(text)
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
    ok, reason = core.speak_text(phrase, Config.load())
    print("OK" if ok else f"FAILED: {reason} (check ~/.gyave/gyave.log)")
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


def _cmd_status(_argv: list[str]) -> int:
    """`claude-voice status`-style one-glance summary of the active config."""
    cfg = Config.load()
    print(f"engine   : {cfg.engine}")
    print(f"voice    : {cfg.voice}")
    print(f"rate     : {cfg.rate}")
    print(f"volume   : {cfg.volume}")
    print(f"pitch    : {cfg.pitch}")
    print(f"muted    : {cfg.mute}")
    print(f"max_chars: {cfg.max_chars}")
    return 0


def _cmd_provider(argv: list[str]) -> int:
    """`gyave provider <name>` — switch + persist the default TTS provider,
    mirroring claude-voice's `claude-voice provider <name>`. No arg: list
    known providers.
    """
    from gyave.providers import PROVIDERS
    if not argv:
        print("Providers disponíveis:", ", ".join(PROVIDERS.keys()))
        print("Uso: gyave provider <nome>")
        return 0
    name = argv[0]
    if name not in PROVIDERS:
        print(f"Provider desconhecido: {name}. Opções: {', '.join(PROVIDERS.keys())}")
        return 1
    save_setting("engine", name)
    print(f"Provider padrão agora é: {name}")
    return 0


def _cmd_voice(argv: list[str]) -> int:
    if not argv:
        cfg = Config.load()
        print(f"Voz atual: {cfg.voice}")
        print("Uso: gyave voice <nome> (ex: pt-BR-FranciscaNeural)")
        return 0
    save_setting("voice", argv[0])
    print(f"Voz padrão agora é: {argv[0]}")
    return 0


def _cmd_voices(argv: list[str]) -> int:
    """List real available edge-tts voices (same data source as the
    `edge-tts --list-voices` CLI command from rany2/edge-tts), optionally
    filtered by locale prefix, e.g. `gyave voices pt-`.
    """
    from gyave.providers import list_edge_voices
    prefix = argv[0] if argv else None
    voices = list_edge_voices(prefix)
    if not voices:
        print("Nenhuma voz encontrada (sem rede, ou edge-tts não instalado).")
        return 1
    for v in voices:
        print(f"{v['short_name']:<32} {v['gender']:<8} {v['locale']}")
    print(f"\n{len(voices)} vozes.")
    return 0


def _cmd_rate(argv: list[str]) -> int:
    if not argv:
        print(f"Rate atual: {Config.load().rate}")
        return 0
    save_setting("rate", argv[0])
    print(f"Rate padrão agora é: {argv[0]}")
    return 0


def _cmd_volume(argv: list[str]) -> int:
    if not argv:
        print(f"Volume atual: {Config.load().volume}")
        return 0
    save_setting("volume", argv[0])
    print(f"Volume padrão agora é: {argv[0]}")
    return 0


def _cmd_pitch(argv: list[str]) -> int:
    if not argv:
        print(f"Pitch atual: {Config.load().pitch}")
        return 0
    save_setting("pitch", argv[0])
    print(f"Pitch padrão agora é: {argv[0]}")
    return 0


def _cmd_doctor(_argv: list[str]) -> int:
    """`claude-voice doctor`-style install diagnostic."""
    import shutil
    ok = True
    print("=== GYAVE doctor ===")

    def check(label, condition, hint=""):
        nonlocal ok
        mark = "OK " if condition else "!! "
        print(f"{mark}{label}" + (f"  ({hint})" if hint and not condition else ""))
        if not condition:
            ok = False

    try:
        import edge_tts  # noqa: F401
        check("edge_tts instalado", True)
    except ImportError:
        check("edge_tts instalado", False, "pip install edge-tts")

    player = shutil.which("ffplay") or shutil.which("paplay") or shutil.which("aplay") or shutil.which("afplay")
    check("player de áudio no PATH", bool(player), "instale ffplay/paplay/aplay/afplay")

    try:
        import faster_whisper  # noqa: F401
        check("faster-whisper (STT local) instalado", True)
    except ImportError:
        check("faster-whisper (STT local) instalado", False, "opcional: pip install faster-whisper")

    import os
    check("OPENAI_API_KEY definido (opcional)", bool(os.environ.get("OPENAI_API_KEY")))
    check("AWS creds configuradas (opcional)", bool(os.environ.get("AWS_ACCESS_KEY_ID") or Path.home().joinpath(".aws/credentials").exists()))

    cfg = Config.load()
    check(f"config carregada (engine={cfg.engine}, voice={cfg.voice})", True)

    print("\nTudo certo!" if ok else "\nAlguns itens opcionais faltando, mas o núcleo (edge+player) é o que importa.")
    return 0


def _cmd_codex_exec(argv: list[str]) -> int:
    """One-shot wrapper for Codex CLI: `codex exec` (headless, one-shot
    mode) has no interactive Stop-style hook the way Claude Code/Copilot
    do — confirmed via ZhijingEu/talkback-win-openai-codex's README ("Codex
    uses TOML config, not JSON... the TUI hook surface is not exposed").
    GYAVE's answer is the same shape as that dedicated fork: shell out to
    `codex exec --json`, extract the final agent message, and speak it —
    see docs/GYAVE.md "Codex CLI" for the full rationale.
    """
    import json
    import shutil
    import subprocess

    if not argv:
        print("Uso: gyave codex-exec \"<prompt>\"")
        return 1
    prompt = " ".join(argv)
    if not shutil.which("codex"):
        print("[gyave] binário `codex` não encontrado no PATH.", file=sys.stderr)
        return 1
    try:
        proc = subprocess.run(
            ["codex", "exec", "--json", prompt],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:
        print(f"[gyave] falha ao rodar codex exec: {exc}", file=sys.stderr)
        return 1

    text = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        item = d.get("item") or {}
        if d.get("type") == "item.completed" and item.get("type") == "agent_message":
            content = item.get("text")
            if isinstance(content, str) and content.strip():
                text = content
        # Fallback shapes seen in other codex versions
        msg = d.get("msg") or {}
        content = msg.get("message") or msg.get("last_agent_message")
        if isinstance(content, str) and content.strip():
            text = content
    if not text:
        text = proc.stdout.strip() or "(sem resposta do codex)"

    print(text)
    core.speak_text(text)
    return proc.returncode


COMMANDS = {
    "speak": _cmd_speak,
    "hook": _cmd_hook,
    "test": _cmd_test,
    "mute": _cmd_mute,
    "unmute": _cmd_unmute,
    "ui": _cmd_ui,
    "status": _cmd_status,
    "provider": _cmd_provider,
    "voice": _cmd_voice,
    "voices": _cmd_voices,
    "rate": _cmd_rate,
    "volume": _cmd_volume,
    "pitch": _cmd_pitch,
    "doctor": _cmd_doctor,
    "codex-exec": _cmd_codex_exec,
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
