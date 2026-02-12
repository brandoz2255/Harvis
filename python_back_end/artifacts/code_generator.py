"""
Code-based document generator

Instead of JSON manifests, LLM writes Python code that generates documents.
This is more flexible and easier for LLMs to write correctly.
"""

import os
import re
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Output directory for generated documents
ARTIFACT_DIR = os.environ.get("ARTIFACT_STORAGE_DIR", "/data/artifacts")

# Docker image for code execution
CODE_EXECUTOR_IMAGE = os.environ.get(
    "CODE_EXECUTOR_IMAGE", "harvis-code-executor:latest"
)

# K8s configuration
USE_K8S_EXECUTION = os.environ.get("USE_K8S_EXECUTION", "false").lower() == "true"
CODE_EXECUTOR_NAMESPACE = os.environ.get("CODE_EXECUTOR_NAMESPACE", "artifact-executor")
CODE_EXECUTOR_POD = os.environ.get("CODE_EXECUTOR_POD", "harvis-code-executor")

# Local execution mode (for Docker Compose - avoids Docker socket dependency)
CODE_EXECUTOR_LOCAL = os.environ.get("CODE_EXECUTOR_LOCAL", "false").lower() == "true"

# Resource limits for code execution
MAX_EXECUTION_TIME = int(os.environ.get("CODE_MAX_EXECUTION_TIME", "60"))  # seconds
MAX_MEMORY = os.environ.get("CODE_MAX_MEMORY", "512m")
MAX_CPUS = os.environ.get("CODE_MAX_CPUS", "1.0")


def extract_document_code(llm_response: str, artifact_type: str) -> Optional[str]:
    """
    Extract Python code for document generation from LLM response.

    Supports multiple code block formats:
    - ```python-doc
    - ```python-spreadsheet
    - ```python-document
    - ```python-pdf
    - ```python-presentation
    - ```python

    Args:
        llm_response: The LLM's response text
        artifact_type: Type of artifact (spreadsheet, document, pdf, presentation)

    Returns:
        Python code string or None if not found
    """
    if not llm_response:
        return None

    # Try type-specific code blocks first
    type_patterns = {
        "spreadsheet": r"```python-spreadsheet\s*([\s\S]*?)```",
        "document": r"```python-document\s*([\s\S]*?)```",
        "pdf": r"```python-pdf\s*([\s\S]*?)```",
        "presentation": r"```python-presentation\s*([\s\S]*?)```",
    }

    # Try specific pattern for this artifact type
    if artifact_type in type_patterns:
        pattern = type_patterns[artifact_type]
        match = re.search(pattern, llm_response, re.IGNORECASE)
        if match:
            code = match.group(1).strip()
            if _validate_document_code(code, artifact_type):
                logger.info(
                    f"Extracted {artifact_type} generation code (specific pattern)"
                )
                return code

    # Try generic python-doc pattern
    pattern = r"```python-doc\s*([\s\S]*?)```"
    match = re.search(pattern, llm_response, re.IGNORECASE)
    if match:
        code = match.group(1).strip()
        if _validate_document_code(code, artifact_type):
            logger.info(
                f"Extracted {artifact_type} generation code (python-doc pattern)"
            )
            return code

    # Try generic python pattern
    pattern = r"```python\s*([\s\S]*?)```"
    matches = list(re.finditer(pattern, llm_response, re.IGNORECASE))

    for match in matches:
        code = match.group(1).strip()
        if _validate_document_code(code, artifact_type):
            logger.info(
                f"Extracted {artifact_type} generation code (generic python pattern)"
            )
            return code

    return None


