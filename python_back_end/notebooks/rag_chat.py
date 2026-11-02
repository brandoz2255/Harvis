"""
RAG Chat Service for NotebookLM
Handles retrieval-augmented generation chat over notebook sources
"""

import logging
import os
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
from .chat_config import default_config, normalize_config
from .chat_history import load_recent_turns
from .grounding import REFUSAL_TEXT, is_grounded, min_similarity
from .rag_answer import AnswerResult, Retrieval, is_unsupported, resolve_answer
from .rag_llm import post_chat
from .query_rewrite import REWRITE_TIMEOUT, rewrite_followup
from .rag_limits import NUM_CTX, clamp_top_k, rag_chunk_limit
from .rag_prompt import build_messages as _build_messages
from .rag_prompt import build_prompt_parts, compose_messages, num_predict_for
from .summary_context import SummaryPassages, context_report, is_overview_question

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
CLOUD_OLLAMA_URL = os.getenv("OLLAMA_CLOUD_URL", "").rstrip("/")
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
_REASONING_HINTS = ("gpt-oss", "deepseek-r1", "qwq", "-r1", "qwen3")

# Performance settings. How many passages an answer retrieves and how many characters
# of them the prompt carries are set in rag_limits (NOTEBOOK_RAG_CHUNKS, NOTEBOOK_RAG_CONTEXT_CHARS).
LLM_TIMEOUT = 180  # 3 minute timeout for LLM calls
DEFAULT_NUM_PREDICT = 512  # reply cap; a notebook's chat length can raise or lower it

CHAT_SYSTEM_NO_SOURCES = "You are a helpful research assistant. Sources could not be searched right now."


NO_SUMMARIES_REPLY = (
    "None of the sources set to Summary have a summary yet. Set them to Full, or try again once "
    "their summaries have finished."
)


