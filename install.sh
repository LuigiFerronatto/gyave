#!/usr/bin/env bash
# GYAVE installer — creates an isolated venv, installs the free TTS stack,
# symlinks the `gyave` command onto PATH, and offers to wire up a hook for
# any host CLI that supports one (Claude Code / Copilot CLI today).
set -euo pipefail

GYAVE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$GYAVE_HOME"

echo "📦 GYAVE installer — installing into: $GYAVE_HOME"

if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 not found on PATH. Install Python 3.9+ first." >&2
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "🐍 Creating virtualenv..."
    python3 -m venv venv
fi

echo "📥 Installing GYAVE + free TTS dependencies (edge-tts, fastapi, uvicorn, websockets)..."
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -e .

echo ""
read -r -p "🔊 Also install optional paid/offline providers (OpenAI TTS, AWS Polly, local Whisper STT)? [y/N] " optional
if [[ "$optional" =~ ^[Yy]$ ]]; then
    venv/bin/pip install --quiet -e ".[all]"
    echo "✅ Optional providers installed. Configure GYAVE_ENGINE=openai|polly and the matching credentials to use them."
fi

mkdir -p "$HOME/.local/bin"
ln -sf "$GYAVE_HOME/bin/gyave" "$HOME/.local/bin/gyave"
echo "🔗 Symlinked gyave -> $HOME/.local/bin/gyave"

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "⚠️  $HOME/.local/bin is not on your PATH — add it to your shell profile (e.g. ~/.bashrc):"
       echo '     export PATH="$HOME/.local/bin:$PATH"' ;;
esac

echo ""
echo "🧪 Running self-test..."
if "$GYAVE_HOME/bin/gyave" test; then
    echo "✅ GYAVE is working!"
else
    echo "⚠️  Self-test did not confirm audio playback — check that ffplay/paplay/aplay is installed."
fi

echo ""
if command -v copilot >/dev/null 2>&1; then
    read -r -p "🪝 Install the Copilot CLI 'agentStop' hook so responses are spoken automatically? [y/N] " hook
    if [[ "$hook" =~ ^[Yy]$ ]]; then
        mkdir -p "$HOME/.copilot/hooks"
        cat > "$HOME/.copilot/hooks/gyave.json" << EOF
{"hooks": {"agentStop": [{"matcher": "", "hooks": [
  {"type": "command", "command": "$GYAVE_HOME/bin/gyave hook copilot"}
]}]}}
EOF
        echo "✅ Installed ~/.copilot/hooks/gyave.json — restart Copilot CLI to pick it up."
    fi
fi

echo ""
echo "🎉 Done! Try:"
echo "   gyave test    # confirm audio"
echo "   gyave ui      # launch the Voice Console"
