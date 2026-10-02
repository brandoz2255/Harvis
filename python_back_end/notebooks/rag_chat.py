"""
RAG Chat Service for NotebookLM
Handles retrieval-augmented generation chat over notebook sources
"""

import logging
import os
import json
import re
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
import requests

from .models import (
    NotebookChatRequest, NotebookChatResponse, Citation, ChunkWithScore,
    MessageRole
)
from .manager import NotebookManager
from .ingestion import IngestionService

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.1:8b")

# Models to try in order of preference. These must be INSTALLED + reliable
# (non-reasoning) instruct models — reasoning models like gpt-oss intermittently
# emit all tokens into a separate `thinking` channel and leave `response` empty,
# which surfaces as a blank chat bubble. llama3.1:8b is the dependable default;
# the rest are installed fallbacks. (gpt-oss deliberately omitted here — if a user
# explicitly selects it, the empty-content guard below falls through to these.)
FALLBACK_MODELS = [
    "llama3.1:8b",
    "granite4.1:8b",
    "gemma4:e4b",
    "qwen3:4b",
]

# Reasoning models put their tokens in a separate `thinking` channel and can leave
# `response` blank, so they go last among discovered models rather than never.
_REASONING_HINTS = ("gpt-oss", "deepseek-r1", "qwq", "-r1")

# Performance settings
MAX_CONTEXT_CHARS = 8000  # Limit context to prevent slow processing
MAX_CHUNKS = 3  # Limit chunks to improve speed
LLM_TIMEOUT = 180  # 3 minute timeout for LLM calls