def _wanted_sources(source_ids: Optional[List[str]]) -> Optional[set]:
    return {str(s) for s in source_ids} if source_ids else None


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

    # ─── shared steps (the streaming route reuses retrieve_context / build_messages) ───

    async def load_history(
        self, notebook_id: UUID, user_id: Optional[int], session_id: Any = None
    ) -> List[Dict[str, str]]:
        """Recent turns of this person's conversation, oldest first; [] if unavailable."""
        pool = getattr(self.manager, "db_pool", None)
        if pool is None or user_id is None:
            return []
        try:
            return await load_recent_turns(pool, notebook_id=notebook_id, user_id=user_id, session_id=session_id)
        except Exception:
            logger.warning("Could not load chat history; answering without it", exc_info=True)
            return []

    async def load_config(self, notebook_id: UUID, user_id: Optional[int]) -> Dict[str, Optional[str]]:
        """The notebook's {persona, style, length, output_language}; defaults if unavailable."""
        if user_id is None:
            return default_config()
        getter = getattr(self.manager, "get_chat_config", None)
        if getter is None:
            return default_config()
        try:
            return normalize_config(await getter(notebook_id, user_id))
        except Exception:
            logger.warning("Could not load chat config; using defaults", exc_info=True)
            return default_config()

    async def retrieve(
        self,
        notebook_id: UUID,
        user_id: Optional[int],
        message: str,
        *,
        history: Optional[List[Dict[str, str]]] = None,
        top_k: Optional[int] = None,
        source_ids: Optional[List[str]] = None,
        summary_source_ids: Optional[List[str]] = None,
        allow_overview: bool = False,
        model: Optional[str] = None,
    ) -> Retrieval:
        """Rewrite a follow-up into a standalone query, embed it and fetch the passages.

        ``summary_source_ids`` are sources at the Summary level: they are not searched, their stored
        summary is added as a passage instead (one without a summary is left out and reported). A
        broad overview question (only with ``allow_overview``) skips the search and similarity floor
        and reads every source's summary, or the start of its text when it has none.
        """
        top_k = clamp_top_k(top_k) if top_k else rag_chunk_limit()
        summary_ids = list(dict.fromkeys(str(s) for s in (summary_source_ids or [])))
        overview = allow_overview and is_overview_question(message)
        loader = getattr(self.manager, "source_summaries", None) if (summary_ids or overview) and user_id is not None else None

        if loader is not None and overview:
            whole = await self._overview(loader, notebook_id, user_id, message, source_ids)
            if whole is not None:
                return whole

        summaries = SummaryPassages()
        unreadable: List[str] = []
        if summary_ids:
            if loader is None:
                unreadable = summary_ids
            else:
                try:
                    summaries = await loader(notebook_id, user_id, summary_ids)
                except Exception:
                    logger.warning("Could not read source summaries; leaving those sources out", exc_info=True)
                    unreadable = summary_ids

        scope = [s for s in (source_ids or []) if str(s) not in set(summary_ids)] if source_ids else None
        if source_ids and not scope:
            # Everything the person left on is at the Summary level: nothing to search.
            retrieval = Retrieval(chunks=[], rewritten_query=message, embedded=True)
        else:
            query = await rewrite_followup(
                message, history, lambda prompt: self._complete_short(prompt, model or DEFAULT_MODEL)
            )
            embedding = await self.ingestion_service.get_query_embedding(query)
            chunks = await self._search(
                notebook_id, user_id, query, embedding, top_k, scope, exclude=summary_ids or None
            )
            retrieval = Retrieval(chunks=chunks, rewritten_query=query, embedded=bool(embedding))

        if summary_ids:
            retrieval.report = context_report("summary", summaries, unreadable=unreadable)
            if summaries.chunks:
                retrieval.chunks = summaries.chunks + retrieval.chunks
                retrieval.floor_exempt = True
            elif not retrieval.chunks and retrieval.embedded:
                retrieval.empty_reply = NO_SUMMARIES_REPLY
        return retrieval

    async def _overview(
        self, loader: Any, notebook_id: UUID, user_id: int, message: str, source_ids: Optional[List[str]]
    ) -> Optional[Retrieval]:
        """Every source's summary (or its opening) for a broad question; None to search as usual."""
        try:
            passages = await loader(notebook_id, user_id, source_ids or None, text_fallback=True)
        except Exception:
            logger.warning("Could not read source summaries for an overview; searching instead", exc_info=True)
            return None
        if not passages.chunks:
            return None
        return Retrieval(
            chunks=passages.chunks, rewritten_query=message, embedded=True, floor_exempt=True,
            report=context_report("overview", passages),
        )

    async def retrieve_context(
        self,
        notebook_id: UUID,
        user_id: Optional[int],
        message: str,
        *,
        history: Optional[List[Dict[str, str]]] = None,
        top_k: Optional[int] = None,
        source_ids: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> Tuple[List[ChunkWithScore], str]:
        """``(chunks, rewritten_query)``; use ``retrieve`` when you also need to know if embedding failed."""
        found = await self.retrieve(
            notebook_id, user_id, message, history=history, top_k=top_k, source_ids=source_ids, model=model
        )
        return found.chunks, found.rewritten_query

    def build_messages(
        self,
        notebook: Any,
        chunks: List[ChunkWithScore],
        history: Optional[List[Dict[str, str]]],
        message: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """``[system (rules + sources), *prior turns, user]`` for a grounded answer."""
        return _build_messages(notebook, chunks, history, message, config)

    async def _search(
        self,
        notebook_id: UUID,
        user_id: Optional[int],
        query: str,
        embedding: Optional[List[float]],
        top_k: int,
        source_ids: Optional[List[str]],
        exclude: Optional[List[str]] = None,
    ) -> List[ChunkWithScore]:
        wanted = _wanted_sources(source_ids)
        skipped = _wanted_sources(exclude) or set()
        hybrid = getattr(self.manager, "search_chunks_hybrid", None) if user_id is not None else None
        if hybrid is not None:
            try:
                extra = {"exclude_source_ids": list(skipped)} if skipped else {}
                chunks = await hybrid(notebook_id, user_id, query, embedding, top_k, source_ids=source_ids, **extra)
            except Exception:
                logger.warning("Hybrid search failed; falling back to vector search", exc_info=True)
            else:
                return [c for c in chunks if (not wanted or str(c.chunk.source_id) in wanted)
                        and str(c.chunk.source_id) not in skipped][:top_k]

        if not embedding:
            return []
        fetch_k = max(top_k * 5, top_k) if wanted or skipped else top_k
        chunks = await self.manager.search_chunks(notebook_id, embedding, top_k=fetch_k)
        if wanted:
            chunks = [c for c in chunks if str(c.chunk.source_id) in wanted]
        if skipped:
            chunks = [c for c in chunks if str(c.chunk.source_id) not in skipped]
        # Here the score is a cosine similarity, which is what the grounding floor compares.
        return [c if c.vector_score is not None else c.model_copy(update={"vector_score": c.score})
                for c in chunks[:top_k]]

    async def _save_exchange(
        self, notebook_id: UUID, user_id: int, question: str, answer: str, **assistant_fields: Any
    ):
        """Save the question, then the answer; returns the saved answer message."""
        await self.manager.add_chat_message(
            notebook_id=notebook_id, user_id=user_id, role=MessageRole.USER, content=question
        )
        return await self.manager.add_chat_message(
            notebook_id=notebook_id, user_id=user_id, role=MessageRole.ASSISTANT, content=answer,
            **assistant_fields
        )

    @staticmethod
    def _generation_extras(history: Optional[List[Dict[str, str]]], config: Dict[str, Any]) -> Dict[str, Any]:
        """Keyword arguments for ``_generate_response`` beyond the four every call passes."""
        extras: Dict[str, Any] = {}
        if history:
            extras["history"] = history
        num_predict = num_predict_for(config)
        if num_predict:
            extras["num_predict"] = num_predict
        return extras

    # ─── chat ──────────────────────────────────────────────────────────────────

    async def chat(
        self,
        notebook_id: UUID,
        user_id: int,
        request: NotebookChatRequest
    ) -> NotebookChatResponse:
        """
        Process a chat message with RAG.
        1. Load the notebook's chat settings and recent turns
        2. Retrieve relevant chunks (a follow-up is rewritten into a standalone query first)
        3. Refuse when nothing retrieved is close enough to the question
        4. Generate a response from the sources, prior turns and question
        5. Save to chat history
        """
        # Refuse before retrieving: search_chunks filters on the notebook id alone.
        notebook = await self.manager.get_notebook(notebook_id, user_id)
        config = await self.load_config(notebook_id, user_id)
        # Read the history before this turn is saved, or the question would be in its own history.
        history = await self.load_history(notebook_id, user_id)

        found = await self.retrieve(
            notebook_id, user_id, request.message, history=history, top_k=request.top_k,
            source_ids=request.source_ids, summary_source_ids=request.summary_source_ids,
            allow_overview=True, model=request.model
        )
        if not found.chunks:
            if found.empty_reply:
                message = await self._save_exchange(
                    notebook_id, user_id, request.message, found.empty_reply, model_used=request.model
                )
                return NotebookChatResponse(
                    answer=found.empty_reply, citations=[], model_used=request.model, message_id=message.id,
                    context=found.report,
                )
            if not found.embedded:
                # Fall back to chat without RAG if embedding fails
                logger.warning("Could not get query embedding, chatting without RAG")
                return await self._chat_without_rag(notebook_id, user_id, request)
            # No chunks found - notebook might be empty
            return await self._chat_empty_notebook(notebook_id, user_id, request)

        if not found.floor_exempt and not is_grounded(found.chunks):
            logger.info("Refusing: best passage below similarity floor %.2f (notebook %s)", min_similarity(), notebook_id)
            message = await self._save_exchange(
                notebook_id, user_id, request.message, REFUSAL_TEXT, model_used=request.model
            )
            return NotebookChatResponse(
                answer=REFUSAL_TEXT, citations=[], model_used=request.model, message_id=message.id,
                raw_chunks=found.chunks if request.include_reasoning else None, refused=True
            )

        system_prompt, context_text, _ = build_prompt_parts(notebook, found.chunks, config)
        answer, reasoning, answered_by = await self._generate_response(
            request.message, system_prompt, context_text, request.model,
            **self._generation_extras(history, config)
        )

        answer, final_citations, unsupported = resolve_answer(answer, found.chunks)

        message = await self._save_exchange(
            notebook_id, user_id, request.message, answer,
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
            raw_chunks=found.chunks if request.include_reasoning else None,
            unsupported=unsupported,
            context=found.report,
        )

    async def answer_for_session_detailed(
        self,
        notebook_id: UUID,
        message: str,
        model: str,
        source_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        *,
        user_id: Optional[int] = None,
        history: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> AnswerResult:
        """``answer_for_session`` with the flags (``refused``, ``unsupported``) kept.

        ``user_id`` turns on hybrid retrieval and the notebook's saved chat settings; the
        caller must already have checked that this person owns the notebook. ``history`` is
        the session's prior turns (``chat_history.load_recent_turns``), ``config`` overrides
        the saved settings.
        """
        if config is None:
            config = await self.load_config(notebook_id, user_id)
        else:
            config = normalize_config(config)
        found = await self.retrieve(
            notebook_id, user_id, message, history=history, top_k=top_k, source_ids=source_ids, model=model
        )
        extras = self._generation_extras(history, config)

        if not found.chunks and not found.embedded:
            answer, _, answered_by = await self._generate_response(
                message, CHAT_SYSTEM_NO_SOURCES, "", model, **extras
            )
            return AnswerResult(answer.strip(), [], model_used=answered_by, rewritten_query=found.rewritten_query)

        if not found.chunks:
            return AnswerResult(
                "I don't have any sources in context to answer from. Add a source "
                "(or include one in the context) and ask again.",
                [], model_used=model, rewritten_query=found.rewritten_query,
            )

        if not is_grounded(found.chunks):
            logger.info("Refusing: best passage below similarity floor %.2f (notebook %s)", min_similarity(), notebook_id)
            return AnswerResult(
                REFUSAL_TEXT, [], refused=True, model_used=model, chunks=found.chunks,
                rewritten_query=found.rewritten_query,
            )

        system_prompt, context_text, citations = build_prompt_parts(None, found.chunks, config)
        answer, reasoning, answered_by = await self._generate_response(
            message, system_prompt, context_text, model, **extras
        )
        # Return the ORDERED context sources (citations[N-1] == "SOURCE N" in the
        # prompt) so the caller can map the model's [SOURCE N] markers to real
        # source ids for clickable inline citations.
        return AnswerResult(
            answer.strip(), citations, unsupported=is_unsupported(answer, found.chunks),
            reasoning=reasoning, model_used=answered_by, chunks=found.chunks,
            rewritten_query=found.rewritten_query,
        )

    async def answer_for_session(
        self,
        notebook_id: UUID,
        message: str,
        model: str,
        source_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
        *,
        user_id: Optional[int] = None,
        history: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, List[Citation]]:
        """Stateless RAG answer for an onb_compat chat session.

        Retrieval can be restricted to a subset of sources (open-notebook's
        fine-grained context control). The caller persists the turn to its own
        session tables. `source_ids=None` searches all of the notebook's chunks.
        """
        result = await self.answer_for_session_detailed(
            notebook_id, message, model, source_ids, top_k,
            user_id=user_id, history=history, config=config,
        )
        return result.answer, result.citations

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
            from owui_compat.ollama_hosts import drop_cloud

            installed = (
                [m.get("name") for m in drop_cloud(response.json().get("models", [])) if m.get("name")]
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


    async def _complete_short(self, prompt: str, model: str) -> Optional[str]:
        """One short local completion (the query rewrite). Never leaves the machine."""
        models = await asyncio.to_thread(self._models_to_try, model, self.allowed_models)
        options = {"temperature": 0, "num_predict": 80, "num_ctx": NUM_CTX}  # same num_ctx: no model reload
        for try_model in models[:2]:
            try:
                got = await post_chat(
                    OLLAMA_URL, try_model, [{"role": "user", "content": prompt}], options, REWRITE_TIMEOUT
                )
            except requests.exceptions.ConnectionError:
                return None
            except Exception:
                logger.debug("Query rewrite with %s failed", try_model, exc_info=True)
                continue
            if got:
                return got[0]
        return None

    async def _generate_response(
        self,
        query: str,
        system_prompt: str,
        context: str,
        model: str,
        history: Optional[List[Dict[str, str]]] = None,
        num_predict: Optional[int] = None,
    ) -> Tuple[str, Optional[str], str]:
        """Generate a response, returning (answer, reasoning, model that actually answered)."""
        messages = compose_messages(system_prompt, context, history, query)
        options = {
            "temperature": 0.7,
            "top_p": 0.9,
            "num_predict": num_predict or DEFAULT_NUM_PREDICT,
            "num_ctx": NUM_CTX,
        }
        models_to_try = self._models_to_try(model, self.allowed_models)

        # Try local Ollama with multiple models
        for try_model in models_to_try:
            try:
                logger.info(f"Trying LLM with model: {try_model}")
                got = await post_chat(OLLAMA_URL, try_model, messages, options, LLM_TIMEOUT)
            except requests.exceptions.ConnectionError:
                logger.warning("Local Ollama not accessible")
                break
            except Exception as e:
                logger.warning(f"Error with model {try_model}: {e}")
                continue
            if got:
                logger.info(f"Successfully generated response with model: {try_model}")
                return got[0], got[1], try_model

        # Cloud fallback only when an operator configured one; the prompt carries source text.
        for try_model in (models_to_try if CLOUD_OLLAMA_URL else []):
            try:
                logger.info(f"Trying cloud Ollama with model: {try_model}")
                got = await post_chat(CLOUD_OLLAMA_URL, try_model, messages, options, LLM_TIMEOUT)
            except Exception as e:
                logger.warning(f"Cloud error with {try_model}: {e}")
                continue
            if got:
                logger.info(f"Successfully generated response with cloud model: {try_model}")
                return got[0], got[1], try_model

        logger.error("All LLM models failed; tried %s", ", ".join(models_to_try))
        return (
            "I couldn't reach any language model. Check that Ollama is running "
            "with at least one model pulled.",
            None,
            model,
        )

    def _extract_citations(
        self,
        answer: str,
        chunks: List[ChunkWithScore]
    ) -> List[Citation]:
        """Citations for the chunks the answer cites, in order of first mention."""
        return resolve_answer(answer, chunks)[1]

    def _resolve_answer(
        self,
        answer: str,
        chunks: List[ChunkWithScore]
    ) -> Tuple[str, List[Citation]]:
        """The answer with its markers renumbered ``[1] [2]...`` and the matching citations."""
        text, citations, _ = resolve_answer(answer, chunks)
        return text, citations

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
                        "stream": False,
                        "think": False,
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

        message = await self._save_exchange(
            notebook_id, user_id, request.message, answer, model_used=used_model
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

        message = await self._save_exchange(
            notebook_id, user_id, request.message, answer, model_used=request.model
        )

        return NotebookChatResponse(
            answer=answer,
            citations=[],
            model_used=request.model,
            message_id=message.id
        )
