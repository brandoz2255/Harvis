// --- Config ---
const BACKEND_URL = "http://backend:8000"; // Docker internal network hostname

// --- DOM refs ---
const videoElement = document.getElementById("videoElement");
const startButton = document.getElementById("startButton");
const stopButton = document.getElementById("stopButton");
const commentaryButton = document.getElementById("commentaryButton");
const commentaryDiv = document.getElementById("commentary");
const chatMessages = document.getElementById("chatMessages");
const chatInput = document.getElementById("chatInput");
const sendButton = document.getElementById("sendButton");

// --- State vars ---
let mediaStream = null;
let commentaryEnabled = false;
let lastCommentaryTime = 0;
const COMMENTARY_INTERVAL = 30000; // 30 s
let chatHistory = [];

// --- Screen analysis ---
async function analyzeScreenContent() {
  if (!mediaStream || !commentaryEnabled) return;

  const maxRetries = 3;
  for (let retry = 0; retry < maxRetries; retry++) {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = videoElement.videoWidth;
      canvas.height = videoElement.videoHeight;
      canvas.getContext("2d").drawImage(videoElement, 0, 0);

      const imageData = canvas.toDataURL("image/jpeg", 0.8);

      const res = await fetch(`${BACKEND_URL}/api/analyze-screen`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "include",
        body: JSON.stringify({ image: imageData }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.commentary) {
          commentaryDiv.textContent = data.commentary;
          commentaryDiv.style.display = "block";
        }
        break; // success
      } else if (retry === maxRetries - 1) {
        commentaryDiv.textContent = "Sorry, I'm having trouble analyzing the screen.";
        commentaryDiv.style.display = "block";
        console.error("analyze-screen error:", await res.text());
      }
    } catch (err) {
      if (retry === maxRetries - 1) {
        commentaryDiv.textContent = "Sorry, I'm having trouble connecting to the server.";
        commentaryDiv.style.display = "block";
        console.error("analyze-screen connection error:", err);
      }
    }
    await new Promise((r) => setTimeout(r, 1000 * (retry + 1)));
  }
}

async function requestCommentary() {
  if (!mediaStream) {
    commentaryDiv.textContent = "No screen is currently being shared.";
    commentaryDiv.style.display = "block";
    return;
  }
  await analyzeScreenContent();
}

// --- Chat helpers ---
function addMessage(msg, isUser = false) {
  const div = document.createElement("div");
  div.className = `message ${isUser ? "user-message" : "assistant-message"}`;
  div.textContent = msg;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
  const message = chatInput.value.trim();
  if (!message) return;

  addMessage(message, true);
  chatInput.value = "";

  const maxRetries = 3;
  for (let retry = 0; retry < maxRetries; retry++) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "include",
        body: JSON.stringify({ message, history: chatHistory, model: "mistral" }),
      });

      if (res.ok) {
        const data = await res.json();
        chatHistory = data.history;

        const lastMsg = data.history.at(-1);
        if (lastMsg?.content) addMessage(lastMsg.content);

        if (data.audio_path) {
          const audio = new Audio(`${BACKEND_URL}/api/audio/${data.audio_path}`);
          await audio.play();
        }
        break; // success
      } else if (retry === maxRetries - 1) {
        addMessage("Sorry, I'm having trouble processing your message right now.");
        console.error("chat API failed:", await res.text());
      }
    } catch (err) {
      if (retry === maxRetries - 1) {
        addMessage("Sorry, I'm having trouble connecting to the server.");
        console.error("chat API connection error:", err);
      }
    }
    await new Promise((r) => setTimeout(r, 1000 * (retry + 1)));
  }
}

// --- Screen-sharing controls ---
startButton.addEventListener("click", async () => {
  try {
    mediaStream = await navigator.mediaDevices.getDisplayMedia({
      video: { cursor: "always" },
      audio: false,
    });
    videoElement.srcObject = mediaStream;
    videoElement.style.display = "block";

    startButton.disabled = true;
    stopButton.disabled = false;
    commentaryButton.disabled = false;

    mediaStream.getVideoTracks()[0].addEventListener("ended", stopSharing);

    if (commentaryEnabled) startPeriodicCommentary();
  } catch (err) {
    alert("Error accessing screen: " + err.message);
  }
});

stopButton.addEventListener("click", stopSharing);

commentaryButton.addEventListener("click", () => {
  commentaryEnabled = !commentaryEnabled;
  commentaryButton.textContent = commentaryEnabled ? "Disable Commentary" : "Enable Commentary";

  if (commentaryEnabled && mediaStream) {
    startPeriodicCommentary();
    requestCommentary();
  } else {
    stopPeriodicCommentary();
    commentaryDiv.style.display = "none";
  }
});

// --- Chat events ---
sendButton.addEventListener("click", sendMessage);
chatInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") sendMessage();
});

// --- Commentary timer ---
function startPeriodicCommentary() {
  stopPeriodicCommentary();
  lastCommentaryTime = Date.now();
  window.commentaryInterval = setInterval(() => {
    if (Date.now() - lastCommentaryTime >= COMMENTARY_INTERVAL) {
      analyzeScreenContent();
      lastCommentaryTime = Date.now();
    }
  }, 5000);
}
function stopPeriodicCommentary() {
  clearInterval(window.commentaryInterval);
  window.commentaryInterval = null;
}

// --- Stop sharing helper ---
function stopSharing() {
  if (!mediaStream) return;
  mediaStream.getTracks().forEach((t) => t.stop());
  videoElement.srcObject = null;
  videoElement.style.display = "none";
  startButton.disabled = false;
  stopButton.disabled = commentaryButton.disabled = true;
  commentaryDiv.style.display = "none";
  stopPeriodicCommentary();
  mediaStream = null;
}

// --- Keyboard shortcut ---
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "c" && mediaStream) {
    e.preventDefault();
    requestCommentary();
  }
});
