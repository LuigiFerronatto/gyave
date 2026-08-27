"""Textual TUI for GYAVE Voice Console — a premium terminal interface
styled like Gemini CLI and Copilot CLI. Act as a lightweight WebSocket
client to the local ui_server backend.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import subprocess
import time
import uuid
from pathlib import Path
import httpx
import websockets
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Select, Label, RichLog, Static, Slider
from textual.message import Message
from rich.markup import escape

from gyave.config import Config


class GyaveTUI(App):
    TITLE = "GYAVE VOICE CONSOLE"
    SUBTITLE = "Give Your Agents Voices"
    
    BINDINGS = [
        ("m", "toggle_mute", "Mute"),
        ("s", "stop_audio", "Parar Fala"),
        ("c", "copy_last", "Copiar Mensagem"),
        ("ctrl+q", "quit", "Sair"),
    ]

    DEFAULT_CSS = """
    Screen {
        background: #111216;
        color: #e3e6ed;
    }

    #left_panel {
        width: 38;
        border-right: solid #3b3f4c;
        padding: 0 2;
        background: #15171e;
    }

    #right_panel {
        padding: 0 2;
    }

    .section_title {
        color: #5f87ff;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 1;
    }

    Label {
        margin-top: 1;
        color: #a0a5b5;
    }

    Select {
        margin-bottom: 1;
    }

    Slider {
        width: 100%;
        margin-bottom: 1;
    }

    .status-idle {
        color: #8be9fd;
        text-style: bold;
    }
    
    .status-thinking {
        color: #ffb86c;
        text-style: bold;
    }
    
    .status-speaking {
        color: #bd93f9;
        text-style: bold;
    }
    
    .status-listening {
        color: #50fa7b;
        text-style: bold;
    }
    
    .status-error {
        color: #ff5555;
        text-style: bold;
    }

    #chat_log {
        height: 1fr;
        border: round #3b3f4c;
        background: #111216;
        padding: 1;
        margin-bottom: 1;
    }

    #message_input {
        dock: bottom;
        border: round #3b3f4c;
        background: #15171e;
    }

    #logs_log {
        height: 8;
        border: solid #282a36;
        background: #0b0c10;
        color: #6272a4;
        margin-top: 1;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = None
        self.backend_proc = None
        self.muted = False
        self.connected = False
        self.last_assistant_text = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left_panel"):
                yield Label("🔧 CONFIGURAÇÕES", classes="section_title")
                yield Label("Provedor (TTS):")
                yield Select([], id="provider_select", prompt="Carregando...")
                yield Label("Modelo:")
                yield Select([], id="model_select", prompt="Carregando...")
                yield Label("Voz:")
                yield Select([], id="voice_select", prompt="Carregando...")
                yield Label("Velocidade (Rate):")
                yield Slider(min=-50, max=50, step=5, value=0, id="rate_slider")
                yield Label("Volume:")
                yield Slider(min=-50, max=50, step=5, value=0, id="volume_slider")
                yield Label("Status:")
                yield Static("🔴 Desconectado", id="status_label")
                yield Label("Mudo:")
                yield Static("🔊 Ativo (Som ligado)", id="mute_label")
            with Vertical(id="right_panel"):
                yield Label("💬 CONSOLE DE CONVERSA", classes="section_title")
                yield RichLog(id="chat_log", highlight=True, markup=True)
                yield Input(placeholder="Digite sua mensagem e pressione Enter...", id="message_input")
                yield Label("🪵 LOGS DE TRANSMISSÃO")
                yield RichLog(id="logs_log", highlight=True, markup=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.chat_log = self.query_one("#chat_log", RichLog)
        self.logs_log = self.query_one("#logs_log", RichLog)
        self.status_label = self.query_one("#status_label", Static)
        self.mute_label = self.query_one("#mute_label", Static)
        self.msg_input = self.query_one("#message_input", Input)

        self.logs_log.write("[bold cyan][TUI][/bold cyan] TUI iniciada. Verificando backend...")

        self.cfg = Config.load()

        # Initialize Sliders from Config
        rate_val = 0
        if self.cfg.rate:
            try:
                rate_val = int(self.cfg.rate.replace("%", "").replace("+", ""))
            except ValueError:
                pass
        self.query_one("#rate_slider", Slider).value = rate_val

        volume_val = 0
        if self.cfg.volume:
            try:
                volume_val = int(self.cfg.volume.replace("%", "").replace("+", ""))
            except ValueError:
                pass
        self.query_one("#volume_slider", Slider).value = volume_val
        
        self.muted = self.cfg.mute
        self.mute_label.update("🔴 MUDO (Sistema Silenciado)" if self.muted else "🔊 Ativo (Som ligado)")

        # Ensure server is running
        await self.ensure_backend()
        
        # Initial loads
        await self.load_providers()

        # Connect WebSocket
        self.msg_input.focus()
        self.run_worker(self.connect_ws_loop())

    async def ensure_backend(self) -> None:
        server_running = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://127.0.0.1:8765/api/health", timeout=1.0)
                if resp.status_code == 200:
                    server_running = True
        except Exception:
            pass

        if not server_running:
            self.logs_log.write("[bold yellow][TUI][/bold yellow] Backend não encontrado. Iniciando servidor em segundo plano...")
            # Run background server in a platform-agnostic detached process
            python_bin = sys.executable or "python3"
            self.backend_proc = subprocess.Popen(
                [python_bin, "-m", "gyave", "ui", "--no-browser"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True # starts in new process group to protect from SIGINT
            )
            await asyncio.sleep(2.0)
            self.logs_log.write("[bold green][TUI][/bold green] Backend iniciado.")

    async def load_providers(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                # Load Engines
                resp = await client.get("http://127.0.0.1:8765/api/tts-providers")
                data = resp.json()
                providers = [(p["label"], p["id"]) for p in data.get("providers", []) if p.get("available")]
                
                provider_sel = self.query_one("#provider_select", Select)
                provider_sel.set_options(providers)
                if providers:
                    # Select the one from config if available
                    cfg_engine = self.cfg.engine
                    if any(p[1] == cfg_engine for p in providers):
                        provider_sel.value = cfg_engine
                    else:
                        provider_sel.value = providers[0][1]
        except Exception as exc:
            self.logs_log.write(f"[bold red][ERRO][/bold red] Falha ao carregar provedores: {escape(str(exc))}")

    async def load_voices_and_models(self, provider: str) -> None:
        try:
            async with httpx.AsyncClient() as client:
                # Load Voices
                resp = await client.get(f"http://127.0.0.1:8765/api/voices?provider={provider}")
                data = resp.json()
                voices = [(v["label"], v["id"]) for v in data.get("voices", [])]
                voice_sel = self.query_one("#voice_select", Select)
                voice_sel.set_options(voices)
                if voices:
                    cfg_voice = self.cfg.voice
                    if any(v[1] == cfg_voice for v in voices):
                        voice_sel.value = cfg_voice
                    else:
                        voice_sel.value = voices[0][1]

                # Load Models
                resp = await client.get(f"http://127.0.0.1:8765/api/models?provider={provider}")
                data = resp.json()
                models = [(m["label"], m["id"]) for m in data.get("models", [])]
                model_sel = self.query_one("#model_select", Select)
                model_sel.set_options(models)
                if models:
                    cfg_model = self.cfg.model
                    if any(m[1] == cfg_model for m in models):
                        model_sel.value = cfg_model
                    else:
                        model_sel.value = models[0][1]
        except Exception as exc:
            self.logs_log.write(f"[bold red][ERRO][/bold red] Falha ao carregar vozes/modelos para {provider}: {escape(str(exc))}")

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider_select" and event.value:
            await self.load_voices_and_models(event.value)

    async def connect_ws_loop(self) -> None:
        while True:
            try:
                self.logs_log.write("[bold cyan][WS][/bold cyan] Conectando ao WebSocket do Gyave...")
                async with websockets.connect("ws://127.0.0.1:8765/ws") as websocket:
                    self.ws = websocket
                    self.connected = True
                    self.status_label.update("🟢 Conectado (Ocioso)")
                    self.status_label.add_class("status-idle")
                    self.logs_log.write("[bold green][WS][/bold green] Conectado com sucesso.")

                    while True:
                        raw = await websocket.recv()
                        msg = json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "state":
                            val = msg.get("value")
                            self.status_label.remove_class("status-idle", "status-thinking", "status-speaking", "status-listening", "status-error")
                            self.status_label.add_class(f"status-{val}")
                            
                            state_texts = {
                                "idle": "🟢 Conectado (Ocioso)",
                                "thinking": "🤔 Pensando...",
                                "speaking": "🗣️ Falando...",
                                "listening": "🎙️ Ouvindo...",
                                "error": "🔴 Erro no servidor",
                            }
                            self.status_label.update(state_texts.get(val, f"🟢 Conectado ({val})"))
                        elif msg_type == "assistant_message":
                            text = msg.get("text", "")
                            self.last_assistant_text = text  # Save for clipboard copy!
                            self.chat_log.write(f"[bold purple]🤖 Lao:[/bold purple] {escape(text)}")
                            self.logs_log.write(f"[bold purple][LAO][/bold purple] Mensagem recebida.")
                        elif msg_type == "user_echo":
                            # already printed locally, ignore
                            pass
                        elif msg_type == "tts_skipped":
                            text = msg.get("text", "")
                            self.chat_log.write(f"[bold yellow]🔇 Sistema:[/bold yellow] {escape(text)}")
            except Exception as exc:
                self.connected = False
                self.ws = None
                self.status_label.remove_class("status-idle", "status-thinking", "status-speaking", "status-listening", "status-error")
                self.status_label.add_class("status-error")
                self.status_label.update("🔴 Desconectado")
                self.logs_log.write(f"[bold red][WS][/bold red] Erro ou desconexão: {escape(str(exc))}. Reconectando em 3s...")
                await asyncio.sleep(3.0)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message_input":
            text = event.value.strip()
            if not text:
                return

            event.input.value = ""
            self.chat_log.write(f"[bold cyan]👤 Você:[/bold cyan] {escape(text)}")

            if not self.connected or not self.ws:
                self.chat_log.write("[bold red]❌ Erro:[/bold red] Desconectado do servidor.")
                return

            # Read selected configs
            provider_sel = self.query_one("#provider_select", Select)
            voice_sel = self.query_one("#voice_select", Select)
            model_sel = self.query_one("#model_select", Select)
            rate_slider = self.query_one("#rate_slider", Slider)
            volume_slider = self.query_one("#volume_slider", Slider)

            # Format slider values as speed and volume percentages (e.g. +15%, -10%)
            rate_str = f"{int(rate_slider.value):+d}%"
            volume_str = f"{int(volume_slider.value):+d}%"

            payload = {
                "type": "user_message",
                "text": text,
                "engine": "auto",
                "voice": voice_sel.value or "",
                "tts_provider": provider_sel.value or "",
                "tts_model": model_sel.value or "auto",
                "rate": rate_str,
                "volume": volume_str,
                "mute": self.muted,
                "audio_output": "system",  # Speak directly on system speakers
            }

            try:
                await self.ws.send(json.dumps(payload))
            except Exception as exc:
                self.chat_log.write(f"[bold red]❌ Erro ao enviar:[/bold red] {escape(str(exc))}")

    def action_copy_last(self) -> None:
        if not self.last_assistant_text:
            self.logs_log.write("[bold yellow][TUI][/bold yellow] Nenhuma mensagem do assistente para copiar.")
            return
        try:
            self.app.copy_to_clipboard(self.last_assistant_text)
            self.notify("Mensagem copiada para a área de transferência!", title="Copiado", severity="information")
        except Exception as exc:
            self.logs_log.write(f"[bold red][ERRO][/bold red] Falha ao copiar mensagem: {escape(str(exc))}")

    def action_toggle_mute(self) -> None:
        self.muted = not self.muted
        self.mute_label.update("🔴 MUDO (Sistema Silenciado)" if self.muted else "🔊 Ativo (Som ligado)")
        self.logs_log.write(f"[bold yellow][TUI][/bold yellow] Mudo alternado para: {self.muted}")

    def action_stop_audio(self) -> None:
        # Run gyave stop via subprocess
        try:
            subprocess.run([sys.executable, "-m", "gyave", "stop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.logs_log.write("[bold yellow][TUI][/bold yellow] Comando STOP enviado.")
        except Exception as exc:
            self.logs_log.write(f"[bold red][ERRO][/bold red] Falha ao enviar STOP: {escape(str(exc))}")

    async def action_quit(self) -> None:
        # Kill the backend if we started it
        if self.backend_proc:
            try:
                self.backend_proc.terminate()
            except Exception:
                pass
        self.exit()


if __name__ == "__main__":
    GyaveTUI().run()
