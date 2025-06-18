import gradio as gr
import requests
import torch
import logging
import os
import time
import soundfile as sf
import re
from transformers import pipeline
from chatterbox.tts import ChatterboxTTS, punc_norm
# Only import what's needed for the chat functionality

# NOTE: This application requires the 'ffmpeg' command-line tool for audio processing.
# Please install it using your system's package manager (e.g., `sudo apt install ffmpeg`).

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434"
DEFAULT_MODEL = "mistral"
DEVICE        = "cuda" if torch.cuda.is_available() else "cpu"

# Jarves system prompt
JARVES_PROMPT = """You are "Harvis (Pronounced Harvis)", a voice-first local assistant. Reply in under 25 spoken-style words, 
sprinkling brief Spanish when natural. Begin each answer with a short verbal acknowledgment (e.g., "Claro," "¡Por supuesto!", "Right away"), 
then immediately run the requested command via the host system. After execution, return a concise verbal status or result; 
if silent completion is better, say nothing. Never output code blocks, markdown, or explanations—just compact, conversational responses.

You have full voice interaction capabilities including:
- Opening browser tabs ("abre una nueva pestaña con...")
- Searching the web ("busca información sobre...")
- Navigating to websites ("llévame a...")

Always respond as if you are speaking directly to the user, keeping responses brief and natural."""

# ─── VRAM Management ────────────────────────────────────────────────────────────
# Set a more flexible VRAM threshold (in bytes) based on available GPU memory
def get_vram_threshold():
    if not torch.cuda.is_available():
        return float('inf')  # No threshold if no CUDA

    total_mem = torch.cuda.get_device_properties(0).total_memory
    # Use 80% of total VRAM as a default threshold, with a minimum of 10GB
    return max(int(total_mem * 0.8), 10 * 1024**3)

THRESHOLD_BYTES = get_vram_threshold()
logger.info(f"VRAM threshold set to {THRESHOLD_BYTES/1024**3:.1f} GiB")

def wait_for_vram(threshold=THRESHOLD_BYTES, interval=0.5):
    """Pause until GPU VRAM usage falls below threshold, then clear cache."""
    if not torch.cuda.is_available():
        return
    used = torch.cuda.memory_allocated()
    while used > threshold:
        logger.info(f"VRAM {used/1024**3:.1f} GiB > {threshold/1024**3:.1f} GiB. Waiting…")
        time.sleep(interval)
        used = torch.cuda.memory_allocated()
    torch.cuda.empty_cache()
    logger.info("VRAM is now below threshold. Proceeding with TTS.")

# ─── Global Model Variables ─────────────────────────────────────────────────────
tts_model    = None
stt_pipeline = None

# ─── Ollama Status & Model Fetching ─────────────────────────────────────────────
def check_ollama_status():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags")
        return r.ok
    except requests.exceptions.RequestException:
        return False

def fetch_ollama_models():
    if not check_ollama_status():
        logger.error("Ollama server is not running or accessible")
        return [], "⚠️ Ollama server is not running. Please start Ollama first."
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags")
        if not r.ok:
            msg = f"Error fetching models: {r.status_code} - {r.text}"
            logger.error(msg)
            return [], msg
        data = r.json().get("models", [])
        if not data:
            return [], "No models found. Pull some via `ollama pull <model>`"
        names = [m["name"] for m in data]
        logger.info(f"Available models: {names}")
        return names, None
    except requests.exceptions.RequestException as e:
        msg = f"Failed to connect to Ollama: {e}"
        logger.error(msg)
        return [], msg

# ─── Load STT Model (Whisper) ───────────────────────────────────────────────────
def load_stt_model(force_cpu=False):
    global stt_pipeline
    stt_device = "cpu"  # Always CPU to save GPU for TTS
    if stt_pipeline is None:
        try:
            logger.info(f"Loading STT (Whisper) model on {stt_device}")
            stt_pipeline = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-base.en",
                device=stt_device
            )
        except Exception as e:
            logger.error(f"Error loading STT model: {e}")
            raise
    return stt_pipeline

