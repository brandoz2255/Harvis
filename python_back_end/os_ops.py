import os
import subprocess
import logging
from typing import List, Optional, Generator, Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def open_terminal(command: Optional[str] = None) -> str:
    """
    Open a terminal window and optionally execute a command.

    Args:
        command (Optional[str]): Command to run in the terminal. If None, just opens an empty terminal.

    Returns:
        str: Result message
    """
    try:
        if os.name == 'posix':  # Linux/MacOS
            if command:
                result = subprocess.run(
                    ['gnome-terminal', '--', 'bash', '-c', command],
                    check=True,
                    capture_output=True,
                    text=True
                )
                return f"✅ Terminal opened and executed: {command}\nOutput:\n{result.stdout}"
            else:
                # Just open an empty terminal
                subprocess.run(['gnome-terminal'], check=True)
                return "✅ Terminal opened"
        elif os.name == 'nt':  # Windows
            if command:
                result = subprocess.run(
                    ['cmd', '/c', command],
                    check=True,
                    capture_output=True,
                    text=True
                )
                return f"✅ Command executed in terminal: {command}\nOutput:\n{result.stdout}"
            else:
                os.system('start cmd')
                return "✅ Terminal opened"
        else:
            logger.error(f"Unsupported OS: {os.name}")
            return f"❌ Error: Unsupported operating system ({os.name})"
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed with exit code {e.returncode}:\n{e.stderr}"
        logger.error(error_msg)
        return f"❌ Command execution failed:\n{error_msg}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to open terminal: {error_msg}")
        return f"❌ Error opening terminal: {error_msg}"

def execute_command(command: str) -> str:
    """
    Execute a shell command and return the result.

    Args:
        command (str): Command to execute

    Returns:
        str: Result message with command output or error
    """
    try:
        if os.name == 'posix':  # Linux/MacOS
            # Use shell=False and pass command as a list for security
            result = subprocess.run(
                ['bash', '-c', command],
                check=True,
                capture_output=True,
                text=True
            )
            return f"✅ Command executed: {command}\nOutput:\n{result.stdout}"
        elif os.name == 'nt':  # Windows
            result = subprocess.run(
                ['cmd', '/c', command],
                check=True,
                capture_output=True,
                text=True
            )
            return f"✅ Command executed: {command}\nOutput:\n{result.stdout}"
        else:
            logger.error(f"Unsupported OS: {os.name}")
            return f"❌ Error: Unsupported operating system ({os.name})"
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed with exit code {e.returncode}:\n{e.stderr}"
        logger.error(error_msg)
        return f"❌ Command execution failed:\n{error_msg}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to execute command: {error_msg}")
        return f"❌ Error executing command: {error_msg}"

def stream_command(command: str) -> Generator[Dict[str, Any], None, None]:
    """
    Execute a shell command and stream its stdout and stderr.
    Yields dictionaries with 'type' (stdout, stderr, status) and 'content'.
    """
    logger.info(f"Streaming command: {command}")
    process = None
    try:
        process = subprocess.Popen(
            ['bash', '-c', command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # Decode stdout/stderr as text
            bufsize=1,  # Line-buffered
            universal_newlines=True  # For cross-platform newline handling
        )

        # Stream stdout and stderr simultaneously
        while True:
            stdout_line = process.stdout.readline()
            stderr_line = process.stderr.readline()

            if stdout_line:
                yield {"type": "stdout", "content": stdout_line.strip() + "\n"}
            if stderr_line:
                yield {"type": "stderr", "content": stderr_line.strip() + "\n"}

            if not stdout_line and not stderr_line and process.poll() is not None:
                break

        # Ensure all output is consumed after process exits
        for stdout_line in process.stdout.readlines():
            yield {"type": "stdout", "content": stdout_line.strip() + "\n"}
        for stderr_line in process.stderr.readlines():
            yield {"type": "stderr", "content": stderr_line.strip() + "\n"}

        process.wait()  # Wait for the process to fully terminate
        if process.returncode != 0:
            yield {"type": "status", "content": f"Command failed with exit code {process.returncode}", "exit_code": process.returncode}
        else:
            yield {"type": "status", "content": "Command completed successfully", "exit_code": 0}

    except FileNotFoundError:
        yield {"type": "status", "content": f"Error: Command not found: {command.split()[0]}", "exit_code": 127}
    except Exception as e:
        logger.error(f"Error streaming command '{command}': {e}")
        yield {"type": "status", "content": f"Error executing command: {e}", "exit_code": 1}
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait()

def list_files(directory: Optional[str] = '.') -> str:
    """
    List files in the specified directory.

    Args:
        directory (Optional[str]): Directory path. Default is current directory.

    Returns:
        str: Result message with file listing or error
    """
    try:
        # Use os.scandir for better performance than glob.glob
        with os.scandir(directory) as entries:
            files = [entry.name for entry in entries if entry.is_file()]
            directories = [entry.name for entry in entries if entry.is_dir()]

        result = f"Files in {directory}:\n{', '.join(files)}\n\n"
        result += f"Directories in {directory}:\n{', '.join(directories)}"

        return f"✅ File listing for {directory}\n\n{result}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to list files: {error_msg}")
        return f"❌ Error listing files: {error_msg}"

def create_file(path: str, content: Optional[str] = '') -> str:
    """
    Create a file with optional initial content.

    Args:
        path (str): File path
        content (Optional[str]): Initial content for the file. Default is empty string.

    Returns:
        str: Result message
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)

        return f"✅ File created: {path}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to create file: {error_msg}")
        return f"❌ Error creating file: {error_msg}"

def delete_file(path: str) -> str:
    """
    Delete a file.

    Args:
        path (str): File path

    Returns:
        str: Result message
    """
    try:
        os.remove(path)
        return f"✅ File deleted: {path}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to delete file: {error_msg}")
        return f"❌ Error deleting file: {error_msg}"

def move_file(src: str, dest: str) -> str:
    """
    Move or rename a file.

    Args:
        src (str): Source file path
        dest (str): Destination file path

    Returns:
        str: Result message
    """
    try:
        os.rename(src, dest)
        return f"✅ File moved/renamed from {src} to {dest}"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to move file: {error_msg}")
        return f"❌ Error moving file: {error_msg}"

def check_battery_status() -> str:
    """
    Check the system battery status (Linux only).

    Returns:
        str: Result message with battery status or error
    """
    try:
        if os.name != 'posix':
            return "❌ Battery status check is only supported on Linux systems"

        result = subprocess.run(
            ['cat', '/sys/class/power_supply/BAT0/capacity'],
            capture_output=True,
            text=True,
            check=True
        )

        capacity = result.stdout.strip()
        return f"✅ Battery level: {capacity}%"
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to check battery status: {error_msg}")
        return f"❌ Error checking battery: {error_msg}"
