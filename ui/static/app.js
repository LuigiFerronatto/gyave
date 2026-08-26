const mascot = document.getElementById("mascot");
const stateLabel = document.getElementById("stateLabel");
const log = document.getElementById("log");
const engineSelect = document.getElementById("engineSelect");
const voiceSelect = document.getElementById("voiceSelect");
const sttModeSelect = document.getElementById("sttModeSelect");
const muteBtn = document.getElementById("muteBtn");
const micBtn = document.getElementById("micBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");

let muted = false;
let ws;

const STATE_LABELS = {
  idle: "pronto",
  thinking: "pensando…",
  speaking: "falando…",
  listening: "ouvindo…",
  error: "algo deu errado",
};

function setMascotState(state) {
  mascot.className = state;
  mascot.src = `/static/mascots/${state === "idle" ? "idle" : state}.png`;
  stateLabel.textContent = STATE_LABELS[state] || state;
}

function addBubble(role, text, isError) {
  const div = document.createElement("div");
  div.className = `bubble ${role}${isError ? " error" : ""}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "state") {
      setMascotState(msg.value);
    } else if (msg.type === "user_echo") {
      // already added locally on send; ignore to avoid duplicate bubble
    } else if (msg.type === "assistant_message") {
      addBubble("lao", msg.text, !!msg.error);
    } else if (msg.type === "tts_skipped") {
      addBubble("system", `🔇 ${msg.text}`, false);
    }
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
}
connectWs();

async function loadEngines() {
  const res = await fetch("/api/engines");
  const data = await res.json();
  (data.engines || []).forEach((e) => {
    const opt = document.createElement("option");
    opt.value = e.id;
    opt.textContent = `${e.id}${e.available ? "" : " (indisponível)"}`;
    engineSelect.appendChild(opt);
  });
}

async function loadVoices() {
  const res = await fetch("/api/voices");
  const data = await res.json();
  (data.voices || []).forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v.id;
    opt.textContent = v.label;
    voiceSelect.appendChild(opt);
  });
}

loadEngines();
loadVoices();

function sendMessage(text) {
  if (!text.trim()) return;
  addBubble("user", text);
  ws.send(JSON.stringify({
    type: "user_message",
    text,
    engine: engineSelect.value,
    voice: voiceSelect.value,
    mute: muted,
  }));
  textInput.value = "";
}

sendBtn.onclick = () => sendMessage(textInput.value);
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage(textInput.value);
});

muteBtn.onclick = () => {
  muted = !muted;
  muteBtn.classList.toggle("muted", muted);
  muteBtn.textContent = muted ? "🔇" : "🔈";
};

// --- STT: three interchangeable capture modes, selected via sttModeSelect
// ("webspeech" | "local" | "openai"). webspeech uses the browser's built-in
// SpeechRecognition (zero network round-trip beyond Chrome's own). The
// other two record audio with MediaRecorder and POST the blob to
// /api/stt?provider=local|openai (gyave/stt.py — faster-whisper locally,
// or OpenAI's whisper-1 API), which is what unlocks Firefox support and
// the offline/no-Web-Speech-API case entirely (see docs/GYAVE.md).
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let recording = false;
let mediaRecorder = null;
let mediaChunks = [];

function currentSttMode() {
  return sttModeSelect ? sttModeSelect.value : "webspeech";
}

function setupWebSpeech() {
  if (!SpeechRecognition) return null;
  const r = new SpeechRecognition();
  r.lang = "pt-BR";
  r.interimResults = true;
  r.continuous = false;
  r.onresult = (event) => {
    let finalText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else textInput.value = event.results[i][0].transcript;
    }
    if (finalText) sendMessage(finalText);
  };
  r.onend = () => { recording = false; micBtn.classList.remove("recording"); setMascotState("idle"); };
  r.onerror = () => { recording = false; micBtn.classList.remove("recording"); setMascotState("idle"); };
  return r;
}
recognizer = setupWebSpeech();

async function startMediaRecorderCapture(provider) {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) mediaChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      setMascotState("thinking");
      const blob = new Blob(mediaChunks, { type: "audio/webm" });
      const form = new FormData();
      form.append("file", blob, "clip.webm");
      form.append("provider", provider);
      try {
        const res = await fetch("/api/stt", { method: "POST", body: form });
        const data = await res.json();
        if (data.text) {
          sendMessage(data.text);
        } else {
          addBubble("system", `🔇 Não consegui transcrever (${data.error || "sem áudio reconhecido"}).`, false);
          setMascotState("idle");
        }
      } catch (err) {
        addBubble("system", `🔇 Falha ao transcrever: ${err}`, false);
        setMascotState("idle");
      }
    };
    mediaRecorder.start();
    recording = true;
    micBtn.classList.add("recording");
    setMascotState("listening");
  } catch (err) {
    addBubble("system", `🔇 Não consegui acessar o microfone: ${err}`, false);
  }
}

function stopMediaRecorderCapture() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  recording = false;
  micBtn.classList.remove("recording");
}

micBtn.onclick = () => {
  const mode = currentSttMode();
  if (mode === "webspeech") {
    if (!recognizer) {
      alert("Seu navegador não suporta Web Speech API. Escolha 'Whisper local' ou 'Whisper OpenAI' no seletor de captura, ou digite a mensagem.");
      return;
    }
    if (recording) { recognizer.stop(); return; }
    recording = true;
    micBtn.classList.add("recording");
    setMascotState("listening");
    recognizer.start();
    return;
  }
  // local | openai — MediaRecorder-based capture, click to start, click again to stop
  if (recording) {
    stopMediaRecorderCapture();
  } else {
    startMediaRecorderCapture(mode);
  }
};
