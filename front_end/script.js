// ─── Config ────────────────────────────────────────────────────────────────────
const BACKEND_API = "/api";   // requests go through nginx same-origin proxy

// ─── DOM refs ──────────────────────────────────────────────────────────────────
const videoElement   = document.getElementById("videoElement");
const startButton    = document.getElementById("startButton");
const stopButton     = document.getElementById("stopButton");
const commentaryBtn  = document.getElementById("commentaryButton");
const commentaryDiv  = document.getElementById("commentary");
const chatMessages   = document.getElementById("chatMessages");
const chatInput      = document.getElementById("chatInput");
const sendButton     = document.getElementById("sendButton");

const voiceBox       = document.getElementById("voiceBox");
const replayBtn      = document.getElementById("replayButton");
const ttsAudio       = document.getElementById("ttsAudio");

// ─── State ─────────────────────────────────────────────────────────────────────
let mediaStream = null;
let commentaryEnabled = false;
let lastCommentary   = 0;
const COMMENTARY_INTERVAL = 30_000;
let chatHistory      = [];

// ─── Utils ─────────────────────────────────────────────────────────────────────
function clearChatMessages() {
  chatMessages.innerHTML = "";
}

function addMessage(text, isUser = false) {
  const div = document.createElement("div");
  div.className = `message ${isUser ? "user-message" : "assistant-message"}`;
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─── Chat ─────────────────────────────────────────────────────────────────────
async function sendMessage() {
  const msg = chatInput.value.trim();
  if (!msg) return;
  addMessage(msg, true);
  chatInput.value = "";

  const payload = {
    message : msg,
    history : chatHistory,
    model   : "mistral"
  };

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(`${BACKEND_API}/chat`, {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        body   : JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      chatHistory = data.history;

      // Clear and show full conversation history
      clearChatMessages();
      for (const msg of chatHistory) {
        addMessage(msg.content, msg.role === "user");
      }

      // TTS handling + UI voice box
      if (data.audio_path) {
        const lastMsg = chatHistory.at(-1);
        if (lastMsg?.content) {
          commentaryDiv.innerHTML = `🔊 ${lastMsg.content}`;
          commentaryDiv.style.display = "block";
        }

        const audioURL = data.audio_path;
        ttsAudio.src = audioURL;
        voiceBox.style.display = "block";

        try {
          await ttsAudio.play();
        } catch (err) {
          console.warn("Autoplay blocked. Use Replay button.");
        }

        replayBtn.onclick = () => {
          ttsAudio.currentTime = 0;
          ttsAudio.play();
        };
      }

      return; // success
    } catch (err) {
      console.error("Chat attempt %d failed: %s", attempt + 1, err);
      if (attempt === 2) addMessage("Sorry, I’m having trouble right now.");
      await sleep(1000 * (attempt + 1));
    }
  }
}

// ─── Screen analysis ──────────────────────────────────────────────────────────
async function analyzeScreen() {
  if (!mediaStream || !commentaryEnabled) return;

  const canvas = document.createElement("canvas");
  canvas.width  = videoElement.videoWidth;
  canvas.height = videoElement.videoHeight;
  canvas.getContext("2d").drawImage(videoElement, 0, 0);
  const imgB64 = canvas.toDataURL("image/jpeg", 0.8);

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(`${BACKEND_API}/analyze-screen`, {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        body   : JSON.stringify({ image: imgB64 })
      });
      if (!res.ok) throw new Error(await res.text());
      const { commentary } = await res.json();
      if (commentary) {
        commentaryDiv.textContent = commentary;
        commentaryDiv.style.display = "block";
      }
      return;
    } catch (err) {
      console.error("Analyze attempt %d failed: %s", attempt + 1, err);
      if (attempt === 2) {
        commentaryDiv.textContent = "Sorry, can't analyze the screen.";
        commentaryDiv.style.display = "block";
      }
      await sleep(1000 * (attempt + 1));
    }
  }
}

// ─── Screen-share controls ────────────────────────────────────────────────────
startButton.addEventListener("click", async () => {
  try {
    mediaStream = await navigator.mediaDevices.getDisplayMedia({
      video: { cursor: "always" },
      audio: false
    });
    videoElement.srcObject = mediaStream;
    videoElement.style.display = "block";

    startButton.disabled   = true;
    stopButton.disabled    = false;
    commentaryBtn.disabled = false;

    mediaStream.getVideoTracks()[0]
               .addEventListener("ended", stopSharing);

    if (commentaryEnabled) startPeriodicCommentary();
  } catch (e) {
    alert("Screen-share error: " + e.message);
  }
});

stopButton.addEventListener("click", stopSharing);

function stopSharing() {
  if (!mediaStream) return;
  mediaStream.getTracks().forEach(t => t.stop());
  mediaStream = null;
  videoElement.srcObject = null;
  videoElement.style.display = "none";
  startButton.disabled = false;
  stopButton.disabled  = commentaryBtn.disabled = true;
  commentaryDiv.style.display = "none";
  stopPeriodicCommentary();
}

// ─── Commentary toggle ────────────────────────────────────────────────────────
commentaryBtn.addEventListener("click", () => {
  commentaryEnabled = !commentaryEnabled;
  commentaryBtn.textContent = commentaryEnabled ? "Disable Commentary" : "Enable Commentary";
  if (commentaryEnabled && mediaStream) {
    startPeriodicCommentary();
    analyzeScreen();
  } else {
    stopPeriodicCommentary();
    commentaryDiv.style.display = "none";
  }
});

// ─── Chat events ──────────────────────────────────────────────────────────────
sendButton.addEventListener("click", sendMessage);
chatInput .addEventListener("keypress", e => {
  if (e.key === "Enter") sendMessage();
});

// ─── Commentary scheduler ─────────────────────────────────────────────────────
let commentaryTimer = null;
function startPeriodicCommentary() {
  stopPeriodicCommentary();
  lastCommentary = Date.now();
  commentaryTimer = setInterval(() => {
    if (Date.now() - lastCommentary >= COMMENTARY_INTERVAL) {
      analyzeScreen();
      lastCommentary = Date.now();
    }
  }, 5000);
}
function stopPeriodicCommentary() {
  clearInterval(commentaryTimer);
  commentaryTimer = null;
}

// ─── Keyboard shortcut (Ctrl/Cmd + C) ─────────────────────────────────────────
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "c" && mediaStream) {
    e.preventDefault();
    analyzeScreen();
  }
});

