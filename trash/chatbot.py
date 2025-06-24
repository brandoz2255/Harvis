import gradio as gr
import requests
import torch
import logging
import os
import time
import soundfile as sf
import re
import numpy as np
from transformers import pipeline


from os_ops import (
    open_terminal,
    execute_command,
    list_files,
    create_file,
    delete_file,
    move_file,
    check_battery_status
)
from trash.browser import (
    open_new_tab,
    search_google,
    navigate_to,
    clear_browser_cache,
    execute_nlp_browser_command
)

# NOTE: This application requires the 'ffmpeg' command-line tool for audio processing.
# Please install it using your system's package manager (e.g., `sudo apt install ffmpeg`).

# ─── Set up logging ─────────────────────────────────────────────────────────────
def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('harvis.log')
        ]
    )

setup_logging()
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434"
DEFAULT_MODEL = "mistral"
DEVICE        = "cuda" if torch.cuda.is_available() else "cpu"
logger.info(f"Application running on device: {DEVICE}")


# ─── Global Model Instances (Lazy Loaded) ──────────────────────────────────
stt_pipeline = None
voice_generator = None

def get_stt_pipeline(force_cpu=False):
    """Loads the STT pipeline on its first use."""
    global stt_pipeline
    if stt_pipeline is None:
        try:
            stt_device = "cpu" if force_cpu else DEVICE
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

def get_voice_generator(force_cpu=False):
    """Initializes the VoiceGenerator on its first use."""
    global voice_generator
    if voice_generator is None:
        try:
            logger.info("Initializing Voice Generator...")
            voice_generator = VoiceGenerator(force_cpu=force_cpu)
        except Exception as e:
            logger.error(f"FATAL: Could not initialize Voice Generator: {e}")
            # This is critical, so we re-raise the exception
            raise
    return voice_generator

# ─── Ollama Functions ───────────────────────────────────────────────────────────
def check_ollama_status():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.ok
    except requests.exceptions.RequestException:
        return False

def fetch_ollama_models():
    if not check_ollama_status():
        logger.error("Ollama server is not running or accessible")
        return [], "⚠️ Ollama server is not running. Please start Ollama first."
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags")
        r.raise_for_status()
        data = r.json().get("models", [])
        names = [m["name"] for m in data]
        logger.info(f"Available Ollama models: {names}")
        return names, f"✅ Found {len(names)} models."
    except requests.exceptions.RequestException as e:
        msg = f"Failed to connect to Ollama: {e}"
        logger.error(msg)
        return [], f"⚠️ {msg}"

# ─── Core Chat Logic ────────────────────────────────────────────────────────────
def chat_with_voice(message, history, selected_model, exaggeration, temperature):
    """Processes text input, gets an LLM response, and generates voice."""
    audio_output_path = None
    response_text = ""
    try:
        # Placeholder for command processing logic if needed
        # For now, we send all messages to Ollama
        logger.info(f"Sending prompt to Ollama model '{selected_model}': '{message}'")
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": selected_model, "prompt": message, "stream": False},
            timeout=60
        )
        r.raise_for_status()
        response_text = r.json()["response"]
        logger.info(f"Ollama response: '{response_text[:100]}...'")

    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API error: {e}")
        response_text = "I'm sorry, I couldn't connect to the language model. Please ensure Ollama is running."
    except Exception as e:
        logger.error(f"An unexpected error occurred during LLM request: {e}")
        response_text = f"An unexpected error occurred: {e}"

    # Generate speech for the response
    try:
        generator = get_voice_generator()
        sr, audio_data = generator.generate_speech(response_text, temperature, exaggeration)

        if sr and audio_data is not None:
            temp_audio_path = "temp_response.wav"
            sf.write(temp_audio_path, audio_data, sr)
            audio_output_path = temp_audio_path
            logger.info(f"Voice response saved to {temp_audio_path}")
        else:
            logger.warning("TTS generation failed. Proceeding without audio response.")

    except Exception as e:
        logger.error(f"TTS processing failed: {e}")
        # The app will continue, but without audio

    # Update history
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": response_text})

    return history, audio_output_path

def transcribe_and_chat(audio_path, history, selected_model, exaggeration, temperature, force_cpu):
    """Transcribes audio input and chains into the main chat logic."""
    if not audio_path:
        return history, None

    try:
        logger.info(f"Transcribing audio from: {audio_path}")
        stt = get_stt_pipeline(force_cpu)
        transcription = stt(audio_path)["text"].strip()
        logger.info(f"Transcription result: '{transcription}'")

        if not transcription:
            return history, None

        return chat_with_voice(transcription, history, selected_model, exaggeration, temperature)

    except Exception as e:
        error_msg = f"Error in transcribe_and_chat: {e}"
        logger.error(error_msg)
        history.append({"role": "user", "content": f"[Audio Input Failed: {error_msg}]"})
        return history, None


