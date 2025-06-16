import os
import subprocess
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_test():
    """Run tests to verify chatbot functionality."""
    logger.info("Starting chatbot test suite...")

    # Test 1: Check if the new-chatbot.py file exists
    try:
        path = Path("new-chatbot.py")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")
        logger.info("✅ Test 1 Passed: new-chatbot.py exists")
    except Exception as e:
        logger.error(f"❌ Test 1 Failed: {str(e)}")

    # Test 2: Check if the chatbot can be started
    try:
        result = subprocess.run(
            ["python3", "new-chatbot.py"],
            capture_output=True,
            text=True
        )
        if "Starting AI Voice Assistant..." in result.stdout:
            logger.info("✅ Test 2 Passed: Chatbot starts successfully")
        else:
            raise Exception(f"Chatbot did not start properly. Output:\n{result.stdout}")
    except Exception as e:
        logger.error(f"❌ Test 2 Failed: {str(e)}")

    # Test 3: Check if the browser automation documentation exists
    try:
        path = Path("docs/browser-automation.md")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")
        logger.info("✅ Test 3 Passed: docs/browser-automation.md exists")
    except Exception as e:
        logger.error(f"❌ Test 3 Failed: {str(e)}")

    # Test 4: Check if the core technologies documentation exists
    try:
        path = Path("docs/core-technologies.md")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")
        logger.info("✅ Test 4 Passed: docs/core-technologies.md exists")
    except Exception as e:
        logger.error(f"❌ Test 4 Failed: {str(e)}")

    # Test 5: Check if the LLM integration documentation exists
    try:
        path = Path("docs/llm-integration.md")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")
        logger.info("✅ Test 5 Passed: docs/llm-integration.md exists")
    except Exception as e:
        logger.error(f"❌ Test 5 Failed: {str(e)}")

    # Test 6: Check if the OS operations file has the expected content
    try:
        path = Path("os-ops.py")
        with open(path, "r") as f:
            content = f.read()
            if "def open_terminal" in content and "def execute_command" in content:
                logger.info("✅ Test 6 Passed: os-ops.py has expected content")
            else:
                raise Exception(f"os-ops.py does not have the expected content")
    except Exception as e:
        logger.error(f"❌ Test 6 Failed: {str(e)}")

    # Test 7: Check if the Docker Compose file exists
    try:
        path = Path("docker-compose.yaml")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File does not exist: {path}")
        logger.info("✅ Test 7 Passed: docker-compose.yaml exists")
    except Exception as e:
        logger.error(f"❌ Test 7 Failed: {str(e)}")

if __name__ == "__main__":
    run_test()
