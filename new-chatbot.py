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
from browser import execute_nlp_browser_command  # Import the new NLP command function
from os_ops import (
    open_terminal,
    execute_command,
    list_files,
    create_file,
    delete_file,
    move_file,
    check_battery_status
)
from browser import (
    open_new_tab,
    search_google,
    navigate_to,
    clear_browser_cache,
    execute_nlp_browser_command
)

# NOTE: This application requires the 'ffmpeg' command-line tool for audio processing.
# Please install it using your system's package manager (e.g., `sudo apt install ffmpeg`).

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434"
DEFAULT_MODEL = "mistral"
DEVICE        = "cuda" if torch.cuda.is_available() else "cpu"

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
    url_pattern = r'(?:https?:\/\/)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
    matches = re.findall(url_pattern, text)
    if matches:
        url = matches[0]
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    return None

def is_browser_command(message):
    """Determine if the message is actually a browser command."""
    message_lower = message.lower().strip()

    # Common browser command patterns
    browser_patterns = [
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:open|launch|start)\s+(?:a\s+)?(?:new\s+)?(?:browser\s+)?(?:tab|window)',
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:search|look\s+up|find)\s+(?:for\s+)?(?:information\s+about\s+)?',
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:go\s+to|navigate\s+to|visit|open)\s+(?:the\s+)?(?:website\s+)?(?:at\s+)?',
        r'^clear browser cache$',
        r'^hey clear browser cache$'
    ]

    # Check if the message matches any browser command pattern
    for pattern in browser_patterns:
        if re.match(pattern, message_lower):
            return True

    # Check for URL presence
    if extract_url(message):
        return True

    return False

def extract_search_query(message):
    """Extract search query from message using improved pattern matching."""
    message_lower = message.lower().strip()

    # Common search patterns
    search_patterns = [
        r'(?:search|look\s+up|find)\s+(?:for\s+)?(?:information\s+about\s+)?(.+)',
        r'(?:what\s+is|who\s+is|where\s+is|how\s+to)\s+(.+)',
        r'(?:tell\s+me\s+about|show\s+me\s+information\s+about)\s+(.+)',
    ]

    for pattern in search_patterns:
        match = re.search(pattern, message_lower)
        if match:
            query = match.group(1).strip()
            # Remove common question words and phrases
            query = re.sub(r'^(?:please|can you|could you|would you|will you)\s+', '', query)
            return query

    return None

# ─── Chat with Voice ────────────────────────────────────────────────────────────
def chat_with_voice(message, history, selected_model,
                    audio_prompt=None, exaggeration=0.5,
                    temperature=0.8, cfg_weight=0.5):
    """Process voice input and generate voice response."""
    try:
        # Initialize command processor
        processor = CommandProcessor()
        
        # Check if it's a browser command
        if is_browser_command(message):
            response = processor.process_command(message)
        else:
            # Process with Ollama
            try:
                r = requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": selected_model,
                        "prompt": message,
                        "stream": False
                    }
                )
                if not r.ok:
                    raise RuntimeError(f"Ollama API error: {r.status_code} - {r.text}")
                response = r.json()["response"]
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                response = "I'm sorry, I couldn't process that request. Please try again."

        # Generate speech for the response
        try:
            wait_for_vram()
            tts = load_tts_model()
            sr, audio = generate_speech(
                response,
                tts,
                audio_prompt=audio_prompt,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight
            )
            
            # Save audio to temporary file
            temp_audio = "temp_response.wav"
            sf.write(temp_audio, audio, sr)
            
            return response, history + [[message, response]], temp_audio
            
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return response, history + [[message, response]], None
            
    except Exception as e:
        error_msg = f"Error in chat_with_voice: {str(e)}"
        logger.error(error_msg)
        return f"❌ {error_msg}", history + [[message, f"❌ {error_msg}"]], None

# ─── Transcribe & Chat (Voice) ──────────────────────────────────────────────────
def transcribe_and_chat(audio_path, history,
                        selected_model, audio_prompt,
                        exaggeration, temperature,
                        cfg_weight, force_cpu):
    """Transcribe audio input and generate voice response."""
    try:
        # Load STT model and transcribe
        stt = load_stt_model(force_cpu)
        result = stt(audio_path)
        message = result["text"].strip()
        
        if not message:
            return "I couldn't understand what you said. Could you please try again?", history, None
            
        # Process the transcribed message
        return chat_with_voice(
            message,
            history,
            selected_model,
            audio_prompt,
            exaggeration,
            temperature,
            cfg_weight
        )
        
    except Exception as e:
        error_msg = f"Error in transcribe_and_chat: {str(e)}"
        logger.error(error_msg)
        return f"❌ {error_msg}", history + [[None, f"❌ {error_msg}"]], None

