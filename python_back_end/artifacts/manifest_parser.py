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
    pattern1 = r"```artifact-manifest\s*([\s\S]*?)```"
    match = re.search(pattern1, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(
                    f"Extracted artifact manifest (pattern 1): {manifest.get('artifact_type')}"
                )
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact-manifest code block: {e}")

    # Pattern 2: Code block with artifact
    pattern2 = r"```artifact\s*([\s\S]*?)```"
    match = re.search(pattern2, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(
                    f"Extracted artifact manifest (pattern 2): {manifest.get('artifact_type')}"
                )
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact code block: {e}")

    # Pattern 3: XML-style tags
    pattern3 = r"<artifact(?:-manifest)?>([\s\S]*?)</artifact(?:-manifest)?>"
    match = re.search(pattern3, llm_response, re.IGNORECASE)
    if match:
        try:
            manifest = json.loads(match.group(1).strip())
            if _validate_manifest(manifest):
                logger.info(
                    f"Extracted artifact manifest (pattern 3): {manifest.get('artifact_type')}"
                )
                return manifest
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse artifact XML tags: {e}")

    # Pattern 4: JSON code block containing artifact_type
    pattern4 = r"```json\s*([\s\S]*?)```"
    for match in re.finditer(pattern4, llm_response, re.IGNORECASE):
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict) and _validate_manifest(data):
                logger.info(
                    f"Extracted artifact manifest (pattern 4): {data.get('artifact_type')}"
                )
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
                    logger.info(
                        f"Extracted artifact manifest (pattern 5): {data.get('artifact_type')}"
                    )
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
    valid_types = {
        "spreadsheet",
        "document",
        "pdf",
        "presentation",
        "website",
        "app",
        "code",
    }
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
        if char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidates.append(text[start : i + 1])
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
    cleaned = re.sub(
        r"```artifact-manifest\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"```artifact\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)

    # Remove python-doc code blocks (for code-based document generation)
    cleaned = re.sub(r"```python-doc\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"```python-spreadsheet\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"```python-document\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"```python-pdf\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"```python-presentation\s*[\s\S]*?```", "", cleaned, flags=re.IGNORECASE
    )

    # Remove XML-style artifact tags
    cleaned = re.sub(
        r"<artifact(?:-manifest)?>\s*[\s\S]*?</artifact(?:-manifest)?>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Clean up extra whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    return cleaned


def extract_manifest_and_clean(
    llm_response: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Extract manifest and return both the manifest and cleaned response.
    Convenience function that combines extract_artifact_manifest and clean_response_content.

    Returns:
        Tuple of (manifest or None, cleaned response text)
    """
    manifest = extract_artifact_manifest(llm_response)
    cleaned = clean_response_content(llm_response)
    return manifest, cleaned


def extract_nextjs_project_from_codeblocks(llm_response: str) -> Optional[Dict[str, Any]]:
    """
    Extract a Next.js/React project from multiple code blocks in the response.

    Detects patterns like:
    - ```tsx filename="pages/index.tsx"
    - ```typescript:pages/index.tsx
    - // filepath: pages/index.tsx
    - // pages/index.tsx
    - ```tsx (pages/index.tsx)
    - **pages/index.tsx** followed by code block
    - `pages/index.tsx` followed by code block

    Returns an artifact manifest if a project structure is detected.
    """
    if not llm_response:
        return None

    files: Dict[str, str] = {}

    logger.debug(f"Attempting to extract Next.js project from response ({len(llm_response)} chars)")

    # Pattern 1: ```language filename="path" or ```language:path
    pattern_filename = r'```(?:tsx?|jsx?|javascript|typescript)(?:\s+filename=["\']([^"\']+)["\']|:([^\s\n]+))\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_filename, llm_response, re.IGNORECASE):
        filepath = match.group(1) or match.group(2)
        code = match.group(3).strip()
        if filepath and code:
            # Normalize path
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            files[filepath] = code
            logger.debug(f"Pattern 1 matched: {filepath}")

    # Pattern 2: ```language (path) or ```language - path
    pattern_paren = r'```(?:tsx?|jsx?|javascript|typescript)\s*[\(\-]\s*([^\)\n]+)[\)]?\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_paren, llm_response, re.IGNORECASE):
        filepath = match.group(1).strip()
        code = match.group(2).strip()
        if filepath and code and ('/' in filepath or filepath.endswith(('.tsx', '.ts', '.jsx', '.js'))):
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 2 matched: {filepath}")

    # Pattern 3: Code blocks with // filepath: or // path comment at start
    pattern_comment = r'```(?:tsx?|jsx?|javascript|typescript)\s*\n\s*(?://|/\*)\s*(?:filepath:?\s*)?([^\n\*]+?)(?:\*/|\n)([\s\S]*?)```'
    for match in re.finditer(pattern_comment, llm_response, re.IGNORECASE):
        potential_path = match.group(1).strip()
        code = match.group(2).strip()
        # Only use if it looks like a file path
        if potential_path and code and ('/' in potential_path or potential_path.endswith(('.tsx', '.ts', '.jsx', '.js', '.css', '.json'))):
            filepath = potential_path
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 3 matched: {filepath}")

    # Pattern 4: Detect project structure from headers like "### pages/index.tsx" or "**pages/index.tsx**"
    pattern_header = r'(?:#{1,4}|[\*_]{2})\s*`?([^`\n*#]+\.(?:tsx?|jsx?|json|css))`?(?:[\*_]{2})?\s*\n```(?:tsx?|jsx?|javascript|typescript|json|css)?\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_header, llm_response, re.IGNORECASE):
        filepath = match.group(1).strip()
        code = match.group(2).strip()
        if filepath and code:
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 4 matched: {filepath}")

    # Pattern 5: Backtick path followed by code block: `pages/index.tsx`\n```tsx
    pattern_backtick = r'`([^`\n]+\.(?:tsx?|jsx?|json|css))`\s*\n```(?:tsx?|jsx?|javascript|typescript|json|css)?\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_backtick, llm_response, re.IGNORECASE):
        filepath = match.group(1).strip()
        code = match.group(2).strip()
        if filepath and code:
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 5 matched: {filepath}")

    # Pattern 6: Number + path like "1. pages/index.tsx" or "1) components/Header.tsx"
    pattern_numbered = r'(?:\d+[.\)]\s*)([^\n]+\.(?:tsx?|jsx?|json|css))\s*\n```(?:tsx?|jsx?|javascript|typescript|json|css)?\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_numbered, llm_response, re.IGNORECASE):
        filepath = match.group(1).strip()
        code = match.group(2).strip()
        if filepath and code:
            # Remove any trailing colon or formatting
            filepath = filepath.rstrip(':').strip()
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 6 matched: {filepath}")

    # Pattern 7: Plain filename on line before code block (more permissive)
    # Matches: "pages/index.tsx:\n```tsx" or "pages/index.tsx\n```tsx"
    pattern_plainpath = r'\n([a-zA-Z0-9_\-./]+\.(?:tsx?|jsx?|json|css)):?\s*\n```(?:tsx?|jsx?|javascript|typescript|json|css)?\s*\n([\s\S]*?)```'
    for match in re.finditer(pattern_plainpath, llm_response, re.IGNORECASE):
        filepath = match.group(1).strip()
        code = match.group(2).strip()
        # Only accept if it looks like a real file path
        if filepath and code and ('/' in filepath or filepath in ['App.tsx', 'App.jsx', 'index.tsx', 'index.jsx']):
            if not filepath.startswith('/'):
                filepath = '/' + filepath
            if filepath not in files:
                files[filepath] = code
                logger.debug(f"Pattern 7 matched: {filepath}")

    # Pattern 8 (Fallback): Infer file structure from React components if no paths found
    # This catches cases where AI outputs multiple components without file paths
    if len(files) < 2:
        logger.debug("No file paths found, attempting to infer from React components")

        # Find all tsx/jsx code blocks
        all_code_blocks = re.findall(r'```(?:tsx?|jsx?|javascript|typescript)\s*\n([\s\S]*?)```', llm_response, re.IGNORECASE)

        inferred_files: Dict[str, str] = {}
        for code in all_code_blocks:
            code = code.strip()
            if not code:
                continue

            # Look for export default function/const ComponentName or function ComponentName
            component_match = re.search(
                r'(?:export\s+default\s+)?(?:function|const)\s+([A-Z][a-zA-Z0-9]*)',
                code
            )

            if component_match:
                component_name = component_match.group(1)
                # Determine file path based on component name
                if component_name in ['Home', 'Index', 'Page']:
                    filepath = '/pages/index.tsx'
                elif component_name == 'App':
                    filepath = '/App.tsx'
                elif 'use client' in code or 'use server' in code:
                    # Next.js app router pattern
                    filepath = f'/app/{component_name.lower()}/page.tsx'
                else:
                    filepath = f'/components/{component_name}.tsx'

                if filepath not in inferred_files:
                    inferred_files[filepath] = code
                    logger.debug(f"Pattern 8 (inferred): {filepath} from component {component_name}")

        # Only use inferred files if we found at least 2 components
        if len(inferred_files) >= 2:
            files.update(inferred_files)
            logger.info(f"Inferred {len(inferred_files)} files from React components")

    # Check if we found a valid project structure
    if len(files) < 2:
        logger.debug(f"Not enough files found for project detection: {len(files)}")
        return None

    logger.info(f"Extracted {len(files)} files: {list(files.keys())}")

    # Detect if it's Next.js or React
    is_nextjs = any(
        '/pages/' in f or '/app/' in f or f.endswith('next.config.js') or f.endswith('next.config.ts')
        for f in files.keys()
    )

    # Find entry file
    entry_candidates = [
        '/pages/index.tsx', '/pages/index.ts', '/pages/index.jsx', '/pages/index.js',
        '/app/page.tsx', '/app/page.ts', '/app/page.jsx', '/app/page.js',
        '/App.tsx', '/App.ts', '/App.jsx', '/App.js',
        '/index.tsx', '/index.ts', '/index.jsx', '/index.js',
    ]
    entry_file = '/App.tsx'
    for candidate in entry_candidates:
        if candidate in files:
            entry_file = candidate
            break

    # Extract dependencies from package.json if present
    dependencies = {"react": "^18.2.0", "react-dom": "^18.2.0"}
    if is_nextjs:
        dependencies["next"] = "^14.0.0"

    if '/package.json' in files:
        try:
            pkg = json.loads(files['/package.json'])
            if 'dependencies' in pkg:
                dependencies.update(pkg['dependencies'])
        except json.JSONDecodeError:
            pass

    # Build the manifest
    manifest = {
        "artifact_type": "website",
        "title": "Next.js App" if is_nextjs else "React App",
        "description": f"Generated {'Next.js' if is_nextjs else 'React'} application with {len(files)} files",
        "content": {
            "framework": "nextjs" if is_nextjs else "react",
            "files": files,
            "entry_file": entry_file,
            "dependencies": dependencies,
        }
    }

    logger.info(f"Auto-detected {'Next.js' if is_nextjs else 'React'} project with {len(files)} files")
    return manifest
