<div align="center">

# 🗣️ GYAVE
### **G**ive **Y**our **A**gents **V**oic**E**s

**The universal, CLI-agnostic voice layer for AI coding agents.**
One install. Any CLI. A real voice.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows*-lightgrey)](#platform-notes)
[![No API key required](https://img.shields.io/badge/TTS-no%20API%20key%20needed-success)](#-tts-providers)

*Claude Code. Copilot CLI. Gemini CLI. Codex. Grok. Antigravity. OpenCode.*
*Seven engines, one voice layer — pick your agent, GYAVE gives it a mouth.*

</div>

---

## 🎯 Why GYAVE exists

Every modern CLI coding agent can **listen** (voice input, dictation, `/voice`
modes). Almost none of them can **talk back**. You're left staring at a wall
of scrolling text, reading status updates you could've just *heard* while
your hands were on something else — a keyboard shortcut, a coffee cup, a
second monitor.

GYAVE closes that gap — for **any** CLI agent, not just one vendor's.

- 🆓 **Free by default.** Neural-quality TTS via Microsoft Edge's
  Read-Aloud backend (`edge-tts`) — no API key, no credit card, one `pip install`.
- 🔌 **Plug into any CLI.** Native hook narration for Claude Code & Copilot
  CLI, plus a turn-based Voice Console that works with *any* CLI that
  accepts a headless prompt — which today means all seven engines above.
- 🖥️ **A real interface, not just a script.** The **GYAVE Voice Console**
  is a local web app: pick your engine, pick your voice, click a mic
  button, watch a mascot react, hear the reply.
- 🧰 **Pluggable providers.** Ships with a free/no-key default and clean
  seams to drop in OpenAI TTS, AWS Polly, or local Whisper STT the moment
  you need paid-tier quality or full offline privacy.
- 🏠 **Lives at `~/.gyave`, not inside any one repo.** Install once,
  reuse across every project and every CLI on your machine.

---

## ⚡ Quick start

```bash
git clone https://github.com/LuigiFerronatto/gyave ~/.gyave
cd ~/.gyave && bash install.sh
```

That's it. `install.sh` creates an isolated venv, installs the free TTS
stack, symlinks the `gyave` command onto your `PATH`, and offers to wire
up a hook for Claude Code / Copilot CLI if it finds one installed.

```bash
gyave test          # hear "GYAVE is working" — confirms your setup
gyave ui             # opens the Voice Console at http://127.0.0.1:8765
```

---

## 🖥️ The Voice Console

<div align="center">
<em>Pick a CLI engine → talk (or type) → the agent responds → GYAVE speaks it → the mascot reacts.</em>
</div>

```
   ┌──────────────┐        WebSocket       ┌───────────────────────┐
   │   Browser    │ ─────────────────────▶ │   GYAVE Voice Console  │
   │  (mascot +   │ ◀───────────────────── │      (FastAPI)         │
   │  mic + chat) │      streamed state     └──────────┬────────────┘
   └──────────────┘                                    │
                                                         ▼
                                    engine_router.invoke(engine, prompt)
                                                         │
                       ┌───────────────┬─────────────────┼─────────────────┬───────────┐
                       ▼               ▼                 ▼                 ▼           ▼
                   claude          copilot            gemini            codex     grok · agy · opencode
```

- 🎙️ **Push-to-talk mic input** via the browser's native Web Speech API
  (zero install), with an optional **local Whisper STT fallback**
  (`/api/stt`) for browsers without it, or fully-offline/privacy-sensitive
  sessions.
- 🐙 **Engine picker** — every engine `lao_core.engine_router` knows about
  shows up automatically, with live availability badges.
- 🔊 **Voice picker** — swap TTS voice/provider without restarting anything.
- 🎭 **A mascot that reacts**: `idle → thinking → listening → speaking →
  error`, so you always know what state the agent is in at a glance.
- 🔇 **One-click mute** that interrupts playback **mid-sentence**, not
  just before the next reply.
- 🩺 **`/api/health`** liveness probe for scripting/monitoring.

Launch it: `gyave ui` (add `--no-browser` to skip auto-opening a tab,
`--port=NNNN` to change the port).

---

## 🔌 Works with every major CLI agent

| Engine | Native hook (passive narration) | Headless invoke (Voice Console) |
|---|:---:|---|
| **Claude Code** | ✅ `Stop` hook | `claude -p PROMPT --dangerously-skip-permissions` |
| **GitHub Copilot CLI** | ✅ `agentStop` hook | `copilot -p PROMPT --allow-all-tools --no-color` |
| **Gemini CLI** | — | `gemini -p PROMPT --approval-mode yolo` |
| **Codex (OpenAI)** | — | `codex exec --full-auto PROMPT` |
| **Grok CLI (xAI)** | — | `grok -p PROMPT --always-approve` |
| **Antigravity (`agy`, Google)** | — | `agy -p PROMPT --dangerously-skip-permissions` |
| **OpenCode** | — | `opencode run PROMPT --auto` |

Only Claude Code and Copilot CLI expose a native `Stop`-style hook today —
GYAVE speaks their responses automatically, with zero per-turn wiring.
Every other engine gets its voice through the **Voice Console's turn-based
invoke path**, which needs nothing more than a headless prompt-in/text-out
mode — meaning **any future CLI that can run one-shot is a one-line
addition away** from having a voice too.

---

## 🎤 TTS providers

| Provider | Cost | API key? | Quality | Notes |
|---|---|:---:|---|---|
| **Edge (`edge-tts`)** *(default)* | Free | ❌ | Neural, 300+ voices | Unofficial Microsoft endpoint, network round-trip |
| **OpenAI TTS** | Paid | ✅ `OPENAI_API_KEY` | Neural | `GYAVE_ENGINE=openai`, `GYAVE_OPENAI_VOICE` |
| **AWS Polly** | Paid | ✅ AWS creds | Neural | `GYAVE_ENGINE=polly`, `GYAVE_POLLY_VOICE` (default `Camila`, pt-BR) |
| **espeak-ng / spd-say** | Free | ❌ | Robotic | Fully offline fallback |
| **silent** | Free | ❌ | — | Logs instead of speaking; dry-run/CI-safe |

All providers speak **sentence-by-sentence**, not as one giant blob — this
means shorter time-to-first-audio on long replies, and `gyave mute` can
interrupt a reply mid-playback instead of only blocking the next one.

Paid providers are strictly opt-in — GYAVE will **never** silently start
billing a cloud account. The default `auto` fallback chain only ever tries
`edge → espeak → silent`.

## 🎧 STT (speech-to-text) options

- **Browser Web Speech API** *(default, Voice Console)* — zero install,
  free, Chrome/Edge only.
- **Local Whisper (`faster-whisper`)** *(optional, `/api/stt`)* — fully
  offline once the model is cached, works in any browser, ideal for
  privacy-sensitive sessions. Install with `pip install ".[whisper]"`.

---

## 🪝 Native hook narration (Claude Code & Copilot CLI)

For the two CLIs that support it, GYAVE also plugs in as a **passive**
narrator — no console, no button, it just speaks every qualifying
response as it happens:

```jsonc
// ~/.copilot/hooks/gyave.json
{"hooks": {"agentStop": [{"matcher": "", "hooks": [
  {"type": "command", "command": "~/.gyave/bin/gyave hook copilot"}
]}]}}
```

A smart filter decides what's worth speaking (skips long analytical
output, bulleted lists, code-heavy replies, and raw tool-output-looking
text) — so what gets read aloud is exactly what you'd want spoken: short
conversational replies and status updates.

---

## 🧩 Architecture

```
gyave/
├── config.py     # env-var-first config, no config framework
├── filters.py     # "is this worth speaking?" heuristics + markdown stripping
├── providers.py   # TTS backends: edge · openai · polly · espeak · silent
├── stt.py         # optional local Whisper STT
├── adapters.py    # per-CLI transcript parsers (the ONLY CLI-specific code)
├── core.py        # orchestration — never raises, fails open
├── ui_server.py    # FastAPI backend for the Voice Console
├── tui.py         # Premium Terminal User Interface (TUI)
└── __main__.py    # `gyave speak|hook|test|mute|unmute|stop|ui|tui`
```

Adding a new CLI only ever touches **one file** on each integration path:
`adapters.py` for hook narration, and your engine-router's own
`ENGINES`/invoke-builder for Voice Console support — GYAVE's core
(filters, providers, orchestration) stays 100% CLI-agnostic.

---

## ⚙️ Configuration

Everything is an environment variable (or `~/.gyave/config.json`) — no
config framework, no YAML to learn:

| Variable | Default | Meaning |
|---|---|---|
| `GYAVE_ENGINE` | `edge` | `edge` \| `openai` \| `polly` \| `elevenlabs` \| `fishaudio` \| `espeak` \| `auto` \| `silent` |
| `GYAVE_VOICE` | `pt-BR-AntonioNeural` | edge-tts voice ID |
| `GYAVE_RATE` | `+0%` | edge-tts speech rate adjustment |
| `GYAVE_VOLUME` | `+0%` | edge-tts volume adjustment (e.g. `-20%`) |
| `GYAVE_PITCH` | `+0Hz` | edge-tts pitch adjustment (e.g. `-10Hz`) |
| `GYAVE_MAX_CHARS` | `800` | Skip speaking anything longer |
| `GYAVE_MAX_BULLETS` | `3` | Skip if 3+ bullet points detected |
| `GYAVE_MUTE` | `0` | `1` mutes globally for the session |
| `GYAVE_OPENAI_VOICE` | `alloy` | Used when `GYAVE_ENGINE=openai` |
| `GYAVE_POLLY_VOICE` | `Camila` | Used when `GYAVE_ENGINE=polly` |
| `GYAVE_ELEVENLABS_VOICE` | `JBFqnCBsd6RMkjVDRZzb` | Used when `GYAVE_ENGINE=elevenlabs` |
| `GYAVE_ELEVENLABS_MODEL` | `eleven_multilingual_v2` | Used when `GYAVE_ENGINE=elevenlabs` |
| `GYAVE_FISHAUDIO_VOICE` | `9a9cf47702da476aa4629e2506d4a857` | Used when `GYAVE_ENGINE=fishaudio` |
| `GYAVE_FISHAUDIO_MODEL` | `s2.1-pro` | Used when `GYAVE_ENGINE=fishaudio` |
| `GYAVE_LAO_REPO` | *(auto-detected)* | Path to a repo exposing `lao_core.engine_router`, for the Voice Console |
| `OPENAI_API_KEY` | *(none)* | Enables `GYAVE_ENGINE=openai` TTS + OpenAI Whisper STT |
| `ELEVENLABS_API_KEY` | *(none)* | Enables `GYAVE_ENGINE=elevenlabs` TTS |
| `FISH_API_KEY` | *(none)* | Enables `GYAVE_ENGINE=fishaudio` TTS |

**Quick CLI commands** (mirroring `claude-voice`'s UX — each persists to
`~/.gyave/config.json` so you don't need to export the env var every
shell):

```bash
gyave status              # current engine/voice/rate/volume/pitch/mute
gyave provider openai     # switch + persist default TTS provider
gyave voice pt-BR-FranciscaNeural
gyave model eleven_v3     # switch + persist default TTS model (OpenAI/ElevenLabs/FishAudio)
gyave voices pt-          # list REAL available edge-tts voices for a locale
gyave rate +15%
gyave volume -10%
gyave pitch +5Hz
gyave mute / unmute       # toggle global mute (persists)
gyave stop                # stop active audio playback immediately without muting
gyave ui                  # launch the Voice Console Web UI
gyave tui                 # launch the beautiful, interactive Terminal User Interface (TUI)
gyave doctor              # diagnose a broken install (deps, player, creds)
```

**`.env` file support**: drop credentials into `~/.gyave/.env` (already
gitignored, `chmod 600` recommended) instead of exporting them in every
shell — same pattern as VoiceMode's `~/.voicemode/voicemode.env`:

```
OPENAI_API_KEY=sk-...
```

Loaded automatically on every `gyave` invocation and by the Voice Console
server; real exported env vars still always take precedence.

---

## 📦 Platform notes

Built and tested on Linux. Audio playback auto-detects `ffplay` / `paplay`
/ `aplay` / `afplay` (macOS) — no hardcoded player. Windows support is
untested but the architecture (subprocess-based playback, no OS-specific
APIs in the core) should port cleanly; contributions welcome.

---

## 🙏 Acknowledgements & inspiration

GYAVE started from auditing three community projects and pulling the
ideas that generalized best across *any* CLI, not just one:

- [`talkback-win`](https://github.com/ZhijingEu/talkback-win) — the
  original "give your CLI agent a voice via a Stop hook" idea, and the
  UTF-8/cp1252 stdin-decoding gotcha GYAVE deliberately avoids from day one.
- **Agent Vibes** — cross-platform, multi-provider TTS for CLI agents;
  validated that a provider-pluggable design (not a single hardcoded
  engine) was the right call.
- [`ricardotrevisan/ai-voice-agent`](https://github.com/ricardotrevisan/ai-voice-agent) —
  a local-first Whisper→LLM→Polly voice agent; contributed the
  sentence-chunked/interruptible TTS playback pattern and the `/health`
  liveness-endpoint convention used here, plus the OpenAI TTS / AWS Polly
  / local Whisper provider options in GYAVE's pool.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

<div align="center">

**GYAVE** — because your agent already listens. Now it can talk back.

</div>
