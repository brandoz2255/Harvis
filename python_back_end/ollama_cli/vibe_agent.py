
import os
import sys
import subprocess
import logging
import requests
import json
from typing import List, Dict, Any, Optional
from starlette.websockets import WebSocket

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from os_ops import (
    execute_command,
    list_files,
    create_file,
    delete_file,
    write_file as write_to_file,
    stream_command
)
from chatterbox_tts import load_tts_model, generate_speech
import whisper

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/generate"

class VibeAgent:
    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.history: List[Dict[str, Any]] = []
        self.mode = "assistant"  # or "vibe"
        self.tts_model = load_tts_model()
        self.stt_model = whisper.load_model("base")
        self.file_tree = ""
        self.update_file_tree()

    def update_file_tree(self):
        """Updates the file tree representation of the project directory."""
        self.file_tree = list_files(self.project_dir)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribes audio to text using Whisper."""
        if not os.path.exists(audio_path):
            return ""
        try:
            result = self.stt_model.transcribe(audio_path)
            return result.get("text", "").strip()
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return ""

    async def speak(self, text: str, websocket: WebSocket):
        """Converts text to speech and sends it over WebSocket."""
        try:
            sr, wav = generate_speech(text, self.tts_model)
            # In a real implementation, you'd send the audio data over the WebSocket
            # For now, we'll just send a text message indicating speech generation
            await websocket.send_json({"type": "speech", "content": text})
            logger.info(f"Generated speech for: {text}")
        except Exception as e:
            logger.error(f"Error generating speech: {e}")
            await websocket.send_json({"type": "error", "content": f"Error generating speech: {e}"})

    async def process_command(self, command: str, websocket: WebSocket):
        """Processes a command based on the current mode."""
        self.history.append({"role": "user", "content": command})
        await websocket.send_json({"type": "status", "content": f"Processing command: {command}"})

        if self.mode == "assistant":
            await self.execute_assistant_command(command, websocket)
        elif self.mode == "vibe":
            await self.execute_vibe_plan(command, websocket)

    async def execute_assistant_command(self, command: str, websocket: WebSocket):
        """Executes a single command in assistant mode."""
        await websocket.send_json({"type": "status", "content": f"Executing: {command}"})
        await websocket.send_json({"type": "command_start", "command": command})

        stderr_output = ""
        command_failed = False
        for output_chunk in stream_command(command):
            await websocket.send_json(output_chunk)
            if output_chunk["type"] == "stderr":
                stderr_output += output_chunk["content"]
            elif output_chunk["type"] == "status" and output_chunk.get("exit_code", 0) != 0:
                command_failed = True
        
        if command_failed and stderr_output:
            await self._diagnose_and_fix(command, stderr_output, websocket)
            response_text = f"Command '{command}' failed. Attempted diagnosis and fix."
        else:
            response_text = f"Command '{command}' executed."

        self.history.append({"role": "assistant", "content": response_text})
        await websocket.send_json({"type": "status", "content": response_text})
        await self.speak(response_text, websocket)

    async def _generate_plan(self, objective: str, websocket: WebSocket) -> List[str]:
        """Generates a sequence of shell commands from an objective using an LLM."""
        await websocket.send_json({"type": "status", "content": "Thinking: Generating plan..."})
        prompt = f"""
        You are an AI assistant that generates a sequence of shell commands to achieve a high-level objective.
        The user wants to: {objective}
        Your task is to break this down into a series of commands.
        - Only output the commands, one per line.
        - Do not include any explanations or natural language.
        - The commands should be runnable in a standard Linux shell.
        - Use `echo` to provide status updates to the user.
        - For file creation, use `create_file("path/to/file.txt", "content")`.
        - For writing to files, use `write_to_file("path/to/file.txt", "content")`.
        Example:
        Objective: Create a new file called 'test.txt' and write 'hello world' to it.
        Commands:
        echo "Creating file test.txt"
        create_file("test.txt", "hello world")
        echo "File created and content written."

        Objective: {objective}
        Commands:
        """
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": "mistral",
                "prompt": prompt,
                "stream": False
            })
            response.raise_for_status()
            commands = response.json()["response"].strip().split('\n')
            plan = [cmd for cmd in commands if cmd.strip()]
            await websocket.send_json({"type": "status", "content": f"Plan generated with {len(plan)} steps."})
            return plan
        except requests.exceptions.RequestException as e:
            logger.error(f"Error communicating with Ollama: {e}")
            await websocket.send_json({"type": "error", "content": f"Error: Could not connect to Ollama to generate a plan: {e}"})
            return ["echo 'Error: Could not connect to Ollama to generate a plan.'"]

    async def _diagnose_and_fix(self, failed_command: str, stderr_output: str, websocket: WebSocket):
        """Diagnoses an error and attempts to fix it using the LLM."""
        await websocket.send_json({"type": "status", "content": "Diagnosing error..."})
        diagnosis_prompt = f"""
        The following command failed:
        {failed_command}
        With the following stderr output:
        {stderr_output}
        
        Please diagnose the root cause of this error and suggest a shell command to fix it. 
        Only output the fix command. Do not include any explanations or natural language.
        If no fix is possible, output "NO_FIX".
        """
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": "mistral",
                "prompt": diagnosis_prompt,
                "stream": False
            })
            response.raise_for_status()
            fix_command = response.json()["response"].strip()

            if fix_command and fix_command != "NO_FIX":
                await websocket.send_json({"type": "status", "content": f"Proposed fix: {fix_command}"})
                if await self.ask_for_confirmation(f"apply fix: `{fix_command}`", websocket):
                    await websocket.send_json({"type": "status", "content": "Attempting to apply fix..."})
                    for output_chunk in stream_command(fix_command):
                        await websocket.send_json(output_chunk)
                    await self.speak("Fix applied.", websocket)
                else:
                    await self.speak("Fix declined.", websocket)
            else:
                await self.speak("Could not diagnose a fix for the error.", websocket)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error communicating with Ollama for diagnosis: {e}")
            await websocket.send_json({"type": "error", "content": f"Error: Could not connect to Ollama for diagnosis: {e}"})
            await self.speak("Error: Could not connect to Ollama for diagnosis.", websocket)

    async def execute_vibe_plan(self, objective: str, websocket: WebSocket):
        """Creates and executes a multi-step plan for a high-level objective."""
        plan = await self._generate_plan(objective, websocket)
        
        execution_log = []
        for step in plan:
            await websocket.send_json({"type": "status", "content": f"Executing step: {step}"})
            await websocket.send_json({"type": "command_start", "command": step})

            # IMPORTANT: Add permission check for sensitive commands here
            if any(cmd in step for cmd in ["pip install", "npm install", "rm "]):
                if not await self.ask_for_confirmation(f"run `{step}`", websocket):
                    execution_log.append(f"Skipping: {step}")
                    await websocket.send_json({"type": "status", "content": f"Skipping: {step}"})
                    continue

            # Check for specific Python function calls
            if step.startswith("create_file("):
                try:
                    # Extract arguments: create_file("path", "content")
                    match = re.match(r'create_file\("(.*)", "(.*)"\)', step)
                    if match:
                        file_path = match.group(1)
                        content = match.group(2)
                        result = create_file(file_path, content)
                        await websocket.send_json({"type": "stdout", "content": result + "\n"})
                    else:
                        await websocket.send_json({"type": "stderr", "content": f"Invalid create_file command format: {step}\n"})
                except Exception as e:
                    await websocket.send_json({"type": "stderr", "content": f"Error executing create_file: {e}\n"})
            elif step.startswith("write_to_file("):
                try:
                    # Extract arguments: write_to_file("path", "content")
                    match = re.match(r'write_to_file\("(.*)", "(.*)"\)', step)
                    if match:
                        file_path = match.group(1)
                        content = match.group(2)
                        result = write_to_file(file_path, content)
                        await websocket.send_json({"type": "stdout", "content": result + "\n"})
                    else:
                        await websocket.send_json({"type": "stderr", "content": f"Invalid write_to_file command format: {step}\n"})
                except Exception as e:
                    await websocket.send_json({"type": "stderr", "content": f"Error executing write_to_file: {e}\n"})
            else:
                # Use stream_command for real-time output for other commands
                stderr_output = ""
                command_failed = False
                for output_chunk in stream_command(step):
                    await websocket.send_json(output_chunk)
                    if output_chunk["type"] == "stderr":
                        stderr_output += output_chunk["content"]
                    elif output_chunk["type"] == "status" and output_chunk.get("exit_code", 0) != 0:
                        command_failed = True
                
                if command_failed and stderr_output:
                    await self._diagnose_and_fix(step, stderr_output, websocket)

            # Speak after each command execution (optional, can be refined)
            await self.speak(f"Executed {step.split(' ')[0]}", websocket)

        response_text = "Plan execution completed."
        self.history.append({"role": "assistant", "content": response_text})
        await websocket.send_json({"type": "status", "content": response_text})
        await self.speak(response_text, websocket)

    async def ask_for_confirmation(self, action: str, websocket: WebSocket) -> bool:
        """Asks the user for confirmation before executing a sensitive action."""
        prompt = f"Are you sure you want to {action}? (yes/no)"
        await websocket.send_json({"type": "awaiting_confirmation", "prompt": prompt})
        await self.speak(prompt, websocket)

        try:
            # Wait for a response from the WebSocket
            response = await websocket.receive_json()
            user_response = response.get("confirmation", "").lower()
            return user_response == "yes"
        except Exception as e:
            logger.error(f"Error receiving confirmation from WebSocket: {e}")
            await websocket.send_json({"type": "error", "content": f"Error awaiting confirmation: {e}"})
            return False

