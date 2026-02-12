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
        # Kimi models only support temperature=1.0
        payload = {
            "model": model,
            "messages": messages,
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
        # Kimi K2.5 only supports temperature=1.0
        payload = {
            "model": model,
            "messages": messages,
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


# Moonshot model mapping
MOONSHOT_MODELS = {
    "kimi-k2.5": "kimi-k2.5",
    "kimi-k2": "kimi-k2",
    "kimi-k1.5": "kimi-k1.5",
    "kimi-latest": "kimi-latest",
}


def is_moonshot_model(model_name: str) -> bool:
    """Check if a model name corresponds to a Moonshot/Kimi model."""
    model_lower = model_name.lower()
    return any(x in model_lower for x in ["kimi", "moonshot"])


def get_moonshot_model_id(model_name: str) -> str:
    """Get the actual Moonshot model ID from a model name."""
    model_lower = model_name.lower()

    if "k2.5" in model_lower or "k2-5" in model_lower:
        return "kimi-k2.5"
    elif "k2" in model_lower:
        return "kimi-k2"
    elif "k1.5" in model_lower or "k1-5" in model_lower:
        return "kimi-k1.5"
    else:
        return "kimi-latest"