def create_interface():
    """Create the Gradio interface."""
    with gr.Blocks(title="Voice-Enabled AI Assistant") as demo:
        gr.Markdown("# 🎙️ Voice-Enabled AI Assistant")
        gr.Markdown("""
        This assistant can:
        - Process voice commands for OS operations
        - Control browser automation
        - Have natural conversations
        - Respond with voice
        
        Just click the microphone button and speak!
        
        Type 'help' or 'show commands' to see available commands.
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    [],
                    elem_id="chatbot",
                    height=600
                )
                with gr.Row():
                    with gr.Column(scale=4):
                        msg = gr.Textbox(
                            show_label=False,
                            placeholder="Type your message here... (Type 'help' to see commands)",
                            container=False
                        )
                    with gr.Column(scale=1):
                        submit = gr.Button("Send")
                
                with gr.Row():
                    audio_input = gr.Audio(
                        source="microphone",
                        type="filepath",
                        label="Voice Input"
                    )
                    audio_output = gr.Audio(
                        label="Voice Response",
                        type="filepath"
                    )
            
            with gr.Column(scale=1):
                with gr.Group():
                    gr.Markdown("### Settings")
                    selected_model = gr.Dropdown(
                        choices=[],
                        label="Ollama Model",
                        value=DEFAULT_MODEL
                    )
                    audio_prompt = gr.Audio(
                        source="upload",
                        type="filepath",
                        label="Voice Style (Optional)"
                    )
                    with gr.Accordion("Advanced Settings", open=False):
                        exaggeration = gr.Slider(
                            minimum=0.0,
                            maximum=1.0,
                            value=0.5,
                            step=0.1,
                            label="Voice Exaggeration"
                        )
                        temperature = gr.Slider(
                            minimum=0.1,
                            maximum=1.0,
                            value=0.8,
                            step=0.1,
                            label="Temperature"
                        )
                        cfg_weight = gr.Slider(
                            minimum=0.1,
                            maximum=1.0,
                            value=0.5,
                            step=0.1,
                            label="CFG Weight"
                        )
                        force_cpu = gr.Checkbox(
                            label="Force CPU for STT",
                            value=False
                        )
                
                with gr.Group():
                    gr.Markdown("### Status")
                    status = gr.Textbox(
                        label="System Status",
                        value="Initializing...",
                        interactive=False
                    )
                    update_btn = gr.Button("🔄 Update Model List")
                
                with gr.Group():
                    gr.Markdown("### Quick Commands")
                    with gr.Row():
                        help_btn = gr.Button("📋 Show Commands")
                        clear_btn = gr.Button("🗑️ Clear Chat")
        
        def update_models():
            models, error = fetch_ollama_models()
            if error:
                return gr.Dropdown.update(choices=[DEFAULT_MODEL], value=DEFAULT_MODEL), error
            return gr.Dropdown.update(choices=models, value=models[0] if models else DEFAULT_MODEL), "✅ Models updated"
        
        def text_submit(message, history, *args):
            if not message.strip():
                return history, None
            response, new_history, audio = chat_with_voice(message, history, *args)
            return new_history, audio
        
        def show_help(history):
            processor = CommandProcessor()
            help_text = processor._handle_help("help")
            return history + [[None, help_text]]
        
        # Set up event handlers
        submit.click(
            text_submit,
            [msg, chatbot, selected_model, audio_prompt, exaggeration, temperature, cfg_weight],
            [chatbot, audio_output]
        ).then(
            lambda: "",
            None,
            msg
        )
        
        audio_input.change(
            transcribe_and_chat,
            [audio_input, chatbot, selected_model, audio_prompt, exaggeration, temperature, cfg_weight, force_cpu],
            [chatbot, audio_output]
        )
        
        update_btn.click(
            update_models,
            None,
            [selected_model, status]
        )
        
        help_btn.click(
            show_help,
            [chatbot],
            [chatbot]
        )
        
        clear_btn.click(
            lambda: [],
            None,
            [chatbot]
        )
        
        # Initial model list update
        demo.load(
            update_models,
            None,
            [selected_model, status]
        )
    
    return demo

class CommandProcessor:
    def __init__(self):
        self.os_commands = {
            "open terminal": self._handle_open_terminal,
            "execute": self._handle_execute_command,
            "list files": self._handle_list_files,
            "create file": self._handle_create_file,
            "delete file": self._handle_delete_file,
            "move file": self._handle_move_file,
            "battery": self._handle_battery_status,
            "help": self._handle_help
        }
        
        self.browser_commands = {
            "open": self._handle_open_url,
            "search": self._handle_search,
            "navigate": self._handle_navigate,
            "clear cache": self._handle_clear_cache
        }
        
        self.command_history = []
        self.max_history = 100

    def process_command(self, command: str) -> str:
        """
        Process a verbal command and route it to the appropriate handler.
        
        Args:
            command (str): The verbal command to process
            
        Returns:
            str: Response from the executed command
        """
        try:
            command = command.lower().strip()
            
            # Add to command history
            self.command_history.append(command)
            if len(self.command_history) > self.max_history:
                self.command_history.pop(0)
            
            # Check for help command first
            if command == "help" or command == "show commands":
                return self._handle_help(command)
            
            # Check for OS commands first
            for cmd_key, handler in self.os_commands.items():
                if cmd_key in command:
                    return handler(command)
            
            # Then check for browser commands
            for cmd_key, handler in self.browser_commands.items():
                if cmd_key in command:
                    return handler(command)
            
            # If no specific command is found, try browser NLP command
            return execute_nlp_browser_command(command)
            
        except Exception as e:
            error_msg = f"Error processing command: {str(e)}"
            logger.error(error_msg)
            return f"❌ {error_msg}"

    def _handle_help(self, command: str) -> str:
        """Show available commands and their usage."""
        help_text = "🤖 Available Commands:\n\n"
        
        help_text += "📁 OS Commands:\n"
        help_text += "- 'open terminal' - Opens a new terminal window\n"
        help_text += "- 'execute <command>' - Runs a shell command\n"
        help_text += "- 'list files [in <directory>]' - Lists files in a directory\n"
        help_text += "- 'create file <path> [with content <text>]' - Creates a new file\n"
        help_text += "- 'delete file <path>' - Deletes a file\n"
        help_text += "- 'move file <source> to <destination>' - Moves or renames a file\n"
        help_text += "- 'battery' - Shows battery status\n\n"
        
        help_text += "🌐 Browser Commands:\n"
        help_text += "- 'open <url>' - Opens a URL in a new tab\n"
        help_text += "- 'search <query>' - Performs a Google search\n"
        help_text += "- 'navigate to <url>' - Navigates to a URL\n"
        help_text += "- 'clear cache' - Clears browser cache\n\n"
        
        help_text += "💡 Other Features:\n"
        help_text += "- Natural language conversation\n"
        help_text += "- Voice input and output\n"
        help_text += "- Command history tracking\n"
        
        return help_text

    def _handle_open_terminal(self, command: str) -> str:
        """Handle terminal opening commands."""
        # Extract optional command to run
        cmd = command.replace("open terminal", "").strip()
        if cmd:
            return open_terminal(cmd)
        return open_terminal()

    def _handle_execute_command(self, command: str) -> str:
        """Handle command execution."""
        # Extract the actual command after "execute"
        cmd = command.replace("execute", "").strip()
        if not cmd:
            return "❌ Please specify a command to execute"
        return execute_command(cmd)

    def _handle_list_files(self, command: str) -> str:
        """Handle file listing commands."""
        # Extract directory if specified
        parts = command.split("in")
        directory = parts[1].strip() if len(parts) > 1 else "."
        return list_files(directory)

    def _handle_create_file(self, command: str) -> str:
        """Handle file creation commands."""
        # Extract file path and content
        parts = command.replace("create file", "").strip().split("with content")
        if not parts[0].strip():
            return "❌ Please specify a file path"
        path = parts[0].strip()
        content = parts[1].strip() if len(parts) > 1 else ""
        return create_file(path, content)

    def _handle_delete_file(self, command: str) -> str:
        """Handle file deletion commands."""
        path = command.replace("delete file", "").strip()
        if not path:
            return "❌ Please specify a file to delete"
        return delete_file(path)

    def _handle_move_file(self, command: str) -> str:
        """Handle file move/rename commands."""
        parts = command.replace("move file", "").strip().split("to")
        if len(parts) != 2:
            return "❌ Invalid move command format. Use: move file <source> to <destination>"
        src = parts[0].strip()
        dest = parts[1].strip()
        if not src or not dest:
            return "❌ Please specify both source and destination paths"
        return move_file(src, dest)

    def _handle_battery_status(self, command: str) -> str:
        """Handle battery status check."""
        return check_battery_status()

    def _handle_open_url(self, command: str) -> str:
        """Handle URL opening commands."""
        url = command.replace("open", "").strip()
        if not url:
            return "❌ Please specify a URL to open"
        return open_new_tab(url)

    def _handle_search(self, command: str) -> str:
        """Handle search commands."""
        query = command.replace("search", "").strip()
        if not query:
            return "❌ Please specify a search query"
        return search_google(query)

    def _handle_navigate(self, command: str) -> str:
        """Handle navigation commands."""
        url = command.replace("navigate", "").strip()
        if not url:
            return "❌ Please specify a URL to navigate to"
        return navigate_to(url)

    def _handle_clear_cache(self, command: str) -> str:
        """Handle cache clearing commands."""
        return clear_browser_cache()

def main():
    processor = CommandProcessor()
    print("🤖 Chatbot initialized. Type 'exit' to quit.")
    
    while True:
        try:
            command = input("\nEnter your command: ").strip()
            if command.lower() == 'exit':
                print("Goodbye! 👋")
                break
                
            response = processor.process_command(command)
            print(f"\n{response}")
            
        except KeyboardInterrupt:
            print("\nGoodbye! 👋")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            print(f"❌ An error occurred: {str(e)}")

if __name__ == "__main__":
    if os.environ.get("CUDA_LAUNCH_BLOCKING") != "1":
        logger.info("Run with CUDA_LAUNCH_BLOCKING=1 for detailed CUDA errors.")
    demo = create_interface()
    demo.queue().launch(debug=True)
    main()
