"""
Extract artifact manifests from LLM responses
"""

import json
import re
from typing import Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


def extract_artifact_manifest(llm_response: str) -> Optional[Dict[str, Any]]:
    """
    Extract artifact manifest from LLM response.
    Supports multiple formats:
    1. ```artifact-manifest\n{json}\n```
    2. ```artifact\n{json}\n```
    3. <artifact>{json}</artifact>
    4. <artifact-manifest>{json}</artifact-manifest>
    5. Direct JSON with artifact_type field in response

    Returns None if no valid manifest found.
    """
    if not llm_response:
        return None

    # Pattern 1: Code block with artifact-manifest
    pattern1 = r'```artifact-manifest\s*([\s\S]*?)```'
    match = re.search(pattern1, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(f"Extracted artifact manifest (pattern 1): {manifest.get('artifact_type')}")
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact-manifest code block: {e}")

    # Pattern 2: Code block with artifact
    pattern2 = r'```artifact\s*([\s\S]*?)```'
    match = re.search(pattern2, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(f"Extracted artifact manifest (pattern 2): {manifest.get('artifact_type')}")
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact code block: {e}")

    # Pattern 3: XML-style tags
    pattern3 = r'<artifact(?:-manifest)?>([\s\S]*?)</artifact(?:-manifest)?>'
    match = re.search(pattern3, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(f"Extracted artifact manifest (pattern 3): {manifest.get('artifact_type')}")
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact XML tags: {e}")

    # Pattern 4: JSON code block containing artifact_type
    pattern4 = r'```json\s*([\s\S]*?)```'
    for match in re.finditer(pattern4, llm_response, re.IGNORECASE):
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict) and _validate_manifest(data):
                logger.info(f"Extracted artifact manifest (pattern 4): {data.get('artifact_type')}")
                return data
        except json.JSONDecodeError:
            continue

    # Pattern 5: Look for artifact_type in any JSON object in response
    # This is a fallback for models that might embed JSON differently
    if '"artifact_type"' in llm_response:
        # Try to find balanced JSON objects
        json_candidates = _find_json_objects(llm_response)
        for candidate in json_candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and _validate_manifest(data):
                    logger.info(f"Extracted artifact manifest (pattern 5): {data.get('artifact_type')}")
                    return data
            except json.JSONDecodeError:
                continue

    return None


def _validate_manifest(manifest: Dict[str, Any]) -> bool:
    """Validate that a dict looks like a valid artifact manifest"""
    if not isinstance(manifest, dict):
        return False

    # Must have artifact_type
    if "artifact_type" not in manifest:
        return False

    # Must have valid artifact_type
    valid_types = {"spreadsheet", "document", "pdf", "presentation", "website", "app", "code"}
    if manifest.get("artifact_type") not in valid_types:
        return False

    # Must have title
    if "title" not in manifest or not manifest.get("title"):
        return False

    # Must have content
    if "content" not in manifest or not isinstance(manifest.get("content"), dict):
        return False

    return True


def _find_json_objects(text: str) -> list:
    """Find potential JSON objects in text by matching balanced braces"""
    candidates = []
    depth = 0
    start = -1

    for i, char in enumerate(text):
        if char == '{':
            if depth == 0:
                start = i
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start != -1:
                candidates.append(text[start:i + 1])
                start = -1

    return candidates


def clean_response_content(llm_response: str) -> str:
    """
    Remove artifact manifest from LLM response to get clean text for display.
    Returns the response with manifest blocks removed.
    """
    if not llm_response:
        return llm_response

    cleaned = llm_response

    # Remove artifact-manifest code blocks
    cleaned = re.sub(r'```artifact-manifest\s*[\s\S]*?```', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'```artifact\s*[\s\S]*?```', '', cleaned, flags=re.IGNORECASE)

    # Remove XML-style artifact tags
    cleaned = re.sub(r'<artifact(?:-manifest)?>\s*[\s\S]*?</artifact(?:-manifest)?>', '', cleaned, flags=re.IGNORECASE)

    # Clean up extra whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    return cleaned


def extract_manifest_and_clean(llm_response: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Extract manifest and return both the manifest and cleaned response.
    Convenience function that combines extract_artifact_manifest and clean_response_content.

    Returns:
        Tuple of (manifest or None, cleaned response text)
    """
    manifest = extract_artifact_manifest(llm_response)
    cleaned = clean_response_content(llm_response)
    return manifest, cleaned