# ─── Gradio Interface ───────────────────────────────────────────────────────────
def create_interface():
    """Creates and configures the Gradio UI."""
    with gr.Blocks(title="Harvis - Voice Assistant", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🎙️ Harvis - Voice Assistant")
        gr.Markdown("Speak or type to interact. The assistant will respond with text and voice.")

        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    [],
                    elem_id="chatbot",
                    label="Conversation",
                    height=600,
                )
                with gr.Row():
                    msg_textbox = gr.Textbox(
                        show_label=False,
                        placeholder="Type your message here or use the microphone...",
                        container=False,
                        scale=4
                    )
                    submit_btn = gr.Button("Send", scale=1)

                with gr.Row():
                    audio_input = gr.Audio(
                        sources=["microphone"],
                        type="filepath",
                        label="Voice Input (Click record, then stop)",
                    )
                    audio_output = gr.Audio(
                        label="Voice Response",
                        type="filepath",
                        autoplay=True,
                    )

            with gr.Column(scale=1):
                with gr.Group():
                    gr.Markdown("### ⚙️ Settings")
                    model_list, status_msg = fetch_ollama_models()
                    status_indicator = gr.Markdown(status_msg)
                    selected_model = gr.Dropdown(
                        choices=model_list,
                        value=model_list[0] if model_list else DEFAULT_MODEL,
                        label="Ollama Model",
                        allow_custom_value=True
                    )
                    refresh_models_btn = gr.Button("Refresh Models")

                with gr.Accordion("Advanced Voice Settings", open=False):
                    exaggeration = gr.Slider(minimum=0.0, maximum=1.0, value=0.5, step=0.1, label="Voice Exaggeration")
                    temperature = gr.Slider(minimum=0.1, maximum=1.0, value=0.7, step=0.1, label="Voice Temperature")
                    force_cpu = gr.Checkbox(label="Force CPU for All Models", value=False, info="Use if you have GPU issues.")

                clear_btn = gr.Button("🗑️ Clear Chat")

        # --- Event Handlers ---
        def on_text_submit(message, history, *args):
            if not message.strip():
                return history, None
            history, audio_path = chat_with_voice(message, history, *args)
            return history, audio_path, "" # Return "" to clear the textbox

        def on_audio_change(audio, history, *args):
            if audio is None:
                return history, None
            history, audio_path = transcribe_and_chat(audio, history, *args)
            return history, audio_path, "" # Also clear textbox after voice input

        def on_refresh_models():
            models, status = fetch_ollama_models()
            return gr.Dropdown(choices=models, value=models[0] if models else DEFAULT_MODEL), status

        # Connect components to functions
        submit_btn.click(
            on_text_submit,
            inputs=[msg_textbox, chatbot, selected_model, exaggeration, temperature],
            outputs=[chatbot, audio_output, msg_textbox]
        )
        msg_textbox.submit(
            on_text_submit,
            inputs=[msg_textbox, chatbot, selected_model, exaggeration, temperature],
            outputs=[chatbot, audio_output, msg_textbox]
        )

        audio_input.change(
            on_audio_change,
            inputs=[audio_input, chatbot, selected_model, exaggeration, temperature, force_cpu],
            outputs=[chatbot, audio_output, msg_textbox]
        )

        clear_btn.click(lambda: [], None, chatbot)
        refresh_models_btn.click(on_refresh_models, None, [selected_model, status_indicator])

        # Initialize models on startup
        def initialize_models(force_cpu_on_startup):
            try:
                get_stt_pipeline(force_cpu_on_startup)
                get_voice_generator(force_cpu_on_startup)
                return "✅ All models initialized successfully."
            except Exception as e:
                logger.error(f"STARTUP FAILED: {e}", exc_info=True)
                return f"⚠️ Model initialization failed: {e}"

        initialization_status = gr.Markdown("Models are initializing...")
        demo.load(initialize_models, inputs=[force_cpu], outputs=[initialization_status])

    return demo

# ─── Main Execution ─────────────────────────────────────────────────────────────
def main():
    try:
        # Create and launch the Gradio interface
        app = create_interface()
        app.launch(
            server_name="0.0.0.0",
            server_port=7860,
            show_error=True,
            share=True # Set to False if you don't want a public link
        )
    except KeyboardInterrupt:
        logger.info("Application terminated by user.")
    except Exception as e:
        logger.error(f"Application failed to launch: {e}", exc_info=True)

if __name__ == "__main__":
    # You will need to create dummy files for these modules if they don't exist
    # For example, create an empty os_ops.py and browser.py in the same directory.
    # This example focuses on the core Gradio app logic.
    main()
