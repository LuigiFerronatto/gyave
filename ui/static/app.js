const mascot = document.getElementById("mascot");
const stateLabel = document.getElementById("stateLabel");
const log = document.getElementById("log");
const engineSelect = document.getElementById("engineSelect");
const voiceSelect = document.getElementById("voiceSelect");
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

// --- Push-to-talk via the browser's built-in Web Speech API (client-side
// STT, no server round-trip, no API key). Falls back gracefully to
// typing-only if the browser doesn't support it (e.g. Firefox).
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let recording = false;

if (SpeechRecognition) {
  recognizer = new SpeechRecognition();
  recognizer.lang = "pt-BR";
  recognizer.interimResults = true;
  recognizer.continuous = false;

  recognizer.onresult = (event) => {
    let finalText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else textInput.value = event.results[i][0].transcript;
    }
    if (finalText) {
      sendMessage(finalText);
    }
  };
  recognizer.onend = () => {
    recording = false;
    micBtn.classList.remove("recording");
  };
  recognizer.onerror = () => {
    recording = false;
    micBtn.classList.remove("recording");
  };

  micBtn.onclick = () => {
    if (recording) {
      recognizer.stop();
      return;
    }
    recording = true;
    micBtn.classList.add("recording");
    setMascotState("listening");
    recognizer.start();
  };
} else {
  micBtn.title = "Reconhecimento de voz não suportado neste navegador — use Chrome/Edge, ou digite.";
  micBtn.onclick = () => alert("Seu navegador não suporta reconhecimento de voz (Web Speech API). Use Chrome ou Edge, ou digite a mensagem.");
}
