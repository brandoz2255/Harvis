"""Moonshot AI API client for Kimi K2.5 integration."""

import os
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from fastapi import HTTPException
import httpx

logger = logging.getLogger(__name__)

# Moonshot API configuration.
#
# Moonshot runs TWO separate platforms with SEPARATE key namespaces:
#   platform.moonshot.ai → https://api.moonshot.ai/v1   (global)
#   platform.moonshot.cn → https://api.moonshot.cn/v1   (China)
# A key issued on one returns 401 on the other, which is the single most common
# cause of "invalid api key" here. Override with MOONSHOT_BASE_URL to match
# whichever console the key was created in.
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1").rstrip("/")


def _key_fingerprint(api_key: str) -> str:
    """Non-reversible identifier for a key, safe to log.

    Enough to tell two keys apart or spot an empty one; never enough to use.
    """
    if not api_key:
        return "<missing>"
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:8]
    return f"len={len(api_key)} sha256:{digest}"


def _explain_error(status: int, body: str, base_url: str) -> str:
    """Turn a Moonshot HTTP error into something the user can act on.

    A 401 here is almost never "the key is malformed" — it's the key belonging to
    the other Moonshot platform, so say that instead of echoing the raw body.
    """
    if status == 401:
        other = ("https://api.moonshot.cn/v1" if "moonshot.ai" in base_url
                 else "https://api.moonshot.ai/v1")
        return (
            f"Moonshot rejected the API key at {base_url}. Moonshot runs two separate "
            f"platforms with separate keys — if this key was created on the other console, "
            f"set MOONSHOT_BASE_URL={other} and restart the backend. Otherwise re-copy the "
            f"key from the console that issued it."
        )
    if status == 429:
        return "Moonshot rate limit or quota exceeded. Check the balance on your Moonshot account."
    return f"Moonshot API error {status}: {body[:400]}"