def _validate_document_code(code: str, artifact_type: str) -> bool:
    """
    Validate that the code looks like document generation code.

    Args:
        code: Python code to validate
        artifact_type: Expected artifact type

    Returns:
        True if valid, False otherwise
    """
    if not code or len(code) < 50:
        return False

    # Check for required imports based on type
    required_imports = {
        "spreadsheet": ["openpyxl"],
        "document": ["docx"],
        "pdf": ["reportlab", "fpdf", "weasyprint"],
        "presentation": ["pptx"],
    }

    # Log validation attempt
    logger.info(f"🔍 Validating {artifact_type} code ({len(code)} chars)")

    if artifact_type in required_imports:
        imports = required_imports[artifact_type]
        if not any(imp in code for imp in imports):
            logger.warning(f"Code missing required imports for {artifact_type}")
            return False

    # Check for save operation
    save_patterns = [
        r"\.save\s*\(",
        r"\.save\s+",
        r"write\s*\(",
        r"output_path",
        r"output_file",
    ]

    if not any(re.search(pattern, code, re.IGNORECASE) for pattern in save_patterns):
        logger.warning("Code missing save operation")
        return False

    # Check for dangerous operations
    dangerous_patterns = [
        r"os\.system",
        r"subprocess",
        r"exec\s*\(",
        r"eval\s*\(",
        r"__import__",
        r"importlib",
        r"open\s*\([^)]*[,\']w",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, code):
            logger.warning(f"Code contains potentially dangerous pattern: {pattern}")
            # Still allow it - Docker isolation will protect us

    return True


def prepare_code_for_execution(
    code: str,
    artifact_id: str,
    output_filename: str,
    output_dir: str = None,
    container_output_path: str = None,
) -> Tuple[str, str]:
    """
    Prepare Python code for execution by adding boilerplate and output handling.

    Args:
        code: Original Python code from LLM
        artifact_id: Unique artifact ID
        output_filename: Name of output file
        output_dir: Directory for output (default: ARTIFACT_DIR)
        container_output_path: Path to use inside container (for Docker/K8s execution)

    Returns:
        Tuple of (prepared_code, output_path)
    """
    if output_dir is None:
        output_dir = os.path.join(ARTIFACT_DIR, artifact_id)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    # Use container path if provided (for Docker/K8s), otherwise use host path
    actual_output_path = container_output_path if container_output_path else output_path

    # Prepare the code with boilerplate
    prepared_code = f'''#!/usr/bin/env python3
"""
Auto-generated document generation script
Artifact ID: {artifact_id}
Generated: {datetime.now().isoformat()}
"""

import os
import sys

# Set output path
OUTPUT_PATH = "{actual_output_path}"

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# User's code starts here
{code}

# Verify output was created
if not os.path.exists(OUTPUT_PATH):
    print(f"ERROR: Output file not created at {{OUTPUT_PATH}}", file=sys.stderr)
    sys.exit(1)

file_size = os.path.getsize(OUTPUT_PATH)
print(f"SUCCESS: Generated {{OUTPUT_PATH}} ({{file_size}} bytes)")
'''

    return prepared_code, output_path


