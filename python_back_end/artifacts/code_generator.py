"""
Code-based document generator

Instead of JSON manifests, LLM writes Python code that generates documents.
This is more flexible and easier for LLMs to write correctly.

The code never runs in this process. It is posted to the document sandbox
(CODE_EXECUTOR_URL, the `sandbox` service), which returns the files the script
wrote; this module stores them under the artifact directory.
"""

import base64
import binascii
import json
import os
import re
import logging
import urllib.error
import urllib.request
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Output directory for generated documents
ARTIFACT_DIR = os.environ.get("ARTIFACT_STORAGE_DIR", "/data/artifacts")

# Wall-clock limit for one script; the sandbox caps it again at 120 s.
MAX_EXECUTION_TIME = int(os.environ.get("CODE_MAX_EXECUTION_TIME", "60"))  # seconds

DEFAULT_SANDBOX_URL = "http://sandbox:8080"
SANDBOX_DOWN = "the document sandbox is not running"
SANDBOX_BUSY = "the document sandbox is busy or took too long to answer; try again shortly"
SANDBOX_SLOT_WAIT = 30  # sandbox_runner.server.SLOT_WAIT_S: how long it queues a job before answering 429
# The sandbox caps its output at 25 MB (about 34 MB as base64); this is a bound on what we read.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


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
    - Raw Python code (already extracted)

    Args:
        llm_response: The LLM's response text
        artifact_type: Type of artifact (spreadsheet, document, pdf, presentation)

    Returns:
        Python code string or None if not found
    """
    if not llm_response:
        return None

    # First, check if this is already valid Python code (no markdown blocks)
    # This happens when code was already extracted before being passed to worker
    if _validate_document_code(llm_response, artifact_type):
        logger.info(
            f"Using provided code directly (already extracted, {len(llm_response)} chars)"
        )
        return llm_response

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


def auto_detect_document_type(llm_response: str) -> Optional[Tuple[str, str]]:
    """
    Auto-detect document type from Python code in LLM response.

    Returns:
        Tuple of (artifact_type, code) or None if not detected
    """
    if not llm_response:
        return None

    # Find all Python code blocks
    pattern = r"```(?:python(?:-\w+)?)\s*([\s\S]*?)```"
    matches = list(re.finditer(pattern, llm_response, re.IGNORECASE))

    # Import patterns to detect document type
    type_imports = {
        "spreadsheet": ["openpyxl", "xlsxwriter", "pandas"],
        "document": ["docx", "python-docx"],
        "pdf": ["reportlab", "fpdf", "weasyprint", "PyPDF"],
        "presentation": ["pptx", "python-pptx"],
    }

    for match in matches:
        code = match.group(1).strip()
        if len(code) < 50:
            continue

        # Check which type this code matches
        for doc_type, imports in type_imports.items():
            if any(imp.lower() in code.lower() for imp in imports):
                # Additional validation - check for save operation
                save_patterns = [r"\.save\s*\(", r"OUTPUT_PATH", r"output_path"]
                if any(re.search(pat, code, re.IGNORECASE) for pat in save_patterns):
                    logger.info(f"Auto-detected {doc_type} from imports in code")
                    return (doc_type, code)

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

    # Check for markdown code block markers - code should NOT have these
    markdown_markers = [
        "```",
        "```python",
        "```python-doc",
        "```python-spreadsheet",
        "```python-pdf",
        "```python-presentation",
    ]
    for marker in markdown_markers:
        if marker in code:
            logger.warning(f"Code contains markdown marker: {marker}")
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
            # Still allow it - the sandbox is what contains it

    return True


def prepare_code_for_execution(code: str, artifact_id: str, output_filename: str) -> str:
    """
    Wrap the LLM's code so its OUTPUT_PATH lands in the sandbox's OUTPUT_DIR.

    The sandbox hands back every file the script leaves in OUTPUT_DIR, so the
    path is relative to the job and never names a directory on this host.
    """
    return f'''#!/usr/bin/env python3
"""
Auto-generated document generation script
Artifact ID: {artifact_id}
"""

import os
import sys

# Set output path
OUTPUT_PATH = os.path.join(os.environ.get("OUTPUT_DIR", "out"), {output_filename!r})

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# User's code starts here
{code}

# Verify output was created
if not os.path.exists(OUTPUT_PATH):
    print("ERROR: Output file not created", file=sys.stderr)
    sys.exit(1)

print(f"SUCCESS: Generated {{os.path.basename(OUTPUT_PATH)}} ({{os.path.getsize(OUTPUT_PATH)}} bytes)")
'''


def _failure(error: str, **extra: Any) -> Dict[str, Any]:
    return {
        "success": False,
        "error": error,
        "file_path": None,
        "file_size": 0,
        "stdout": "",
        "stderr": "",
        "returncode": -1,
        **extra,
    }


def _post_to_sandbox(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{url}/run",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # The sandbox may hold the request for a free slot, then enforces `timeout` itself,
    # then needs a moment to answer; giving up earlier would drop a finished job's result.
    with urllib.request.urlopen(req, timeout=SANDBOX_SLOT_WAIT + timeout + 20) as resp:
        return json.loads(resp.read(MAX_RESPONSE_BYTES))


def execute_document_code(
    code: str,
    artifact_id: str,
    output_filename: str,
    timeout: int = None,
    memory_limit: str = None,
    use_docker: bool = True,
) -> Dict[str, Any]:
    """
    Run document-generation code in the sandbox and store the file it produces.

    Fails closed: with the sandbox unreachable (CODE_EXECUTOR_URL, default
    http://sandbox:8080) the result is an error, never a local subprocess. memory_limit and use_docker
    are accepted for old callers and ignored; the sandbox sets its own limits.

    Returns:
        Dict with success status, file_path, file_size, stdout/stderr and error.
    """
    timeout = timeout or MAX_EXECUTION_TIME

    if not output_filename or os.path.basename(output_filename) != output_filename:
        return _failure("Invalid output filename")

    url = (os.environ.get("CODE_EXECUTOR_URL", "").strip() or DEFAULT_SANDBOX_URL).rstrip("/")

    prepared_code = prepare_code_for_execution(code, artifact_id, output_filename)
    logger.info(f"Sending document generation code for {artifact_id} to the sandbox")

    try:
        reply = _post_to_sandbox(url, {"code": prepared_code, "timeout": timeout}, timeout)
    except urllib.error.HTTPError as e:
        logger.error(f"Sandbox answered HTTP {e.code} for {artifact_id}")
        if e.code == 429:
            return _failure(SANDBOX_BUSY)
        return _failure(f"the document sandbox refused the job (HTTP {e.code})")
    except (urllib.error.URLError, OSError, ValueError) as e:
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
            logger.error(f"Document sandbox did not answer {artifact_id} in time: {e}")
            return _failure(SANDBOX_BUSY)
        logger.error(f"Document sandbox unreachable at {url}: {e}")
        return _failure(f"{SANDBOX_DOWN} (could not reach it at {url})")

    result = {
        "success": bool(reply.get("ok")),
        "stdout": reply.get("stdout", ""),
        "stderr": reply.get("stderr", ""),
        "returncode": reply.get("returncode", -1),
    }
    if not result["success"]:
        result["error"] = reply.get("error") or "Document generation code failed"
        return result

    produced = next((f for f in reply.get("files") or [] if f.get("name") == output_filename), None)
    if produced is None:
        result["success"] = False
        result["error"] = "Code executed but output file was not created"
        logger.error(result["error"])
        return result

    try:
        data = base64.b64decode(produced.get("b64", ""), validate=True)
    except (binascii.Error, ValueError):
        result["success"] = False
        result["error"] = "The sandbox returned a file that could not be decoded"
        return result

    output_dir = os.path.join(ARTIFACT_DIR, artifact_id)
    output_path = os.path.join(output_dir, output_filename)
    try:
        os.makedirs(output_dir, exist_ok=True)
        partial = output_path + ".part"
        with open(partial, "wb") as fh:
            fh.write(data)
        os.replace(partial, output_path)
    except OSError as e:
        logger.exception("Failed to store generated document")
        result["success"] = False
        result["error"] = f"Could not store the generated file: {e.strerror or e}"
        return result

    result["file_path"] = output_path
    result["file_size"] = len(data)
    logger.info(f"Successfully generated {output_filename} ({len(data)} bytes)")
    return result


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


def get_mime_type(artifact_type: str) -> str:
    """Get proper MIME type for artifact type."""
    mime_types = {
        "spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return mime_types.get(artifact_type, "application/octet-stream")


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
        use_docker: Ignored; kept so existing callers still work

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
    result = execute_document_code(
        code=code,
        artifact_id=artifact_id,
        output_filename=output_filename,
        use_docker=use_docker,
    )

    # Include artifact_id and mime_type in result for worker to use
    result["artifact_id"] = artifact_id
    result["mime_type"] = get_mime_type(artifact_type)

    return result
