import gradio as gr
import requests
import torch
import logging
import os
import soundfile as sf
from transformers import pipeline
from chatterbox.tts import ChatterboxTTS, punc_norm

# NOTE: This application requires the 'ffmpeg' command-line tool for audio processing.
# Please install it using your system's package manager (e.g., `sudo apt install ffmpeg`).

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "mistral"  # Changed from mistral:latest to just mistral
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# --- Global Model Variables ---
tts_model = None
stt_pipeline = None

def check_ollama_status():
    """Check if Ollama server is running and accessible."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        return True if response.ok else False
    except requests.exceptions.RequestException:
        return False

def fetch_ollama_models():
    """Fetch available models from Ollama with improved error handling."""
    if not check_ollama_status():
        logger.error("Ollama server is not running or not accessible")
        return [], "⚠️ Ollama server is not running. Please start Ollama first."

    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags")
        if response.ok:
            models = response.json().get("models", [])
            if not models:
                return [], "No models found. Please pull some models using 'ollama pull <model_name>'"
            
            model_names = [model["name"] for model in models]
            logger.info(f"Available models: {model_names}")
            return model_names, None
        else:
            error_msg = f"Error fetching models: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return [], error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to connect to Ollama: {str(e)}"
        logger.error(error_msg)
        return [], error_msg

# --- Model Loading Functions (Unchanged) ---
def load_stt_model(force_cpu=False):
    global stt_pipeline, DEVICE
    stt_device = "cpu" if force_cpu else DEVICE
    if stt_pipeline is None:
        try:
            logger.info(f"Loading STT (Whisper) model on {stt_device}")
            stt_pipeline = pipeline(
                "automatic-speech-recognition",
                model="openai/whisper-base.en",
                device=stt_device
            )
        except Exception as e:
            logger.error(f"Error loading STT model: {str(e)}")
            raise
    return stt_pipeline

def load_tts_model(force_cpu=False):
    global tts_model, DEVICE
    tts_device = "cpu" if force_cpu else DEVICE
    if tts_model is None:
        try:
            logger.info(f"Loading TTS model on {tts_device}")
            tts_model = ChatterboxTTS.from_pretrained(device=tts_device)
        except Exception as e:
            logger.error(f"Error loading TTS model on {tts_device}: {str(e)}")
            if not force_cpu and tts_device == "cuda":
                logger.info("Attempting to fall back to CPU for TTS...")
                return load_tts_model(force_cpu=True)
            raise
    return tts_model

def generate_speech(text, model, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    try:
        normalized_text = punc_norm(text)
        wav = model.generate(
            normalized_text,
            audio_prompt_path=audio_prompt,
            exaggeration=exaggeration,
            temperature=temperature,
            cfg_weight=cfg_weight
        )
        return (model.sr, wav.squeeze(0).numpy())
    except Exception as e:
        logger.error(f"TTS Error: {str(e)}")
        raise

# --- FIX 2: Updated chat function to handle the new `messages` format ---
def chat_with_voice(message, history, selected_model, audio_prompt=None, exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    if not message.strip():
        return history, None

    if not check_ollama_status():
        error_msg = "⚠️ Ollama server is not running. Please start Ollama first."
        history.append({"role": "assistant", "content": error_msg})
        return history, None

    history.append({"role": "user", "content": message})

    # Create the prompt from the message history
    system_prompt = "You are a helpful and friendly verbal assistant. Please provide concise and conversational responses."
    prompt = f"{system_prompt}\n\n"
    for turn in history:
        role = "User" if turn['role'] == 'user' else "Assistant"
        prompt += f"{role}: {turn['content']}\n"
    prompt += "Assistant:"
    
    try:
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(f"{OLLAMA_URL}/api/generate", json=payload)
        if response.ok:
            result = response.json()
            answer = result.get("response", "").strip()
        else:
            error_msg = f"Error from Ollama: {response.status_code} - {response.text}"
            if "model not found" in response.text.lower():
                error_msg += "\nTip: Use 'ollama pull <model_name>' to download the model first."
            logger.error(error_msg)
            answer = f"[Error: {error_msg}]"
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to connect to Ollama: {str(e)}"
        logger.error(error_msg)
        answer = f"[Connection Error: {error_msg}]"

    audio_output = None
    try:
        model = load_tts_model()
        audio_output = generate_speech(answer, model, audio_prompt, exaggeration, temperature, cfg_weight)
    except Exception as e:
        logger.error(f"TTS Error: {str(e)}")
        answer += f"\n[TTS Error: {str(e)}]"
    
    history.append({"role": "assistant", "content": answer})
    return history, audio_output


def transcribe_and_chat(audio_path, history, selected_model, audio_prompt, exaggeration, temperature, cfg_weight, force_cpu):
    if audio_path is None:
        return history, None, "Please record your voice first.", None

    logger.info(f"Received audio file: {audio_path}")

    try:
        stt_model = load_stt_model(force_cpu=force_cpu)
        transcription = stt_model(audio_path)["text"]
        logger.info(f"Transcription: '{transcription}'")
    except Exception as e:
        logger.error(f"STT Error: {str(e)}")
        if "ffmpeg" in str(e).lower():
            error_text = "[STT Error: `ffmpeg` was not found. Please install `ffmpeg` on your system to process audio.]"
        else:
            error_text = f"[STT Error: {str(e)}]"
        return history, None, error_text, None

    # Call the updated chat function
    new_history, audio_response = chat_with_voice(
        transcription, history, selected_model, audio_prompt, exaggeration, temperature, cfg_weight
    )
    return new_history, audio_response, transcription, ""


with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🗣️ Voice Chat with Ollama
    Have a conversation with an LLM using voice or text! Choose your preferred model and interaction method.
    
    > **Note**: Make sure Ollama is running and you have pulled your desired models using `ollama pull <model_name>`
    """)

    # Get initial models and any error message
    initial_models, error_msg = fetch_ollama_models()
    
    with gr.Row():
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(height=400, label="Conversation", type="messages")
        
        with gr.Column(scale=1):
            gr.Markdown("### Model Selection")
            model_status = gr.Markdown("" if not error_msg else f"⚠️ {error_msg}")
            model_selector = gr.Dropdown(
                choices=initial_models,
                value=initial_models[0] if initial_models else None,
                label="Select AI Model",
                interactive=True,
                info="Choose the AI model you want to chat with"
            )
            
            refresh_models = gr.Button("🔄 Refresh Models")
            
            def update_models():
                models, error = fetch_ollama_models()
                status = "" if not error else f"⚠️ {error}"
                return models, models[0] if models else None, status
            
            refresh_models.click(
                update_models,
                outputs=[model_selector, model_selector, model_status]
            )

            with gr.Accordion("Advanced Voice Settings", open=False):
                audio_prompt = gr.Audio(
                    sources=["upload"],
                    type="filepath",
                    label="Voice Reference for TTS (Optional)",
                    value=None
                )
                force_cpu = gr.Checkbox(
                    label="Force CPU Mode",
                    value=False,
                    info="Enable if experiencing GPU issues"
                )
                exaggeration = gr.Slider(0.25, 2, value=0.5, step=.05, label="Voice Exaggeration")
                temperature = gr.Slider(0.05, 5, value=0.8, step=.05, label="Temperature")
                cfg_weight = gr.Slider(0.0, 1, value=0.5, step=.05, label="CFG/Pace Weight")

    gr.Markdown("---")
    with gr.Row():
        with gr.Column():
            gr.Markdown("### 🎤 Voice Input")
            voice_input = gr.Audio(
                sources=["microphone"], 
                type="filepath", 
                label="Record Your Message"
            )
            
        with gr.Column():
            gr.Markdown("### ⌨️ Text Input")
            msg = gr.Textbox(
                label="Type your message", 
                placeholder="Type here or use voice input above...",
                info="Press Enter to send"
            )
    
    audio_output = gr.Audio(label="AI Voice Response", autoplay=True)
    
    # Clear button at the bottom
    with gr.Row():
        clear = gr.ClearButton(
            components=[chatbot, msg, audio_output, voice_input],
            value="Clear Conversation"
        )

    # Event Handling Logic
    voice_input.stream(
        transcribe_and_chat,
        inputs=[voice_input, chatbot, model_selector, audio_prompt, exaggeration, temperature, cfg_weight, force_cpu],
        outputs=[chatbot, audio_output, msg, voice_input]
    )
    
    def text_submit_wrapper(message, history, *args):
        """Wrapper to handle the different return values for text submission."""
        new_history, audio_out = chat_with_voice(message, history, *args)
        return "", new_history, audio_out

    msg.submit(
        text_submit_wrapper,
        inputs=[msg, chatbot, model_selector, audio_prompt, exaggeration, temperature, cfg_weight],
        outputs=[msg, chatbot, audio_output]
    )

if __name__ == "__main__":
    if os.environ.get("CUDA_LAUNCH_BLOCKING") != "1":
        logger.info("For detailed CUDA error tracking, consider running with: CUDA_LAUNCH_BLOCKING=1")
    
    demo.queue().launch(debug=True)