def execute_document_code(
    code: str,
    artifact_id: str,
    output_filename: str,
    timeout: int = None,
    memory_limit: str = None,
    use_docker: bool = True,
) -> Dict[str, Any]:
    """
    Execute Python code to generate a document.

    Args:
        code: Python code to execute
        artifact_id: Unique artifact ID
        output_filename: Name of output file
        timeout: Execution timeout in seconds
        memory_limit: Docker memory limit
        use_docker: Whether to use Docker isolation

    Returns:
        Dict with success status, output path, and any errors
    """
    timeout = timeout or MAX_EXECUTION_TIME
    memory_limit = memory_limit or MAX_MEMORY

    # Calculate paths
    output_dir = os.path.join(ARTIFACT_DIR, artifact_id)
    output_path = os.path.join(output_dir, output_filename)

    # Container path for Docker execution
    container_output_path = f"/data/artifacts/{artifact_id}/{output_filename}"

    # Prepare code with appropriate output path
    if USE_K8S_EXECUTION or use_docker:
        prepared_code, output_path = prepare_code_for_execution(
            code, artifact_id, output_filename, output_dir, container_output_path
        )
    else:
        prepared_code, output_path = prepare_code_for_execution(
            code, artifact_id, output_filename, output_dir
        )

    # Save code to temporary file
    work_dir = os.path.join(ARTIFACT_DIR, "code", artifact_id)
    os.makedirs(work_dir, exist_ok=True)

    script_path = os.path.join(work_dir, "generate.py")
    with open(script_path, "w") as f:
        f.write(prepared_code)

    logger.info(f"Executing document generation code for {artifact_id}")
    logger.info(f"Output will be written to: {output_path}")
    logger.info(f"Script saved to: {script_path}")

    # Verify script file exists
    if not os.path.exists(script_path):
        logger.error(f"Script file does not exist: {script_path}")
        return {
            "success": False,
            "error": f"Script file not found: {script_path}",
            "output_path": None,
            "file_size": 0,
        }

    # Verify output directory exists (create if needed)
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        logger.info(f"Creating output directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    # Determine execution mode
    use_k8s = USE_K8S_EXECUTION
    use_docker_local = use_docker

    if CODE_EXECUTOR_LOCAL:
        logger.info("Using local execution mode (CODE_EXECUTOR_LOCAL=true)")
        use_docker_local = False
        use_k8s = False

    try:
        if use_k8s:
            result = _execute_in_k8s(script_path, output_path, timeout)
        elif use_docker_local:
            result = _execute_in_docker(script_path, output_path, timeout, memory_limit)
        else:
            result = _execute_locally(script_path, timeout)

        # Check if output was created
        if result["success"] and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            result["output_path"] = output_path
            result["file_size"] = file_size
            logger.info(f"Successfully generated {output_filename} ({file_size} bytes)")
        elif result["success"]:
            result["success"] = False
            result["error"] = "Code executed but output file was not created"
            logger.error(result["error"])

        return result

    except Exception as e:
        logger.exception("Failed to execute document generation code")
        return {
            "success": False,
            "error": str(e),
            "output_path": None,
            "file_size": 0,
        }


def _execute_in_docker(
    script_path: str, output_path: str, timeout: int, memory_limit: str
) -> Dict[str, Any]:
    """Execute code in isolated Docker container."""

    # Check if Docker is available
    try:
        docker_check = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True
        )
        if docker_check.returncode != 0:
            logger.error("Docker is not available")
            return {
                "success": False,
                "error": "Docker is not available in this environment",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
            }
    except FileNotFoundError:
        logger.error("Docker command not found")
        return {
            "success": False,
            "error": "Docker command not found. Is Docker installed?",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }

    script_dir = os.path.dirname(script_path)
    output_dir = os.path.dirname(output_path)
    script_name = os.path.basename(script_path)

    # Container paths (inside Docker)
    # The script is mounted at /workspace/code/generate.py
    container_script_path = f"/workspace/code/{script_name}"

    logger.info(f"Docker execution:")
    logger.info(f"  Host script path: {script_path}")
    logger.info(f"  Host script dir: {script_dir}")
    logger.info(f"  Script exists: {os.path.exists(script_path)}")
    logger.info(f"  Container script path: {container_script_path}")
    logger.info(f"  Host output path: {output_path}")
    logger.info(f"  Host output dir: {output_dir}")
    logger.info(f"  Output dir exists: {os.path.exists(output_dir)}")

    # Build Docker command - mount entire artifact directory to allow writing anywhere
    # Run as UID 1001 (appuser) to match volume permissions
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",  # No network access
        "--memory",
        memory_limit,
        "--cpus",
        MAX_CPUS,
        "--user",
        "1001:1001",  # Run as appuser for proper permissions
        "-v",
        f"{ARTIFACT_DIR}:/data/artifacts:rw",  # Mount entire artifact directory
        "-v",
        f"{script_dir}:/workspace/code:ro",  # Read-only code mount
        "-w",
        "/workspace",
        CODE_EXECUTOR_IMAGE,
        "python3",
        container_script_path,
    ]

    logger.info(f"Docker command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Code execution timed out after {timeout} seconds")
        return {
            "success": False,
            "error": f"Execution timed out after {timeout} seconds",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }
    except Exception as e:
        logger.error(f"Docker execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }


def _execute_in_k8s(script_path: str, output_path: str, timeout: int) -> Dict[str, Any]:
    """Execute code in Kubernetes pod."""

    script_dir = os.path.dirname(script_path)
    output_dir = os.path.dirname(output_path)
    script_name = os.path.basename(script_path)

    # Get pod name (may need to find it dynamically)
    pod_name = CODE_EXECUTOR_POD

    try:
        # First, try to get the actual pod name if it's a deployment
        get_pod_cmd = [
            "kubectl",
            "get",
            "pods",
            "-n",
            CODE_EXECUTOR_NAMESPACE,
            "-l",
            "app.kubernetes.io/component=code-executor",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
        result = subprocess.run(get_pod_cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            pod_name = result.stdout.strip()
            logger.info(f"Found code executor pod: {pod_name}")
    except Exception as e:
        logger.warning(f"Could not get pod name dynamically, using default: {e}")

    # Copy script to pod
    try:
        copy_cmd = [
            "kubectl",
            "cp",
            "-n",
            CODE_EXECUTOR_NAMESPACE,
            script_path,
            f"{pod_name}:/tmp/{script_name}",
        ]
        result = subprocess.run(copy_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to copy script to pod: {result.stderr}")
            return {
                "success": False,
                "error": f"Failed to copy script to pod: {result.stderr}",
                "stdout": "",
                "stderr": result.stderr,
                "returncode": -1,
            }
    except Exception as e:
        logger.error(f"Failed to copy script to pod: {e}")
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }

    # Execute code in pod
    try:
        exec_cmd = [
            "kubectl",
            "exec",
            "-n",
            CODE_EXECUTOR_NAMESPACE,
            pod_name,
            "--",
            "python3",
            f"/tmp/{script_name}",
        ]
        logger.debug(f"K8s exec command: {' '.join(exec_cmd)}")

        result = subprocess.run(
            exec_cmd, capture_output=True, text=True, timeout=timeout
        )

        # Copy output back from pod if it exists
        if result.returncode == 0:
            try:
                copy_back_cmd = [
                    "kubectl",
                    "cp",
                    "-n",
                    CODE_EXECUTOR_NAMESPACE,
                    f"{pod_name}:{output_path}",
                    output_path,
                ]
                subprocess.run(copy_back_cmd, capture_output=True, text=True)
            except Exception as e:
                logger.warning(f"Failed to copy output from pod: {e}")

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        logger.error(f"K8s code execution timed out after {timeout} seconds")
        return {
            "success": False,
            "error": f"Execution timed out after {timeout} seconds",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }
    except Exception as e:
        logger.error(f"K8s execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }


def _execute_locally(script_path: str, timeout: int) -> Dict[str, Any]:
    """Execute code locally (fallback if Docker not available)."""

    try:
        result = subprocess.run(
            ["python3", script_path], capture_output=True, text=True, timeout=timeout
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Execution timed out after {timeout} seconds",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
        }


def get_output_filename(artifact_type: str, title: str) -> str:
    """Generate output filename based on artifact type and title."""
    # Clean title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    safe_title = safe_title[:50].strip()

    extensions = {
        "spreadsheet": ".xlsx",
        "document": ".docx",
        "pdf": ".pdf",
        "presentation": ".pptx",
    }

    ext = extensions.get(artifact_type, ".bin")
    return f"{safe_title}{ext}"


# Convenience function for main.py
def generate_document_from_code(
    llm_response: str,
    artifact_type: str,
    title: str,
    artifact_id: str,
    use_docker: bool = True,
) -> Dict[str, Any]:
    """
    Complete pipeline: extract code and generate document.

    Args:
        llm_response: LLM response containing Python code
        artifact_type: Type of artifact to generate
        title: Title of the document
        artifact_id: Unique artifact ID
        use_docker: Whether to use Docker isolation

    Returns:
        Dict with success status and output information
    """
    # Extract code
    code = extract_document_code(llm_response, artifact_type)

    if not code:
        return {
            "success": False,
            "error": f"No valid {artifact_type} generation code found in response",
            "output_path": None,
            "file_size": 0,
        }

    # Generate output filename
    output_filename = get_output_filename(artifact_type, title)

    # Execute code
    return execute_document_code(
        code=code,
        artifact_id=artifact_id,
        output_filename=output_filename,
        use_docker=use_docker,
    )