class RAGChatService:
    """
    RAG-based chat service for notebooks.
    Retrieves relevant chunks and generates grounded answers.
    """

    def __init__(self, manager: NotebookManager, allowed_models: Optional[List[str]] = None):
        self.manager = manager
        # The Harvis admin's model list for this person (Settings ▸ People); None = any.
        self.allowed_models = allowed_models
        self.ingestion_service = IngestionService(manager)

    async def chat(
        self,
        notebook_id: UUID,
        user_id: int,
        request: NotebookChatRequest
    ) -> NotebookChatResponse:
        """
        Process a chat message with RAG.
        1. Get embedding for the query
        2. Retrieve relevant chunks
        3. Build context-aware prompt
        4. Generate response with citations
        5. Save to chat history
        """
        # Get query embedding
        query_embedding = await self.ingestion_service.get_query_embedding(request.message)

        if not query_embedding:
            # Fall back to chat without RAG if embedding fails
            logger.warning("Could not get query embedding, chatting without RAG")
            return await self._chat_without_rag(
                notebook_id, user_id, request
            )

        # Retrieve relevant chunks (limit for performance)
        effective_top_k = min(request.top_k, MAX_CHUNKS)
        chunks = await self.manager.search_chunks(
            notebook_id,
            query_embedding,
            top_k=effective_top_k
        )

        if not chunks:
            # No chunks found - notebook might be empty
            return await self._chat_empty_notebook(
                notebook_id, user_id, request
            )

        # Build the RAG prompt
        system_prompt, context_text, citations = self._build_rag_prompt(chunks)

        # Generate response from LLM
        answer, reasoning, answered_by = await self._generate_response(
            request.message,
            system_prompt,
            context_text,
            request.model
        )

        # Process citations in the answer
        final_citations = self._extract_citations(answer, chunks)

        # Save user message to history
        await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.USER,
            content=request.message
        )

        # Save assistant message to history
        message = await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            reasoning=reasoning if request.include_reasoning else None,
            citations=final_citations,
            model_used=answered_by
        )

        return NotebookChatResponse(
            answer=answer,
            reasoning=reasoning if request.include_reasoning else None,
            citations=final_citations,
            model_used=answered_by,
            message_id=message.id,
            raw_chunks=chunks if request.include_reasoning else None
        )

    async def answer_for_session(
        self,
        notebook_id: UUID,
        message: str,
        model: str,
        source_ids: Optional[List[str]] = None,
        top_k: int = MAX_CHUNKS,
    ) -> Tuple[str, List[Citation]]:
        """Stateless RAG answer for an onb_compat chat session.

        Retrieval can be restricted to a subset of sources (open-notebook's
        fine-grained context control). The caller persists the turn to its own
        session tables. `source_ids=None` searches all of the notebook's chunks.
        """
        query_embedding = await self.ingestion_service.get_query_embedding(message)
        if not query_embedding:
            answer, _, _ = await self._generate_response(
                message,
                "You are a helpful research assistant. Sources could not be searched right now.",
                "", model,
            )
            return answer.strip(), []

        fetch_k = max(top_k * 5, top_k) if source_ids else top_k
        chunks = await self.manager.search_chunks(notebook_id, query_embedding, top_k=fetch_k)
        if source_ids:
            wanted = {str(s) for s in source_ids}
            chunks = [c for c in chunks if str(c.chunk.source_id) in wanted][:top_k]
        else:
            chunks = chunks[:top_k]

        if not chunks:
            return (
                "I don't have any sources in context to answer from. Add a source "
                "(or include one in the context) and ask again."
            ), []

        system_prompt, context_text, citations = self._build_rag_prompt(chunks)
        answer, _, _ = await self._generate_response(message, system_prompt, context_text, model)
        # Return the ORDERED context sources (citations[N-1] == "SOURCE N" in the
        # prompt) so the caller can map the model's [SOURCE N] markers to real
        # source ids for clickable inline citations.
        return answer.strip(), citations

    def _build_rag_prompt(
        self,
        chunks: List[ChunkWithScore]
    ) -> Tuple[str, str, List[Citation]]:
        """Build the RAG prompt with retrieved context"""

        system_prompt = """You are a helpful research assistant analyzing a notebook's sources.
Your task is to answer questions based ONLY on the provided source materials.

Important guidelines:
1. ONLY use information from the provided sources - do not use external knowledge
2. If the information is not in the sources, say "I don't see information about that in your sources"
3. Cite sources using the bracketed source NUMBER exactly as shown in the context headers — e.g. [SOURCE 1] or [SOURCE 2] (you may add the paragraph, e.g. [SOURCE 1: Para 3]). Always cite by the SOURCE number, never by the title.
4. Be direct and concise in your answers
5. If multiple sources provide relevant information, synthesize them together
6. Quote relevant passages when appropriate using quotation marks

Remember: You are a research assistant helping the user understand their uploaded materials."""

        # Build context from chunks
        context_parts = []
        citations = []

        for i, chunk_with_score in enumerate(chunks, 1):
            chunk = chunk_with_score.chunk
            source_title = chunk_with_score.source_title or "Unknown Source"

            # Build source reference
            metadata = chunk.metadata or {}
            page_info = ""
            if "page" in metadata:
                page_info = f", Page {metadata['page']}"
            elif "paragraphs" in metadata:
                page_info = f", Para {metadata['paragraphs'][0]+1}" if metadata['paragraphs'] else ""

            source_ref = f"[S{i}] {source_title}{page_info}"

            context_parts.append(f"""
--- SOURCE {i}: {source_title}{page_info} ---
{chunk.content}
---
""")

            citations.append(Citation(
                source_id=chunk.source_id,
                source_title=source_title,
                chunk_id=chunk.id,
                page=metadata.get("page"),
                section=metadata.get("section"),
                quote=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
            ))

        context_text = "\n".join(context_parts)
        
        # Limit context size for performance
        if len(context_text) > MAX_CONTEXT_CHARS:
            context_text = context_text[:MAX_CONTEXT_CHARS] + "\n\n[Context truncated for performance...]"
            logger.info(f"Context truncated from {len(context_text)} to {MAX_CONTEXT_CHARS} chars")

        return system_prompt, context_text, citations

    @staticmethod
    def _models_to_try(model: str, allowed: Optional[List[str]] = None) -> List[str]:
        """
        Requested model first, then the preferred fallbacks, then anything Ollama
        actually reports installed. The preferred names are only a preference — on a
        deploy that has none of them pulled, a list of four hardcoded names means
        every attempt 404s and the user gets "I couldn't connect to any AI models"
        while a perfectly good model sits installed.
        """
        ordered = [model] if model else []
        ordered += [m for m in FALLBACK_MODELS if m != model]

        try:
            response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
            installed = (
                [m.get("name") for m in response.json().get("models", []) if m.get("name")]
                if response.status_code == 200 else []
            )
        except Exception:
            logger.warning("Could not list Ollama models for chat fallback", exc_info=True)
            installed = []

        # Skip dedicated embedders — they cannot generate — and defer reasoning models.
        usable = [m for m in installed if "embed" not in m.lower()]
        usable.sort(key=lambda m: any(h in m.lower() for h in _REASONING_HINTS))
        for name in usable:
            if name not in ordered:
                ordered.append(name)
        return ordered if allowed is None else [m for m in ordered if m in allowed]

    async def _generate_response(
        self,
        query: str,
        system_prompt: str,
        context: str,
        model: str
    ) -> Tuple[str, Optional[str], str]:
        """Generate a response, returning (answer, reasoning, model that actually answered)."""

        full_prompt = f"""{system_prompt}

SOURCES:
{context}

USER QUESTION: {query}

Please provide a helpful answer based on the sources above. Remember to cite sources when using specific information."""

        models_to_try = self._models_to_try(model, self.allowed_models)

        # Try local Ollama with multiple models
        for try_model in models_to_try:
            try:
                logger.info(f"Trying LLM with model: {try_model}")
                # Offload the blocking HTTP call to a thread so the async event loop
                # (and the rest of the backend) isn't frozen for the whole generation.
                response = await asyncio.to_thread(
                    requests.post,
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": try_model,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.7,
                            "top_p": 0.9,
                            "num_predict": 512,  # Limit response length for speed
                            "num_ctx": 4096,     # Smaller context window
                        }
                    },
                    timeout=LLM_TIMEOUT
                )

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("response", "") or ""

                    # Reasoning models (gpt-oss, etc.) may put chain-of-thought in a
                    # separate Ollama `thinking` field and/or inline <think>...</think>.
                    reasoning = data.get("thinking") or None
                    if "<think>" in answer and "</think>" in answer:
                        inline_reasoning, answer = self._separate_thinking(answer)
                        reasoning = reasoning or inline_reasoning

                    answer = answer.strip()
                    if not answer:
                        # Reasoning-only response (all tokens went to the thinking
                        # channel, `response` is blank). Don't persist an empty
                        # bubble — fall through to the next (non-reasoning) model.
                        logger.warning(
                            f"Model {try_model} returned empty content "
                            f"(reasoning-only); trying next model"
                        )
                        continue

                    logger.info(f"Successfully generated response with model: {try_model}")
                    return answer, reasoning, try_model

                elif response.status_code == 404:
                    logger.debug(f"Model {try_model} not found locally, trying next...")
                    continue
                else:
                    logger.warning(f"LLM request with {try_model} failed: {response.status_code}")
                    continue

            except requests.exceptions.ConnectionError:
                logger.warning(f"Local Ollama not accessible")
                break
            except Exception as e:
                logger.warning(f"Error with model {try_model}: {e}")
                continue

        # Try cloud Ollama as final fallback
        for try_model in models_to_try:
            try:
                logger.info(f"Trying cloud Ollama with model: {try_model}")
                response = await asyncio.to_thread(
                    requests.post,
                    f"{CLOUD_OLLAMA_URL}/api/generate",
                    json={
                        "model": try_model,
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {
                            "num_predict": 512,
                            "num_ctx": 4096,
                        }
                    },
                    timeout=LLM_TIMEOUT
                )

                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("response", "") or ""

                    reasoning = data.get("thinking") or None
                    if "<think>" in answer and "</think>" in answer:
                        inline_reasoning, answer = self._separate_thinking(answer)
                        reasoning = reasoning or inline_reasoning

                    answer = answer.strip()
                    if not answer:
                        logger.warning(
                            f"Cloud model {try_model} returned empty content "
                            f"(reasoning-only); trying next model"
                        )
                        continue

                    logger.info(f"Successfully generated response with cloud model: {try_model}")
                    return answer, reasoning, try_model

                elif response.status_code == 404:
                    continue
                    
            except Exception as e:
                logger.warning(f"Cloud error with {try_model}: {e}")
                continue

        logger.error("All LLM models failed; tried %s", ", ".join(models_to_try))
        return (
            "I couldn't reach any language model. Check that Ollama is running "
            "with at least one model pulled.",
            None,
            model,
        )

    def _separate_thinking(self, text: str) -> Tuple[str, str]:
        """Separate thinking/reasoning from final answer"""
        reasoning = ""
        remaining = text

        while "<think>" in remaining and "</think>" in remaining:
            start = remaining.find("<think>")
            end = remaining.find("</think>")

            if start != -1 and end != -1 and end > start:
                thought = remaining[start + len("<think>"):end].strip()
                if thought:
                    reasoning += thought + "\n\n"
                remaining = remaining[:start] + remaining[end + len("</think>"):]
            else:
                break

        return reasoning.strip(), remaining.strip()

    def _extract_citations(
        self,
        answer: str,
        chunks: List[ChunkWithScore]
    ) -> List[Citation]:
        """Extract and validate citations from the answer"""
        citations = []

        # Look for citation patterns like [S1], [Source: ...], etc.
        citation_patterns = [
            r'\[S(\d+)\]',
            r'\[Source:\s*([^\]]+)\]',
            r'\[(\d+)\]'
        ]

        mentioned_indices = set()

        for pattern in citation_patterns:
            matches = re.findall(pattern, answer)
            for match in matches:
                if match.isdigit():
                    idx = int(match) - 1
                    if 0 <= idx < len(chunks):
                        mentioned_indices.add(idx)

        # Build citations from mentioned chunks
        for idx in mentioned_indices:
            chunk_with_score = chunks[idx]
            chunk = chunk_with_score.chunk
            metadata = chunk.metadata or {}

            citations.append(Citation(
                source_id=chunk.source_id,
                source_title=chunk_with_score.source_title,
                chunk_id=chunk.id,
                page=metadata.get("page"),
                section=metadata.get("section"),
                quote=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content
            ))

        # If no explicit citations found but answer uses sources, include top chunks
        if not citations and chunks:
            # Include top 3 most relevant chunks as implicit citations
            for chunk_with_score in chunks[:3]:
                if chunk_with_score.score > 0.5:  # Only if reasonably similar
                    chunk = chunk_with_score.chunk
                    metadata = chunk.metadata or {}

                    citations.append(Citation(
                        source_id=chunk.source_id,
                        source_title=chunk_with_score.source_title,
                        chunk_id=chunk.id,
                        page=metadata.get("page"),
                        section=metadata.get("section")
                    ))

        return citations

    async def _chat_without_rag(
        self,
        notebook_id: UUID,
        user_id: int,
        request: NotebookChatRequest
    ) -> NotebookChatResponse:
        """Chat without RAG when embeddings fail"""

        system_prompt = """You are a helpful research assistant. The user has a notebook with uploaded sources,
but I couldn't search them right now. Please let the user know and offer to help with general questions.
If they're asking about their sources, suggest they try again or check if their sources are fully processed."""

        answer = ""
        used_model = request.model
        # Same fallback chain as the RAG path — this used to call one hardcoded model
        # with no fallback, so a deploy without it got a bare 404 here.
        for try_model in self._models_to_try(request.model, self.allowed_models):
            try:
                response = await asyncio.to_thread(
                    requests.post,
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": try_model,
                        "prompt": f"{system_prompt}\n\nUser: {request.message}",
                        "stream": False
                    },
                    timeout=60
                )
            except Exception:
                logger.warning(f"Non-RAG chat failed with {try_model}", exc_info=True)
                continue

            if response.status_code == 200:
                answer = (response.json().get("response") or "").strip()
                if answer:
                    used_model = try_model
                    break
            elif response.status_code == 404:
                logger.debug(f"Model {try_model} not found locally, trying next...")
            else:
                logger.warning(f"Non-RAG chat with {try_model} failed: {response.status_code}")

        if not answer:
            logger.error("Non-RAG chat: every model failed")
            answer = (
                "I couldn't search this notebook's sources, and no language model "
                "answered. Check that Ollama is running with a model pulled."
            )

        # Save to history
        await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.USER,
            content=request.message
        )

        message = await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            model_used=used_model
        )

        return NotebookChatResponse(
            answer=answer,
            citations=[],
            model_used=used_model,
            message_id=message.id
        )

    async def _chat_empty_notebook(
        self,
        notebook_id: UUID,
        user_id: int,
        request: NotebookChatRequest
    ) -> NotebookChatResponse:
        """Handle chat when notebook has no sources or chunks"""

        answer = """I don't have any sources to search in this notebook yet.

To use the RAG chat feature, please:
1. Upload some documents (PDFs, text files, or URLs)
2. Wait for them to finish processing (you'll see a "Ready" status)
3. Then ask your questions!

I can only answer questions based on the sources you provide in this notebook."""

        # Save to history
        await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.USER,
            content=request.message
        )

        message = await self.manager.add_chat_message(
            notebook_id=notebook_id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=answer,
            model_used=request.model
        )

        return NotebookChatResponse(
            answer=answer,
            citations=[],
            model_used=request.model,
            message_id=message.id
        )
