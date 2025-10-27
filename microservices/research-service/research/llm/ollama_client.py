"""
Unified Ollama client with cloud fallback and error handling.

Wraps the existing make_ollama_request function with additional features:
- Automatic model fallback
- Response validation
- Token counting
- Rate limiting
- Streaming support
"""

import asyncio
import logging
import os
import time
from typing import Optional, Dict, Any, List, Union, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import json

# Will import from your existing code once integrated
# from ..main import make_ollama_request

logger = logging.getLogger(__name__)


class GenerationError(Exception):
    """Custom exception for LLM generation errors"""
    pass


class ModelTier(Enum):
    """Model performance tiers for different tasks"""
    SMALL = "small"      # Fast, simple tasks (summaries, extraction)
    MEDIUM = "medium"    # Balanced performance (analysis, synthesis)  
    LARGE = "large"      # Complex reasoning (verification, planning)


@dataclass
class ModelResponse:
    """Structured response from LLM generation"""
    content: str
    model: str
    success: bool
    processing_time: float
    token_count: Optional[int] = None
    metadata: Dict[str, Any] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class OllamaClient:
    """
    Enhanced Ollama client with smart fallbacks and error handling.
    
    Wraps your existing make_ollama_request function with additional
    reliability and monitoring features.
    """
    
    def __init__(
        self,
        base_url: str = os.getenv("OLLAMA_URL", "http://ollama:11434"),
        default_model: str = "mistral",
        fallback_models: Optional[List[str]] = None,
        max_retries: int = 3,
        request_timeout: int = 60,
        rate_limit_delay: float = 0.1
    ):
        self.base_url = base_url
        self.default_model = default_model
        self.fallback_models = fallback_models or ["llama3.2:3b", "qwen2.5:7b"]
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        self.rate_limit_delay = rate_limit_delay
        
        # Stats tracking
        self._request_count = 0
        self._total_tokens = 0
        self._total_time = 0.0
        self._error_count = 0
    
    def _estimate_token_count(self, text: str) -> int:
        """Rough token count estimation (words / 0.75)"""
        return int(len(text.split()) / 0.75)
    
    def _validate_response(self, response: Any) -> bool:
        """Validate that response contains expected content"""
        if not response:
            return False
        
        # If response is string, it's valid
        if isinstance(response, str):
            return len(response.strip()) > 0
        
        # If response is dict, check for content key
        if isinstance(response, dict):
            return bool(response.get("content") or response.get("response"))
        
        return False
    
    def _extract_content(self, response: Any) -> str:
        """Extract text content from various response formats"""
        if isinstance(response, str):
            return response.strip()
        
        if isinstance(response, dict):
            # Try different possible keys
            for key in ["content", "response", "text", "output"]:
                if key in response and response[key]:
                    return str(response[key]).strip()
        
        return str(response).strip()
    
    async def _make_request_with_fallback(
        self,
        prompt: str,
        model: str,
        **kwargs
    ) -> ModelResponse:
        """Make request with automatic model fallback"""
        
        models_to_try = [model] + [m for m in self.fallback_models if m != model]
        last_error = None
        
        for attempt_model in models_to_try:
            try:
                start_time = time.time()
                
                # This would call your existing make_ollama_request function
                # response = await make_ollama_request(prompt, attempt_model, **kwargs)
                
                # Placeholder for integration with your existing code
                # For now, simulate a response
                await asyncio.sleep(0.1)  # Simulate processing time
                response = f"Response to '{prompt[:50]}...' using model {attempt_model}"
                
                processing_time = time.time() - start_time
                
                # Validate response
                if not self._validate_response(response):
                    raise GenerationError(f"Empty or invalid response from {attempt_model}")
                
                content = self._extract_content(response)
                token_count = self._estimate_token_count(content)
                
                # Update stats
                self._request_count += 1
                self._total_tokens += token_count
                self._total_time += processing_time
                
                # Rate limiting
                if self.rate_limit_delay > 0:
                    await asyncio.sleep(self.rate_limit_delay)
                
                return ModelResponse(
                    content=content,
                    model=attempt_model,
                    success=True,
                    processing_time=processing_time,
                    token_count=token_count,
                    metadata={
                        "attempt_number": models_to_try.index(attempt_model) + 1,
                        "fallback_used": attempt_model != model
                    }
                )
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Request failed with model {attempt_model}: {last_error}")
                continue
        
        # All models failed
        self._error_count += 1
        return ModelResponse(
            content="",
            model=model,
            success=False,
            processing_time=0.0,
            error=f"All models failed. Last error: {last_error}"
        )
    
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> ModelResponse:
        """
        Generate text using Ollama with fallback support.
        
        Args:
            prompt: Input prompt text
            model: Model to use (defaults to default_model)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters for the model
            
        Returns:
            ModelResponse with generated content
        """
        model = model or self.default_model
        
        # Add generation parameters
        generation_kwargs = {
            "temperature": temperature,
            **kwargs
        }
        
        if max_tokens:
            generation_kwargs["max_tokens"] = max_tokens
        
        logger.debug(f"Generating with model {model}, prompt length: {len(prompt)}")
        
        return await self._make_request_with_fallback(
            prompt=prompt,
            model=model,
            **generation_kwargs
        )
    
    async def generate_with_retries(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> ModelResponse:
        """Generate with explicit retry logic"""
        max_retries = max_retries or self.max_retries
        
        for attempt in range(max_retries):
            response = await self.generate(prompt, model, **kwargs)
            
            if response.success:
                return response
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.info(f"Retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time)
        
        # All retries failed
        return response
    
    async def batch_generate(
        self,
        prompts: List[str],
        model: Optional[str] = None,
        max_concurrent: int = 3,
        **kwargs
    ) -> List[ModelResponse]:
        """Generate responses for multiple prompts concurrently"""
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def bounded_generate(prompt: str) -> ModelResponse:
            async with semaphore:
                return await self.generate(prompt, model, **kwargs)
        
        logger.info(f"Starting batch generation for {len(prompts)} prompts")
        start_time = time.time()
        
        responses = await asyncio.gather(
            *[bounded_generate(prompt) for prompt in prompts],
            return_exceptions=True
        )
        
        # Handle any exceptions
        results = []
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                results.append(ModelResponse(
                    content="",
                    model=model or self.default_model,
                    success=False,
                    processing_time=0.0,
                    error=str(response)
                ))
            else:
                results.append(response)
        
        total_time = time.time() - start_time
        successful = sum(1 for r in results if r.success)
        
        logger.info(f"Batch completed in {total_time:.2f}s: {successful}/{len(prompts)} successful")
        
        return results
    
    async def stream_generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Stream generation (placeholder for streaming support).
        
        Would integrate with Ollama streaming API when available.
        """
        # Placeholder - would implement actual streaming
        response = await self.generate(prompt, model, **kwargs)
        
        if response.success:
            # Simulate streaming by yielding chunks
            words = response.content.split()
            for i in range(0, len(words), 5):
                chunk = " ".join(words[i:i+5])
                yield chunk + " "
                await asyncio.sleep(0.05)  # Simulate streaming delay
    
    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        # This would query Ollama for available models
        # For now, return default list
        return [self.default_model] + self.fallback_models
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client usage statistics"""
        return {
            "total_requests": self._request_count,
            "total_tokens": self._total_tokens,
            "total_processing_time": self._total_time,
            "error_count": self._error_count,
            "success_rate": 1 - (self._error_count / max(1, self._request_count)),
            "avg_tokens_per_request": self._total_tokens / max(1, self._request_count),
            "avg_processing_time": self._total_time / max(1, self._request_count)
        }
    
    def reset_stats(self):
        """Reset usage statistics"""
        self._request_count = 0
        self._total_tokens = 0
        self._total_time = 0.0
        self._error_count = 0


# Convenience functions
async def quick_generate(
    prompt: str,
    model: str = "mistral",
    max_retries: int = 2
) -> str:
    """Quick text generation with minimal setup"""
    client = OllamaClient(default_model=model, max_retries=max_retries)
    response = await client.generate(prompt)
    
    if response.success:
        return response.content
    else:
        raise GenerationError(f"Generation failed: {response.error}")


async def batch_quick_generate(
    prompts: List[str],
    model: str = "mistral",
    max_concurrent: int = 3
) -> List[str]:
    """Quick batch generation returning just content strings"""
    client = OllamaClient(default_model=model)
    responses = await client.batch_generate(prompts, max_concurrent=max_concurrent)
    
    return [r.content if r.success else "" for r in responses]