class MoonshotClient:
    """Client for interacting with Moonshot AI API (Kimi models)."""

    def __init__(self, api_key: str, base_url: str = MOONSHOT_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _filter_empty_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out empty and tool-role messages before sending to Moonshot.

        Moonshot API requirements:
        - All messages must have non-empty content.
        - tool / function role messages are invalid unless tools are defined in the
          request (we never send tools). Strip them to avoid "tool_call_id not found".
        - Strip tool_calls from assistant messages for the same reason.
        """
        filtered = []
        for msg in messages:
            role = msg.get("role", "")

            # Drop tool / function result messages — Kimi is called without tools
            if role in ("tool", "function"):
                logger.warning(f"Filtering out {role} role message (no tools defined)")
                continue

            # Strip tool_calls field from assistant messages if present
            if role == "assistant" and msg.get("tool_calls"):
                msg = {k: v for k, v in msg.items() if k != "tool_calls"}

            content = msg.get("content", "")
            # Handle multimodal content (list format for vision)
            if isinstance(content, list):
                # Keep message if it has any content items
                if content:
                    filtered.append(msg)
                else:
                    logger.warning(f"Filtering out empty multimodal {role} message")
            # Handle string content
            elif isinstance(content, str):
                if content and content.strip():
                    filtered.append(msg)
                else:
                    logger.warning(f"Filtering out empty {role} message")
            else:
                # Unknown content type, keep it
                filtered.append(msg)
        return filtered

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> str:
        """
        Send a chat completion request to Moonshot API.

        Args:
            model: Model name (e.g., "kimi-k2.5")
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response

        Returns:
            The model's response text
        """
        # Filter out empty messages (Moonshot API rejects them)
        filtered_messages = self._filter_empty_messages(messages)

        # Kimi models only support temperature=1.0
        payload = {
            "model": model,
            "messages": filtered_messages,
            "temperature": 1.0,
            "stream": stream,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0)
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self.headers,
                )

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(
                        "Moonshot API error %s at %s (key %s): %s",
                        response.status_code, self.base_url,
                        _key_fingerprint(self.api_key), error_text,
                    )
                    raise HTTPException(
                        status_code=response.status_code if response.status_code in (401, 403, 429) else 502,
                        detail=_explain_error(response.status_code, error_text, self.base_url),
                    )

                data = response.json()
                return data["choices"][0]["message"]["content"]

        except httpx.TimeoutException:
            logger.error("Moonshot API request timed out")
            raise HTTPException(
                status_code=504, detail="Moonshot API request timed out"
            )
        except Exception as e:
            logger.error(f"Error calling Moonshot API: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error calling Moonshot API: {str(e)}"
            )

    async def chat_completion_stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion from Moonshot API.

        Yields:
            Chunks of the response text
        """
        # Filter out empty messages (Moonshot API rejects them)
        filtered_messages = self._filter_empty_messages(messages)

        # Kimi K2.5 only supports temperature=1.0
        payload = {
            "model": model,
            "messages": filtered_messages,
            "temperature": 1.0,
            "stream": True,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        try:
            # NEVER log self.headers or the raw key — the Authorization header carries the
            # secret verbatim and container logs are readable by anyone with docker access.
            # A fingerprint is enough to tell "wrong key" from "no key" when debugging.
            logger.info(
                "Moonshot API: POST %s/chat/completions model=%s messages=%d key=%s",
                self.base_url, model, len(filtered_messages), _key_fingerprint(self.api_key),
            )

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0)
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self.headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = (await response.aread()).decode(errors="replace")
                        logger.error(
                            "Moonshot API error %s at %s (key %s): %s",
                            response.status_code, self.base_url,
                            _key_fingerprint(self.api_key), error_text,
                        )
                        raise HTTPException(
                            status_code=response.status_code if response.status_code in (401, 403, 429) else 502,
                            detail=_explain_error(response.status_code, error_text, self.base_url),
                        )

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        yield delta["content"]
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            logger.error(f"Error streaming from Moonshot API: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error streaming from Moonshot API: {str(e)}"
            )


def get_moonshot_client(api_key: str) -> MoonshotClient:
    """Create a Moonshot client with the given API key."""
    return MoonshotClient(api_key)


# Moonshot model mapping. kimi-k3 = the 2.8T MoE flagship (1M ctx, released 2026-07-16);
# kimi-k2.6 = the prior stable; kimi-k2.5 = multimodal. All OpenAI-compatible on this base URL.
MOONSHOT_MODELS = {
    "kimi-k3": "kimi-k3",
    "kimi-k2.6": "kimi-k2.6",
    "kimi-k2.5": "kimi-k2.5",
    "kimi-k2": "kimi-k2",
    "kimi-k1.5": "kimi-k1.5",
    "kimi-latest": "kimi-latest",
}


def is_moonshot_model(model_name: str) -> bool:
    """Check if a model name corresponds to a Moonshot/Kimi model."""
    model_lower = model_name.lower()
    # nvidia-kimi routes through the NVIDIA NIM proxy, not Moonshot
    if model_lower.startswith("nvidia-"):
        return False
    return any(x in model_lower for x in ["kimi", "moonshot"])


def get_moonshot_model_id(model_name: str) -> str:
    """Resolve a facade or bare model name to the real Moonshot API model id.
    Strips the ``moonshot/`` catalog prefix and recognizes the k3 / k2.6 / k2.5 / k2 / k1.5
    families. Order matters — the more-specific version tags are checked before bare ``k2``."""
    m = (model_name or "").lower().split("/", 1)[-1]  # strip the 'moonshot/' facade prefix

    if "k3" in m:
        return "kimi-k3"
    elif "k2.6" in m or "k2-6" in m:
        return "kimi-k2.6"
    elif "k2.5" in m or "k2-5" in m:
        return "kimi-k2.5"
    elif "k2" in m:
        return "kimi-k2"
    elif "k1.5" in m or "k1-5" in m:
        return "kimi-k1.5"
    else:
        return "kimi-k2.5"  # safe fallback — kimi-latest doesn't exist on Moonshot API
