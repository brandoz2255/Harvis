"""Moonshot AI API client for Kimi K2.5 integration."""

import os
import json
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from fastapi import HTTPException
import httpx

logger = logging.getLogger(__name__)

# Moonshot API configuration
MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"


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
                        f"Moonshot API error: {response.status_code} - {error_text}"
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Moonshot API error: {response.status_code}",
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
            # Log the actual Authorization header (with full key for debugging)
            logger.info(f"Moonshot API: Using API key length={len(self.api_key)}")
            logger.info(
                f"Moonshot API: API key repr={repr(self.api_key[:20])}...{repr(self.api_key[-5:])}"
            )
            logger.info(f"Moonshot API: Full headers={self.headers}")
            logger.info(f"Moonshot API: Request URL={self.base_url}/chat/completions")
            logger.info(f"Moonshot API: Request payload={payload}")

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
                        error_text = await response.aread()
                        logger.error(
                            f"Moonshot API streaming error: {response.status_code}"
                        )
                        logger.error(
                            f"Moonshot API error response: {error_text.decode()}"
                        )
                        raise HTTPException(
                            status_code=500,
                            detail=f"Moonshot API error: {response.status_code} - {error_text.decode()}",
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
