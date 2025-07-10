
import os
import sys
import subprocess
import logging
import requests
import json
import re
from typing import List, Dict, Any, Optional, Tuple
from starlette.websockets import WebSocket
from datetime import datetime

#TODO: Add RAG for vibe coding documents such as next.js documentation and frameworks documentations

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from os_ops import (
    execute_command,
    list_files,
    create_file,
    delete_file,
    stream_command
)
# Import model management functions from model_manager to avoid circular imports
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_manager import unload_all_models, reload_models_if_needed, log_gpu_memory

# ─── Set up logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/generate"

class VibeAgent:
    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.history: List[Dict[str, Any]] = []
        self.mode = "assistant"  # or "vibe"
        # Models will be loaded on demand for memory efficiency
        self.tts_model = None
        self.stt_model = None
        self.file_tree = ""
        
        # Enhanced vibe coding properties
        self.vibe_workspace = os.path.join(project_dir, "vibe")
        self.context_file = os.path.join(self.vibe_workspace, "Ollama.md")
        self.ensure_vibe_workspace()
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
        """Converts text to speech and sends it over WebSocket with model management."""
        try:
            # Ensure TTS models are loaded for speech generation
            reload_models_if_needed()
            
            # For WebSocket implementation, just send text indication
            # Full TTS integration would require audio streaming setup
            await websocket.send_json({"type": "speech", "content": text})
            logger.info(f"Generated speech indication for: {text}")
        except Exception as e:
            logger.error(f"Error in speech processing: {e}")
            await websocket.send_json({"type": "error", "content": f"Error in speech processing: {e}"})

    async def process_command(self, command: str, websocket: WebSocket):
        """Processes a command based on the current mode with intelligent model management."""
        self.history.append({"role": "user", "content": command})
        await websocket.send_json({"type": "status", "content": f"Processing command: {command}"})

        # Phase 1: Unload models to free GPU memory for vibe processing
        logger.info("🤖 Unloading models for vibe agent processing")
        unload_all_models()
        log_gpu_memory("before vibe processing")

        if self.mode == "assistant":
            await self.execute_assistant_command(command, websocket)
        elif self.mode == "vibe":
            await self.execute_vibe_plan(command, websocket)
        
        # Phase 2: Reload models after vibe processing
        logger.info("🔄 Reloading models after vibe processing")
        reload_models_if_needed()
        log_gpu_memory("after vibe processing")

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
        - For writing to files, use `create_file("path/to/file.txt", "content")`.
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
            }, timeout=90)
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
            }, timeout=90)
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

    # ─── Enhanced Vibe Coding Methods (LLM-Generated) ──────────────────────────

    def ensure_vibe_workspace(self):
        """Ensure the vibe workspace directory exists"""
        if not os.path.exists(self.vibe_workspace):
            os.makedirs(self.vibe_workspace, exist_ok=True)
            logger.info(f"Created vibe workspace: {self.vibe_workspace}")

    def get_vibe_file_tree(self) -> Dict[str, Any]:
        """Get the file tree for the vibe workspace"""
        try:
            def build_tree(path: str, relative_path: str = "") -> Dict[str, Any]:
                items = []
                try:
                    for item in sorted(os.listdir(path)):
                        item_path = os.path.join(path, item)
                        item_relative = os.path.join(relative_path, item) if relative_path else item
                        
                        if os.path.isdir(item_path):
                            items.append({
                                "name": item,
                                "type": "directory", 
                                "path": item_relative,
                                "children": build_tree(item_path, item_relative)["items"]
                            })
                        else:
                            items.append({
                                "name": item,
                                "type": "file",
                                "path": item_relative,
                                "size": os.path.getsize(item_path)
                            })
                except PermissionError:
                    pass
                
                return {"items": items}
            
            return build_tree(self.vibe_workspace)
        except Exception as e:
            logger.error(f"Error building vibe file tree: {e}")
            return {"items": []}

    def write_vibe_file(self, file_path: str, content: str) -> bool:
        """Write/update a file in the vibe workspace"""
        try:
            if '..' in file_path:
                return False
            
            full_path = os.path.join(self.vibe_workspace, file_path)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Created/updated vibe file: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error writing vibe file {file_path}: {e}")
            return False

    def update_context_notes(self, message: str, response: str, files_created: List[str] = None):
        """Update the Ollama.md context file with session information"""
        try:
            # Read existing content
            existing_content = ""
            if os.path.exists(self.context_file):
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    existing_content = f.read()
            else:
                existing_content = "# Ollama Context Notes\n\nVibe Coding Session History\n\n"
            
            # Create new entry
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_entry = f"""## Session {timestamp}

**User Request:** {message}

**AI Response:** {response}

"""
            
            if files_created:
                new_entry += "**Files Created:**\n"
                for file_path in files_created:
                    new_entry += f"- {file_path}\n"
                new_entry += "\n"
            
            new_entry += "---\n\n"
            
            # Append to existing content
            updated_content = existing_content + new_entry
            
            # Write back to file
            with open(self.context_file, 'w', encoding='utf-8') as f:
                f.write(updated_content)
                
            logger.info(f"Updated context notes with session: {message[:50]}...")
            
        except Exception as e:
            logger.error(f"Error updating context notes: {e}")

    async def enhanced_vibe_coding(self, message: str, existing_files: List[Dict] = None) -> Tuple[str, List[Dict], List[str]]:
        """
        Enhanced vibe coding that lets the LLM generate everything based on user preferences
        """
        try:
            # Read context notes for continuity
            context = self.read_context_notes()
            
            # Build file context
            file_context = ""
            if existing_files:
                file_context = "CURRENT FILES:\n"
                for file in existing_files:
                    file_context += f"=== {file.get('name', 'unknown')} ===\n{file.get('content', '')}\n\n"
            
            # Get LLM to plan the entire project structure and content
            project_plan = await self.get_llm_project_plan(message, context, file_context)
            
            # Execute the plan (create files)
            files_created = []
            steps = []
            
            if project_plan and "files" in project_plan:
                for i, file_info in enumerate(project_plan["files"]):
                    file_path = file_info.get("path", f"file_{i+1}.py")
                    file_content = file_info.get("content", "")
                    
                    if self.write_vibe_file(file_path, file_content):
                        files_created.append(file_path)
                        steps.append({
                            "id": str(i+1),
                            "description": f"Created {file_path}",
                            "action": "create_file",
                            "target": file_path,
                            "completed": True
                        })
            
            # Generate summary response
            summary = project_plan.get("summary", f"Created {len(files_created)} files for your project!")
            
            # Update context notes
            self.update_context_notes(message, summary, files_created)
            
            return summary, steps, files_created
            
        except Exception as e:
            logger.error(f"Error in enhanced vibe coding: {e}")
            return f"Error creating project: {str(e)}", [], []

    async def get_llm_project_plan(self, message: str, context: str, file_context: str) -> Dict:
        """
        Ask LLM to plan and generate the entire project structure and content
        """
        try:
            system_prompt = """You are an expert programmer and project architect. Your job is to create complete, functional project structures based on user requests.

INSTRUCTIONS:
1. Analyze the user's request carefully
2. Plan a complete project structure with all necessary files
3. Generate actual, functional code for each file (no placeholders or comments like "# Add your code here")
4. Create a project that works out of the box
5. Include proper imports, error handling, and best practices
6. Make the code production-ready and well-structured

RESPONSE FORMAT (JSON):
{
  "summary": "Brief description of what you created",
  "files": [
    {
      "path": "relative/path/to/file.py",
      "content": "Complete file content here (no placeholders)"
    }
  ]
}

REQUIREMENTS:
- Generate COMPLETE, FUNCTIONAL code
- No TODO comments or placeholders
- Include all necessary dependencies
- Make it a working project the user can run immediately
- Follow best practices for the chosen technology stack"""

            user_prompt = f"""
User Request: {message}

Previous Context:
{context}

Existing Files:
{file_context}

Please create a complete, functional project based on this request. Generate all necessary files with complete, working code.
"""

            payload = {
                "model": "mistral",
                "prompt": f"System: {system_prompt}\n\nUser: {user_prompt}\n\nAssistant: I'll create a complete project for you. Here's the JSON response:",
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9
                }
            }

            response = requests.post(OLLAMA_URL, json=payload, timeout=120)
            response.raise_for_status()
            
            llm_response = response.json().get("response", "").strip()
            
            # Try to parse JSON response
            try:
                # Extract JSON from response (in case LLM adds extra text)
                json_start = llm_response.find('{')
                json_end = llm_response.rfind('}') + 1
                
                if json_start >= 0 and json_end > json_start:
                    json_str = llm_response[json_start:json_end]
                    project_plan = json.loads(json_str)
                    return project_plan
                else:
                    logger.error("No valid JSON found in LLM response")
                    return self.fallback_project_plan(message, llm_response)
                    
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return self.fallback_project_plan(message, llm_response)
            
        except Exception as e:
            logger.error(f"Error getting LLM project plan: {e}")
            return self.fallback_project_plan(message, str(e))

    def fallback_project_plan(self, message: str, llm_response: str) -> Dict:
        """Create a simple fallback plan when JSON parsing fails"""
        return {
            "summary": f"Created a simple project based on: {message}",
            "files": [
                {
                    "path": "main.py",
                    "content": f'''#!/usr/bin/env python3
"""
Project: {message}
Generated by Vibe Coding

LLM Response:
{llm_response}
"""

def main():
    print("🚀 Vibe Coding Project Started!")
    print(f"Goal: {message}")
    
    # Implementation goes here
    print("✨ Project ready for development!")

if __name__ == "__main__":
    main()
'''
                }
            ]
        }

    def read_context_notes(self) -> str:
        """Read existing context notes for continuity"""
        try:
            if os.path.exists(self.context_file):
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    return f.read()
            return ""
        except Exception as e:
            logger.error(f"Error reading context notes: {e}")
            return ""

