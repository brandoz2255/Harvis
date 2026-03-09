"""
Workspace XML parser — extracts <harvis_workspace> tags from streamed LLM text.

The main chat LLM emits XML signals to auto-launch a workspace:
    <harvis_workspace model="local">Create docker-compose.yml with nginx</harvis_workspace>

This module handles:
  - Complete tag extraction from fully-buffered text
  - Incremental parsing from streaming chunks (partial tag buffering)
  - Stripping the XML from visible response text
"""

import re
from dataclasses import dataclass
from typing import Optional

# Matches the full tag including optional model attribute
_TAG_RE = re.compile(
    r'<harvis_workspace(?:\s+model="([^"]*)")?\s*>(.*?)</harvis_workspace>',
    re.DOTALL,
)

# Detects a partial opening tag (start of tag but no closing tag yet)
_PARTIAL_OPEN_RE = re.compile(r'<harvis_workspace[^>]*>(?!.*</harvis_workspace>)', re.DOTALL)


@dataclass
class WorkspaceSignal:
    """Parsed workspace signal from the LLM response."""
    task_brief: str
    model: str  # "local", "kimi", or "gpt-oss"


def extract_workspace_signal(text: str) -> tuple[Optional[WorkspaceSignal], str]:
    """
    Extract a <harvis_workspace> tag from text.

    Returns:
        (signal, cleaned_text) — signal is None if no complete tag found.
        cleaned_text has the XML tag stripped out.
    """
    match = _TAG_RE.search(text)
    if not match:
        return None, text

    model = (match.group(1) or "local").strip()
    task_brief = match.group(2).strip()

    # Validate model
    if model not in ("local", "kimi", "gpt-oss"):
        model = "local"

    # Strip the tag from the text
    cleaned = text[:match.start()] + text[match.end():]
    cleaned = cleaned.strip()

    signal = WorkspaceSignal(task_brief=task_brief[:200], model=model)
    return signal, cleaned


class StreamingXMLParser:
    """
    Incremental parser for streaming chunks.

    Buffers text until a complete <harvis_workspace> tag is found,
    or releases buffered text if no tag is forming.
    """

    def __init__(self):
        self._buffer: str = ""
        self._found_signal: Optional[WorkspaceSignal] = None

    @property
    def signal(self) -> Optional[WorkspaceSignal]:
        """The workspace signal if one was found."""
        return self._found_signal

    def feed(self, chunk: str) -> str:
        """
        Feed a streaming chunk.

        Returns:
            Text safe to display to the user (XML tags stripped).
            May return empty string if buffering a partial tag.
        """
        self._buffer += chunk

        # Already found a signal — just strip any remaining tag remnants
        if self._found_signal:
            signal, cleaned = extract_workspace_signal(self._buffer)
            self._buffer = ""
            return cleaned

        # Try to extract a complete tag
        signal, cleaned = extract_workspace_signal(self._buffer)
        if signal:
            self._found_signal = signal
            self._buffer = ""
            return cleaned

        # Check if we're in the middle of a partial tag
        if _PARTIAL_OPEN_RE.search(self._buffer):
            # Don't emit anything yet — wait for the closing tag
            return ""

        # Check for the very start of a tag (e.g. "<harvis_" without closing >)
        if "<harvis_" in self._buffer and ">" not in self._buffer.split("<harvis_")[-1]:
            return ""

        # No tag forming — release the buffer
        result = self._buffer
        self._buffer = ""
        return result

    def flush(self) -> str:
        """Flush any remaining buffered text (call at end of stream)."""
        result = self._buffer
        self._buffer = ""
        return result