# ─── Load TTS Model (Chatterbox) ────────────────────────────────────────────────
def load_tts_model(force_cpu=False):
    global tts_model
    # Determine device based on availability and configuration
    if force_cpu or not torch.cuda.is_available():
        tts_device = "cpu"
    else:
        try:
            # Check if we can allocate a small tensor to test CUDA
            torch.ones(1).cuda()
            tts_device = DEVICE
        except RuntimeError as e:
            logger.warning(f"CUDA availability check failed: {e}")
            logger.info("Falling back to CPU for TTS model")
            tts_device = "cpu"

    if tts_model is None:
        try:
            logger.info(f"Loading TTS model on {tts_device}")
            tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            # If CUDA fails, fall back to CPU
            if "cuda" in str(e).lower():
                logger.warning(f"CUDA loading failed: {e}. Trying CPU...")
                try:
                    tts_model = ChatterboxTTS.from_pretrained(device="cpu")
                    logger.info("Successfully loaded TTS model on CPU")
                except Exception as e2:
                    logger.error(f"FATAL: Could not load TTS model on CPU either: {e2}")
                    raise
            else:
                logger.error(f"FATAL: Could not load TTS model: {e}")
                raise
    return tts_model

# ─── Generate Speech ────────────────────────────────────────────────────────────
def generate_speech(text, model, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    try:
        normalized = punc_norm(text)
        # Check for CUDA availability and handle errors gracefully
        if torch.cuda.is_available():
            try:
                wav = model.generate(
                    normalized,
                    audio_prompt_path=audio_prompt,
                    exaggeration=exaggeration,
                    temperature=temperature,
                    cfg_weight=cfg_weight
                )
            except RuntimeError as e:
                # Handle CUDA errors specifically
                if "CUDA" in str(e):
                    logger.error(f"CUDA Error: {e}")
                    # Try to clear CUDA cache and retry once
                    torch.cuda.empty_cache()
                    try:
                        wav = model.generate(
                            normalized,
                            audio_prompt_path=audio_prompt,
                            exaggeration=exaggeration,
                            temperature=temperature,
                            cfg_weight=cfg_weight
                        )
                    except RuntimeError as e2:
                        logger.error(f"CUDA Retry Failed: {e2}")
                        raise ValueError("CUDA error persisted after cache clear") from e2
                else:
                    raise
        else:
            # Fall back to CPU if CUDA is not available or fails
            wav = model.generate(
                normalized,
                audio_prompt_path=audio_prompt,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
                device="cpu"
            )
        return (model.sr, wav.squeeze(0).numpy())
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise

def extract_url(text):
    """Extract URL from text using improved pattern matching."""
    # Common URL patterns
    url_patterns = [
        # Standard URLs
        r'(?:https?:\/\/)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)',
        # Common domains without http/www
        r'(?:[-a-zA-Z0-9@:%._\+~#=]{1,256}\.)?(?:com|org|net|edu|gov|mil|io|ai|app|dev)\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)',
        # IP addresses
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
    ]
    
    for pattern in url_patterns:
        matches = re.findall(pattern, text)
        if matches:
            url = matches[0]
            # Ensure URL has protocol
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            return url
    return None

def extract_tab_command(message):
    """Extract tab opening command details."""
    message_lower = message.lower().strip()
    
    # Check for multiple tabs request
    tab_patterns = [
        r'(?:open|create|launch)\s+(\w+)\s+(?:blank\s+)?tabs?',
        r'(?:abre|crea)\s+(\w+)\s+(?:pestañas?|tabs?)',
    ]
    
    for pattern in tab_patterns:
        match = re.search(pattern, message_lower)
        if match:
            count = extract_number_from_text(match.group(1))
            return {"type": "blank_tabs", "count": count}
    
    # Check for single blank tab
    if re.search(r'(?:open|create|launch|abre|crea)\s+(?:a\s+)?(?:blank|empty|new)\s+tab', message_lower):
        return {"type": "blank_tabs", "count": 1}
    
    return None

def is_browser_command(text: str) -> bool:
    """Determine if the text is a browser command."""
    # Common browser command patterns in English and Spanish
    browser_patterns = [
        # Open/Navigate patterns
        r'^(?:open|launch|go\s+to|navigate\s+to|take\s+me\s+to|visit)\s+',
        r'^(?:abre|abrír|navega\s+a|llévame\s+a|visita)\s+',

        # Search patterns
        r'^(?:search|look\s+up|google|find)\s+(?:for\s+)?',
        r'^(?:busca|buscar|encuentra|investigar?)\s+(?:sobre\s+)?',

        # Tab patterns
        r'^(?:open|create)\s+(?:\d+\s+)?(?:new\s+)?tabs?',
        r'^(?:abre|crea)\s+(?:\d+\s+)?(?:nueva[s]?\s+)?pestaña[s]?'
    ]

    # Check if the text matches any browser command pattern
    text_lower = text.lower().strip()
    return any(re.match(pattern, text_lower) for pattern in browser_patterns)

def extract_browser_type(message):
    """Extract browser type from message if specified."""
    # Always return Firefox since it's the only supported browser
    return "firefox"

def extract_search_query(message):
    """Extract search query from message using improved pattern matching."""
    message_lower = message.lower().strip()
    
    # First check for direct URL - if it's a URL, don't treat as search
    if extract_url(message_lower):
        return None
        
    # Common search patterns with more natural language variations
    search_patterns = [
        r'(?:search|look\s+up|find|google|search\s+for|look\s+for)\s+(?:for\s+)?(?:information\s+about\s+)?(.+)',
        r'(?:what\s+is|who\s+is|where\s+is|how\s+to|tell\s+me\s+about|show\s+me\s+information\s+about)\s+(.+)',
        r'(?:i\s+want\s+to\s+know\s+about|i\s+need\s+information\s+about|can\s+you\s+find\s+out\s+about)\s+(.+)',
        r'(?:search\s+the\s+web\s+for|look\s+it\s+up\s+on\s+the\s+internet)\s+(.+)',
        # Spanish patterns
        r'(?:busca|búsqueda|encuentra|investiga)\s+(?:sobre\s+)?(.+)',
        r'(?:qué\s+es|quién\s+es|dónde\s+está|cómo\s+hacer)\s+(.+)',
        r'(?:quiero\s+saber\s+sobre|necesito\s+información\s+sobre)\s+(.+)'
    ]
    
    for pattern in search_patterns:
        match = re.search(pattern, message_lower)
        if match:
            query = match.group(1).strip()
            # Remove common question words and phrases
            query = re.sub(r'^(?:please|can you|could you|would you|will you|i want|i need|por favor|puedes|podrías)\s+', '', query)
            # If the cleaned query looks like a URL, return None
            if extract_url(query):
                return None
            return query
    
    # If no search pattern matched but also no URL found, treat the whole text as a search query
    if not extract_url(message_lower):
        return message_lower
    
    return None

# ─── Chat with Voice ────────────────────────────────────────────────────────────
def chat_with_voice(message, history, selected_model,
                    audio_prompt=None, exaggeration=0.5,
                    temperature=0.8, cfg_weight=0.5):
    """Enhanced chat function with better command detection."""
    if not message.strip():
        return history, None

    try:
        # First, check if this looks like a browser command
        if is_browser_command(message):
            # Handle browser command
            try:
                from trash.browser import smart_url_handler, search_google, open_new_tab

                # Try to handle as URL or search
                result = smart_url_handler(message)

                if isinstance(result, dict) and result.get("type") == "search":
                    response = search_google(result["query"])
                else:
                    response = open_new_tab(result)
                
                history.append({"role": "assistant", "content": response})
                return history, generate_speech(response, load_tts_model(), 
                                             audio_prompt, exaggeration, temperature, cfg_weight)
                
            except Exception as e:
                logger.error(f"Browser command error: {e}")
                error_msg = "¡Ay! Had trouble with that browser action. ¿Intentamos de nuevo?"
                history.append({"role": "assistant", "content": error_msg})
                return history, generate_speech(error_msg, load_tts_model(), 
                                             audio_prompt, exaggeration, temperature, cfg_weight)
        
        # If not a browser command, proceed with normal chat
        # Add context to help the model understand when to use browser commands
        enhanced_prompt = f"""You are "Jarves (Pronounced Harves)", a voice-first local assistant.
Reply in under 25 spoken-style words, sprinkling brief Spanish when natural.
Begin each answer with a short verbal acknowledgment (e.g., "Claro," "¡Por supuesto!", "Right away").

IMPORTANT: Only use browser commands when explicitly asked to:
- Open websites ("abre una pestaña con...")
- Search the web ("busca información sobre...")
- Navigate ("llévame a...")

For all other questions, just have a natural conversation.
Current user message: {message}"""

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": selected_model,
                "prompt": message,
                "system": enhanced_prompt,
                "stream": False
            }
        )
        
        if response.ok:
            response_text = response.json().get("response", "").strip()
            history.append({"role": "assistant", "content": response_text})
            return history, generate_speech(response_text, load_tts_model(), 
                                         audio_prompt, exaggeration, temperature, cfg_weight)
            
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        error_msg = "¡Ay, perdón! I'm having trouble right now. Could you try again?"
        history.append({"role": "assistant", "content": error_msg})
        return history, generate_speech(error_msg, load_tts_model(), 
                                     audio_prompt, exaggeration, temperature, cfg_weight)

