"""
RAG Chat Service for NotebookLM
Handles retrieval-augmented generation chat over notebook sources
"""

import logging
import os
import json
import re
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
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "codellama:7b")

# Models to try in order of preference (lighter/faster models first)
FALLBACK_MODELS = [
    "gpt-oss:latest",      # Usually fastest
    "codellama:7b",
    "deepseek-coder:6.7b",
    "mistral",
    "llama3.2",
    "qwen2.5",
]

# Performance settings
MAX_CONTEXT_CHARS = 8000  # Limit context to prevent slow processing
MAX_CHUNKS = 3  # Limit chunks to improve speed
LLM_TIMEOUT = 180  # 3 minute timeout for LLM calls


class RAGChatService:
    """
    RAG-based chat service for notebooks.
    Retrieves relevant chunks and generates grounded answers.
    """

    def __init__(self, manager: NotebookManager):
        self.manager = manager
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
        answer, reasoning = await self._generate_response(
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
            model_used=request.model
        )

        return NotebookChatResponse(
            answer=answer,
            reasoning=reasoning if request.include_reasoning else None,
            citations=final_citations,
            model_used=request.model,
            message_id=message.id,
            raw_chunks=chunks if request.include_reasoning else None
        )

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
3. Cite your sources using [Source: Title, Page/Section] format when referencing specific information
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

    async def _generate_response(
        self,
        query: str,
        system_prompt: str,
        context: str,
        model: str
    ) -> Tuple[str, Optional[str]]:
        """Generate response using Ollama with smart model fallback"""

        full_prompt = f"""{system_prompt}

SOURCES:
{context}

USER QUESTION: {query}

Please provide a helpful answer based on the sources above. Remember to cite sources when using specific information."""

        # Build list of models to try - requested model first, then fallbacks
        models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
        
        # Try local Ollama with multiple models
        for try_model in models_to_try:
            try:
                logger.info(f"Trying LLM with model: {try_model}")
                response = requests.post(
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
                    answer = data.get("response", "")

                    # Check for reasoning markers
                    reasoning = None
                    if "<think>" in answer and "</think>" in answer:
                        reasoning, answer = self._separate_thinking(answer)

                    logger.info(f"Successfully generated response with model: {try_model}")
                    return answer.strip(), reasoning
                    
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
                response = requests.post(
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
                    answer = data.get("response", "")
                    
                    reasoning = None
                    if "<think>" in answer and "</think>" in answer:
                        reasoning, answer = self._separate_thinking(answer)
                    
                    logger.info(f"Successfully generated response with cloud model: {try_model}")
                    return answer.strip(), reasoning
                    
                elif response.status_code == 404:
                    continue
                    
            except Exception as e:
                logger.warning(f"Cloud error with {try_model}: {e}")
                continue

        logger.error("All LLM models failed")
        return "I apologize, but I couldn't connect to any AI models. Please check that Ollama is running with a model loaded.", None

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

        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": request.model,
                    "prompt": f"{system_prompt}\n\nUser: {request.message}",
                    "stream": False
                },
                timeout=60
            )

            if response.status_code == 200:
                answer = response.json().get("response", "")
            else:
                answer = "I apologize, but I'm having trouble accessing your sources right now. Please try again in a moment."

        except Exception as e:
            logger.error(f"Non-RAG chat failed: {e}")
            answer = "I apologize, but I encountered an error. Please try again."

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
