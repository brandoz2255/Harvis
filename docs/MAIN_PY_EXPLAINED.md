# `python_back_end/main.py` Explained

This document provides a technical overview of `main.py`, the central orchestrator for the Harvis backend. This FastAPI application serves as the bridge between the frontend (Next.js), the Database (PostgreSQL), and the AI Models (Ollama, Whisper, Chatterbox TTS).

## 🏗️ High-Level Architecture

The file follows a **modular monolith** pattern. While `main.py` contains the core routes, it delegates heavy logic to specialized modules (like `model_manager.py`, `chat_history_module.py`, and `vibecoding/`).

**Key Responsibilities:**
1.  **API Gateway:** Handles HTTP and WebSocket requests from the frontend.
2.  **Resource Management:** Manages Database connections and GPU VRAM.
3.  **Orchestration:** Chains together STT (Speech-to-Text), LLM (Inference), and TTS (Text-to-Speech) into coherent workflows.
4.  **Streaming:** Manages Server-Sent Events (SSE) to provide real-time feedback to the UI.

---

## 🚀 1. Application Startup (`lifespan`)

The `lifespan` function is the first thing that runs. It ensures resources are ready before the app accepts traffic.

*   **Database Pool:** Creates an `asyncpg` connection pool to PostgreSQL. This is more efficient than opening a new connection for every request.
*   **Module Initialization:**
    *   Initializes `ChatHistoryManager`.
    *   Checks for Model Caches (HuggingFace/Whisper).
    *   Initializes RAG (Retrieval Augmented Generation) vectors.
    *   Initializes the Vibe Coding file system tables.

---

## 🔐 2. Authentication & Security

*   **JWT (JSON Web Tokens):** The `get_current_user` dependency checks for a valid `access_token` in cookies or headers.
*   **Optimized Auth:** Uses `auth_optimized.py` for faster user lookups using the DB pool.
*   **CORS:** Configured to allow requests from the frontend containers (`frontend`, `nginx-proxy`) and localhost.

---

## 💬 3. Core Chat Pipeline (`/api/chat`)

This is the most complex endpoint. It uses **SSE (Server-Sent Events)** to stream text tokens and status updates to the client.

**The Pipeline:**
1.  **Input Processing:** Accepts text and file attachments (extracts text from files).
2.  **Auto-Research Check:** Detects if the user is asking for fresh info (e.g., "latest news"). If so, redirects to the Research Agent.
3.  **Context Loading:** Fetches recent chat history from the DB using `ChatHistoryManager`.
4.  **LLM Inference (Ollama):**
    *   Streams tokens chunk-by-chunk.
    *   **Heartbeats:** Sends keep-alive signals to preventing Nginx/Browser timeouts during long "thinking" pauses.
    *   **Reasoning Extraction:** Separates `<think>` tags (from reasoning models like DeepSeek-R1) so the UI can display them efficiently.
5.  **History Persistence:** Saves the User prompt and Assistant response to Postgres.
6.  **TTS Generation:**
    *   If not `text_only`, it calls `safe_generate_speech_optimized`.
    *   Returns a link to the generated `.wav` file in the final JSON packet.

---

## 🎙️ 4. Voice Interaction (`/api/mic-chat`)

Handles the "Talk to Harvis" feature.

1.  **Upload:** Receives a raw audio file (blob).
2.  **STT (Whisper):** Transcribes audio to text using `transcribe_with_whisper_optimized`.
    *   *Optimization:* Can unload TTS models to make room in VRAM for Whisper.
3.  **LLM:** Sends transcribed text to the Chat pipeline.
4.  **TTS:** Converts the LLM response back to audio.
5.  **Response:** Returns: `Transcription` (User) + `Text Response` (AI) + `Audio Path` (AI Voice).

---

## 🖼️ 5. Vision (`/api/vision-chat`)

Handles image analysis using Multi-modal models (like LLaVA, Moondream).

*   **Input:** Receives text + Base64 encoded images.
*   **Processing:** Converts images to format Ollama accepts.
*   **Streaming:** Uses the same SSE heartbeat mechanism as Chat to ensure large images don't cause timeouts.

---

## 🧠 6. Model Management (The "VRAM Brain")

This is unique to Harvis. It allows running complex AI on consumer hardware (e.g., 8GB VRAM) by swapping models.

*   **Endpoints:** `/api/models/unload`, `/api/models/status`.
*   **Logic:**
    *   If the user asks for Vision, it unloads TTS/Whisper.
    *   If the user asks for Voice, it loads Whisper, transcribes, then unloads it to load the LLM.
    *   Controlled by the `low_vram` flag sent from the frontend.

---

## 🧪 7. Research & Vibe Coding

*   **Research (`/api/research-chat`):** Connects to `agent_research.py`. Performs web searches, scrapes content, and synthesizes an answer with citations.
*   **Vibe Coding:** Routes are imported from `vibecoding.commands`. This allows the AI to write files, run terminal commands, and manage Docker containers.

---

## ⚙️ Key Configurations

*   **`MAX_RESPONSE_SIZE`:** Limits the AI output (default 100k chars) to prevent infinite loops or memory crashes.
*   **`HEARTBEAT_INTERVAL`:** (10s) Frequency of keep-alive signals sent during long processing tasks.

## 🛠️ Recent Changes (Summary)

1.  **Removed n8n:** All code related to n8n automation has been stripped out to simplify the architecture.
2.  **Added Heartbeats:** `run_tts_with_heartbeats` and `run_stt_with_heartbeats` were added to fix timeouts during voice generation and transcription.
3.  **Fixed Vision:** Switched Vision chat to use the robust SSE streaming protocol.