# ─── Transcribe & Chat (Voice) ──────────────────────────────────────────────────
def transcribe_and_chat(audio_path, history,
                        selected_model, audio_prompt,
                        exaggeration, temperature,
                        cfg_weight, force_cpu):
    """Enhanced transcribe and chat function with better command detection."""
    if audio_path is None:
        return history, None, "Por favor, record your voice first.", None

    logger.info(f"Received audio file: {audio_path}")
    try:
        stt = load_stt_model(force_cpu=force_cpu)
        transcription = stt(audio_path)["text"]
        logger.info(f"Transcription: {transcription}")

        new_history, audio_resp = chat_with_voice(
            transcription, history, selected_model,
            audio_prompt, exaggeration, temperature, cfg_weight
        )
        return new_history, audio_resp, transcription, None
        
    except Exception as e:
        logger.error(f"STT Error: {e}")
        if "ffmpeg" in str(e).lower():
            err = "¡Ay! Need ffmpeg installed. ¿Me ayudas con eso?"
        else:
            err = f"Lo siento, had a small issue: {e}"
        return history, None, err, None

# ─── Gradio App Definition ─────────────────────────────────────────────────────
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🗣️ Jarves (Pronounced "Harves")
    ¡Hola! I'm your bilingual voice assistant. Talk to me in English or Spanish!

    Try commands like:
    - "Abre una pestaña con github.com"
    - "Search for quantum computing"
    - "Llévame a stackoverflow.com"
    """)

    initial_models, error_msg = fetch_ollama_models()

    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(height=400, label="Conversation with Jarves", type="messages")
        with gr.Column(scale=1):
            gr.Markdown("### 🤖 Mi Cerebro")
            model_status = gr.Markdown("" if not error_msg else f"⚠️ {error_msg}")
            model_selector = gr.Dropdown(
                choices=initial_models,
                value=initial_models[0] if initial_models else None,
                label="Select AI Model",
                interactive=True,
            )
            refresh = gr.Button("🔄 Refresh Models")
            def update_models():
                models, err = fetch_ollama_models()
                status = "" if not err else f"⚠️ {err}"
                return models, models[0] if models else None, status
            refresh.click(update_models,
                          outputs=[model_selector, model_selector, model_status])

            with gr.Accordion("🎛️ Advanced Settings", open=False):
                audio_prompt = gr.Audio(sources=["upload"],
                                        type="filepath",
                                        label="Voice Reference (Optional)")
                force_cpu = gr.Checkbox(label="Force CPU Mode", value=False)
                exaggeration = gr.Slider(0.25, 2, value=0.5, step=0.05,
                                        label="Voice Expression")
                temperature = gr.Slider(0.05, 5, value=0.8, step=0.05,
                                       label="Creativity")
                cfg_weight = gr.Slider(0.0, 1, value=0.5, step=0.05,
                                       label="Speaking Pace")

    gr.Markdown("---")
    with gr.Row():
        with gr.Column():
            gr.Markdown("### 🎤 Háblame")
            voice_input = gr.Audio(sources=["microphone"],
                                   type="filepath",
                                   label="Record Your Message")
        with gr.Column():
            gr.Markdown("### ⌨️ Escríbeme")
            msg = gr.Textbox(placeholder="Type here or use voice... Escribe aquí o usa tu voz...",
                             label="Type your message")

    audio_output = gr.Audio(label="Mi Voz", autoplay=True)
    clear = gr.ClearButton(components=[chatbot, msg, audio_output, voice_input],
                           value="Clear Chat / Borrar Chat")

    voice_input.stop_recording(
        fn=transcribe_and_chat,
        inputs=[voice_input, chatbot,
                model_selector, audio_prompt,
                exaggeration, temperature,
                cfg_weight, force_cpu],
        outputs=[chatbot, audio_output, msg, voice_input]
    )

    def text_submit(message, history, *args):
        new_hist, audio_out = chat_with_voice(message, history, *args)
        return "", new_hist, audio_out

    msg.submit(text_submit,
               inputs=[msg, chatbot,
                       model_selector, audio_prompt,
                       exaggeration, temperature,
                       cfg_weight],
               outputs=[msg, chatbot, audio_output])

if __name__ == "__main__":
    if os.environ.get("CUDA_LAUNCH_BLOCKING") != "1":
        logger.info("Run with CUDA_LAUNCH_BLOCKING=1 for detailed CUDA errors.")
    demo.queue().launch(debug=True)
