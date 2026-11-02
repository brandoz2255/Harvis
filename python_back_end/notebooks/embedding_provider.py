"""Where Notebooks gets its embeddings.

Two providers sit behind one small interface, chosen by ``NOTEBOOK_EMBED_PROVIDER``:

* ``ollama`` (default): the local model server. Batches go through ``/api/embed``;
  an older server that lacks it is served one text at a time through ``/api/embeddings``.
* ``openai``: any OpenAI-compatible ``/v1/embeddings`` endpoint. This sends the text of
  every source to that server, so it is never selected unless the operator sets it.
  ``NOTEBOOK_EMBED_BASE_URL`` is checked as a plain http(s) URL and, unless
  ``NOTEBOOK_EMBED_ALLOW_PRIVATE_URL=1``, dialled through the connect-time SSRF guard
  the Hermes endpoints use (public addresses only, no redirects, no env proxies).

Providers are blocking and never raise for a failed request: an entry that could not
be embedded is ``None``, so the caller decides how much loss is acceptable.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 8000
DEFAULT_REMOTE_URL = "https://api.openai.com/v1"
DEFAULT_REMOTE_MODEL = "text-embedding-3-small"
REMOTE_RETRIES = 2
REMOTE_BACKOFF_S = (1.0, 3.0)
_TRUTHY = ("1", "true", "yes", "on")


class ProviderConfigError(ValueError):
    """The configured provider cannot be used. The message is safe to show to the operator."""


@dataclass(frozen=True)
class EmbedResult:
    vectors: List[Optional[List[float]]]
    model: Optional[str]


def _clean_vector(value: Any) -> Optional[List[float]]:
    if not isinstance(value, list) or not value:
        return None
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        return None


class EmbeddingProvider(ABC):
    name: str
    model: str
    batch_size: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> EmbedResult:
        """Blocking. One vector (or ``None``) per input text, in order."""


class OllamaProvider(EmbeddingProvider):
    name = "ollama"
    batch_size = 16

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, texts: Sequence[str]) -> EmbedResult:
        inputs = [t[:MAX_INPUT_CHARS] for t in texts]
        if not inputs:
            return EmbedResult([], self.model)
        try:
            response = requests.post(
                f"{self.base_url}/api/embed", json={"model": self.model, "input": inputs}, timeout=120
            )
        except Exception:
            return EmbedResult([None] * len(inputs), self.model)
        if response.status_code == 200:
            try:
                rows = response.json().get("embeddings") or []
            except ValueError:
                rows = []
            if len(rows) == len(inputs):
                return EmbedResult([_clean_vector(r) for r in rows], self.model)
            return EmbedResult([None] * len(inputs), self.model)
        if response.status_code in (404, 405) and not _model_is_missing(response):
            # A server too old to have /api/embed: one text per request.
            return EmbedResult([self._embed_legacy(t) for t in inputs], self.model)
        return EmbedResult([None] * len(inputs), self.model)

    def _embed_legacy(self, text: str) -> Optional[List[float]]:
        try:
            response = requests.post(
                f"{self.base_url}/api/embeddings", json={"model": self.model, "prompt": text}, timeout=60
            )
            if response.status_code == 200:
                return _clean_vector(response.json().get("embedding"))
        except Exception:
            pass
        return None


def _model_is_missing(response) -> bool:
    """Ollama answers 404 both for an unknown model and for an endpoint it does not have;
    only the first has a JSON error that names the model."""
    try:
        error = str(response.json().get("error") or "").lower()
    except ValueError:
        return False
    return "model" in error


@dataclass(frozen=True)
class RemoteSettings:
    base_url: str
    model: str
    api_key: str
    dimensions: Optional[int]
    guarded: bool


def remote_settings() -> RemoteSettings:
    from plugins.hermes_ui.providers import EndpointValidationError, plain_http_url

    raw = (os.getenv("NOTEBOOK_EMBED_BASE_URL") or DEFAULT_REMOTE_URL).strip()
    try:
        base_url = plain_http_url(raw)
    except EndpointValidationError as exc:
        raise ProviderConfigError(f"NOTEBOOK_EMBED_BASE_URL is not usable: {exc}") from exc
    dimensions: Optional[int] = None
    raw_dim = (os.getenv("NOTEBOOK_EMBED_DIMENSIONS") or "").strip()
    if raw_dim:
        try:
            dimensions = int(raw_dim)
        except ValueError:
            dimensions = None
        if dimensions is None or not 1 <= dimensions <= 4096:
            raise ProviderConfigError("NOTEBOOK_EMBED_DIMENSIONS must be a whole number from 1 to 4096.")
    return RemoteSettings(
        base_url=base_url,
        model=(os.getenv("NOTEBOOK_EMBED_MODEL") or DEFAULT_REMOTE_MODEL).strip(),
        api_key=(os.getenv("NOTEBOOK_EMBED_API_KEY") or "").strip(),
        dimensions=dimensions,
        guarded=(os.getenv("NOTEBOOK_EMBED_ALLOW_PRIVATE_URL") or "").strip().lower() not in _TRUTHY,
    )


def remote_headers(settings: RemoteSettings) -> dict:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


def remote_sync_client(settings: RemoteSettings, **kwargs: Any):
    """The HTTP client for the remote endpoint: SSRF-guarded unless the operator allowed private URLs."""
    import httpx

    if settings.guarded:
        from plugins.hermes_ui.providers import guarded_sync_client

        return guarded_sync_client(**kwargs)
    return httpx.Client(**kwargs)


class OpenAICompatProvider(EmbeddingProvider):
    name = "openai"
    batch_size = 32

    def __init__(self, settings: RemoteSettings):
        self.settings = settings
        self.model = settings.model

    def embed(self, texts: Sequence[str]) -> EmbedResult:
        inputs = [t[:MAX_INPUT_CHARS] for t in texts]
        failed = EmbedResult([None] * len(inputs), self.model)
        if not inputs:
            return EmbedResult([], self.model)
        body: dict = {"model": self.model, "input": inputs, "encoding_format": "float"}
        if self.settings.dimensions:
            body["dimensions"] = self.settings.dimensions
        url = f"{self.settings.base_url}/embeddings"
        for attempt in range(REMOTE_RETRIES + 1):
            try:
                with remote_sync_client(self.settings, timeout=120.0) as client:
                    response = client.post(url, json=body, headers=remote_headers(self.settings))
            except Exception as exc:
                # The key is in a header, never in the exception text or the URL.
                logger.warning("Embedding request failed (%s)", type(exc).__name__)
                response = None
            if response is not None and response.status_code == 200:
                return self._parse(response, len(inputs)) or failed
            retryable = response is None or response.status_code == 429 or response.status_code >= 500
            if response is not None:
                logger.warning("Embedding server answered HTTP %s", response.status_code)
            if not retryable or attempt == REMOTE_RETRIES:
                break
            time.sleep(REMOTE_BACKOFF_S[min(attempt, len(REMOTE_BACKOFF_S) - 1)])
        return failed

    def _parse(self, response, expected: int) -> Optional[EmbedResult]:
        try:
            rows = response.json().get("data") or []
            ordered = sorted(rows, key=lambda r: r.get("index", 0))
        except (ValueError, AttributeError, TypeError):
            return None
        if len(ordered) != expected:
            return None
        return EmbedResult([_clean_vector(r.get("embedding")) for r in ordered], self.model)


def configured_provider_name() -> str:
    name = (os.getenv("NOTEBOOK_EMBED_PROVIDER") or "ollama").strip().lower()
    if name in ("openai", "openai-compatible", "openai_compatible"):
        return "openai"
    if name not in ("ollama", ""):
        logger.warning("Unknown NOTEBOOK_EMBED_PROVIDER %r; using ollama (documents stay on this machine)", name)
    return "ollama"


def remote_provider() -> OpenAICompatProvider:
    """The OpenAI-compatible provider from the environment. Raises ProviderConfigError."""
    return OpenAICompatProvider(remote_settings())
