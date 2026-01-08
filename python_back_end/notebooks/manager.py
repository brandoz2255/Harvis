"""
NotebookManager - Database operations for NotebookLM feature
"""

import logging
import json
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from asyncpg import Pool
from datetime import datetime

from .models import (
    Notebook, NotebookSource, NotebookChunk, NotebookNote, NotebookChatMessage,
    CreateNotebookRequest, UpdateNotebookRequest,
    CreateNoteRequest, UpdateNoteRequest,
    SourceType, SourceStatus, NoteType, MessageRole,
    Citation, ChunkWithScore
)

logger = logging.getLogger(__name__)


class NotebookManagerError(Exception):
    """Base exception for NotebookManager"""
    pass


class NotebookNotFoundError(NotebookManagerError):
    """Notebook not found"""
    pass


class SourceNotFoundError(NotebookManagerError):
    """Source not found"""
    pass


class NoteNotFoundError(NotebookManagerError):
    """Note not found"""
    pass


class NotebookManager:
    """
    Manager for NotebookLM database operations.
    Handles notebooks, sources, chunks, notes, and chat messages.
    """

    def __init__(self, db_pool: Pool):
        self.db_pool = db_pool

    # ─── Notebook CRUD ─────────────────────────────────────────────────────────

    async def create_notebook(self, user_id: int, request: CreateNotebookRequest) -> Notebook:
        """Create a new notebook for a user"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebooks (user_id, title, description)
                VALUES ($1, $2, $3)
                RETURNING id, user_id, title, description, is_active, created_at, updated_at
            """, user_id, request.title, request.description)

            logger.info(f"Created notebook {row['id']} for user {user_id}")
            return Notebook(**dict(row), source_count=0, note_count=0)

    async def get_notebook(self, notebook_id: UUID, user_id: int) -> Notebook:
        """Get a notebook by ID (only if owned by user)"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT n.id, n.user_id, n.title, n.description, n.is_active, n.created_at, n.updated_at,
                       (SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = n.id) as source_count,
                       (SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = n.id) as note_count
                FROM notebooks n
                WHERE n.id = $1 AND n.user_id = $2 AND n.is_active = TRUE
            """, notebook_id, user_id)

            if not row:
                raise NotebookNotFoundError(f"Notebook {notebook_id} not found")

            return Notebook(**dict(row))

    async def list_notebooks(self, user_id: int, limit: int = 50, offset: int = 0) -> Tuple[List[Notebook], int]:
        """List all notebooks for a user with pagination"""
        async with self.db_pool.acquire() as conn:
            # Get notebooks with counts
            rows = await conn.fetch("""
                SELECT n.id, n.user_id, n.title, n.description, n.is_active, n.created_at, n.updated_at,
                       (SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = n.id) as source_count,
                       (SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = n.id) as note_count
                FROM notebooks n
                WHERE n.user_id = $1 AND n.is_active = TRUE
                ORDER BY n.updated_at DESC
                LIMIT $2 OFFSET $3
            """, user_id, limit, offset)

            # Get total count
            total = await conn.fetchval("""
                SELECT COUNT(*) FROM notebooks WHERE user_id = $1 AND is_active = TRUE
            """, user_id)

            notebooks = [Notebook(**dict(row)) for row in rows]
            return notebooks, total

    async def update_notebook(self, notebook_id: UUID, user_id: int, request: UpdateNotebookRequest) -> Notebook:
        """Update a notebook's title or description"""
        async with self.db_pool.acquire() as conn:
            # Build dynamic update
            updates = []
            params = [notebook_id, user_id]
            param_idx = 3

            if request.title is not None:
                updates.append(f"title = ${param_idx}")
                params.append(request.title)
                param_idx += 1

            if request.description is not None:
                updates.append(f"description = ${param_idx}")
                params.append(request.description)
                param_idx += 1

            if not updates:
                return await self.get_notebook(notebook_id, user_id)

            row = await conn.fetchrow(f"""
                UPDATE notebooks
                SET {', '.join(updates)}
                WHERE id = $1 AND user_id = $2 AND is_active = TRUE
                RETURNING id, user_id, title, description, is_active, created_at, updated_at
            """, *params)

            if not row:
                raise NotebookNotFoundError(f"Notebook {notebook_id} not found")

            # Get counts
            source_count = await conn.fetchval(
                "SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = $1", notebook_id
            )
            note_count = await conn.fetchval(
                "SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = $1", notebook_id
            )

            return Notebook(**dict(row), source_count=source_count, note_count=note_count)

    async def delete_notebook(self, notebook_id: UUID, user_id: int) -> bool:
        """Soft delete a notebook (cascade deletes sources, chunks, notes, messages)"""
        async with self.db_pool.acquire() as conn:
            # Soft delete by setting is_active to FALSE
            result = await conn.execute("""
                UPDATE notebooks
                SET is_active = FALSE
                WHERE id = $1 AND user_id = $2 AND is_active = TRUE
            """, notebook_id, user_id)

            deleted = result == "UPDATE 1"
            if deleted:
                logger.info(f"Deleted notebook {notebook_id} for user {user_id}")

            return deleted

    # ─── Source Management ─────────────────────────────────────────────────────

    async def create_source(
        self,
        notebook_id: UUID,
        user_id: int,
        source_type: SourceType,
        title: Optional[str] = None,
        storage_path: Optional[str] = None,
        original_filename: Optional[str] = None,
        content_text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> NotebookSource:
        """Create a new source for a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebook_sources
                    (notebook_id, type, title, storage_path, original_filename, content_text, metadata, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, notebook_id, type, title, storage_path, original_filename, metadata, status,
                          error_message, created_at, updated_at
            """, notebook_id, source_type.value, title, storage_path, original_filename,
                 content_text, json.dumps(metadata or {}), SourceStatus.PENDING.value)

            logger.info(f"Created source {row['id']} for notebook {notebook_id}")

            data = dict(row)
            if isinstance(data['metadata'], str):
                data['metadata'] = json.loads(data['metadata'])

            return NotebookSource(**data, chunk_count=0)

    async def get_source(self, source_id: UUID, user_id: int) -> NotebookSource:
        """Get a source by ID (verifies notebook ownership)"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT s.id, s.notebook_id, s.type, s.title, s.storage_path, s.original_filename,
                       s.metadata, s.status, s.error_message, s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM notebook_chunks WHERE source_id = s.id) as chunk_count
                FROM notebook_sources s
                JOIN notebooks n ON s.notebook_id = n.id
                WHERE s.id = $1 AND n.user_id = $2 AND n.is_active = TRUE
            """, source_id, user_id)

            if not row:
                raise SourceNotFoundError(f"Source {source_id} not found")

            data = dict(row)
            if isinstance(data['metadata'], str):
                data['metadata'] = json.loads(data['metadata'])

            return NotebookSource(**data)

    async def list_sources(self, notebook_id: UUID, user_id: int) -> List[NotebookSource]:
        """List all sources for a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.notebook_id, s.type, s.title, s.storage_path, s.original_filename,
                       s.metadata, s.status, s.error_message, s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM notebook_chunks WHERE source_id = s.id) as chunk_count
                FROM notebook_sources s
                WHERE s.notebook_id = $1
                ORDER BY s.created_at DESC
            """, notebook_id)

            sources = []
            for row in rows:
                data = dict(row)
                if isinstance(data['metadata'], str):
                    data['metadata'] = json.loads(data['metadata'])
                sources.append(NotebookSource(**data))

            return sources

    async def update_source_status(
        self,
        source_id: UUID,
        status: SourceStatus,
        error_message: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update a source's status and optionally its metadata"""
        async with self.db_pool.acquire() as conn:
            if metadata_update:
                await conn.execute("""
                    UPDATE notebook_sources
                    SET status = $1, error_message = $2, metadata = metadata || $3
                    WHERE id = $4
                """, status.value, error_message, json.dumps(metadata_update), source_id)
            else:
                await conn.execute("""
                    UPDATE notebook_sources
                    SET status = $1, error_message = $2
                    WHERE id = $3
                """, status.value, error_message, source_id)

            logger.info(f"Updated source {source_id} status to {status.value}")

    async def delete_source(self, source_id: UUID, user_id: int) -> bool:
        """Delete a source and its associated chunks"""
        # Verify ownership first
        source = await self.get_source(source_id, user_id)

        async with self.db_pool.acquire() as conn:
            # Cascade delete will handle chunks
            result = await conn.execute("""
                DELETE FROM notebook_sources WHERE id = $1
            """, source_id)

            deleted = result == "DELETE 1"
            if deleted:
                logger.info(f"Deleted source {source_id}")

            return deleted

    # ─── Chunk Management ──────────────────────────────────────────────────────

    async def create_chunks(
        self,
        source_id: UUID,
        notebook_id: UUID,
        chunks: List[Tuple[str, List[float], Dict[str, Any], int]]
    ) -> int:
        """
        Batch insert chunks with embeddings.
        Each chunk is a tuple of (content, embedding, metadata, chunk_index)
        """
        if not chunks:
            return 0

        async with self.db_pool.acquire() as conn:
            # Convert embeddings to pgvector string format
            # pgvector expects format like '[0.1, 0.2, 0.3]'
            records = []
            for content, embedding, metadata, chunk_index in chunks:
                # Convert embedding list to pgvector string format
                if embedding:
                    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                else:
                    # Default zero vector if no embedding
                    embedding_str = '[' + ','.join(['0.0'] * 1024) + ']'
                
                records.append((
                    source_id, 
                    notebook_id, 
                    content, 
                    embedding_str, 
                    json.dumps(metadata), 
                    chunk_index
                ))

            await conn.executemany("""
                INSERT INTO notebook_chunks (source_id, notebook_id, content, embedding, metadata, chunk_index)
                VALUES ($1, $2, $3, $4::vector, $5, $6)
            """, records)

            logger.info(f"Created {len(chunks)} chunks for source {source_id}")
            return len(chunks)

    async def search_chunks(
        self,
        notebook_id: UUID,
        query_embedding: List[float],
        top_k: int = 5
    ) -> List[ChunkWithScore]:
        """
        Search for similar chunks using vector similarity.
        Returns chunks with their similarity scores.
        """
        # Convert query embedding to pgvector string format
        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT c.id, c.source_id, c.notebook_id, c.content, c.metadata, c.chunk_index, c.created_at,
                       s.title as source_title,
                       1 - (c.embedding <=> $1::vector) as similarity
                FROM notebook_chunks c
                JOIN notebook_sources s ON c.source_id = s.id
                WHERE c.notebook_id = $2 AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> $1::vector
                LIMIT $3
            """, embedding_str, notebook_id, top_k)

            results = []
            for row in rows:
                data = dict(row)
                source_title = data.pop('source_title')
                similarity = data.pop('similarity')

                if isinstance(data['metadata'], str):
                    data['metadata'] = json.loads(data['metadata'])

                chunk = NotebookChunk(**data)
                results.append(ChunkWithScore(
                    chunk=chunk,
                    score=float(similarity),
                    source_title=source_title
                ))

            return results

    # ─── Note Management ───────────────────────────────────────────────────────

    async def create_note(
        self,
        notebook_id: UUID,
        user_id: int,
        request: CreateNoteRequest
    ) -> NotebookNote:
        """Create a new note in a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebook_notes
                    (notebook_id, user_id, type, title, content, source_meta, is_pinned)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, notebook_id, user_id, type, title, content, source_meta, is_pinned,
                          created_at, updated_at
            """, notebook_id, user_id, request.type.value, request.title, request.content,
                 json.dumps(request.source_meta or {}), request.is_pinned)

            data = dict(row)
            if isinstance(data['source_meta'], str):
                data['source_meta'] = json.loads(data['source_meta'])

            logger.info(f"Created note {row['id']} in notebook {notebook_id}")
            return NotebookNote(**data)

    async def get_note(self, note_id: UUID, user_id: int) -> NotebookNote:
        """Get a note by ID (verifies ownership)"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, notebook_id, user_id, type, title, content, source_meta, is_pinned,
                       created_at, updated_at
                FROM notebook_notes
                WHERE id = $1 AND user_id = $2
            """, note_id, user_id)

            if not row:
                raise NoteNotFoundError(f"Note {note_id} not found")

            data = dict(row)
            if isinstance(data['source_meta'], str):
                data['source_meta'] = json.loads(data['source_meta'])

            return NotebookNote(**data)

    async def list_notes(
        self,
        notebook_id: UUID,
        user_id: int,
        note_type: Optional[NoteType] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[NotebookNote], int]:
        """List notes for a notebook with optional filtering by type"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            if note_type:
                rows = await conn.fetch("""
                    SELECT id, notebook_id, user_id, type, title, content, source_meta, is_pinned,
                           created_at, updated_at
                    FROM notebook_notes
                    WHERE notebook_id = $1 AND type = $2
                    ORDER BY is_pinned DESC, created_at DESC
                    LIMIT $3 OFFSET $4
                """, notebook_id, note_type.value, limit, offset)

                total = await conn.fetchval("""
                    SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = $1 AND type = $2
                """, notebook_id, note_type.value)
            else:
                rows = await conn.fetch("""
                    SELECT id, notebook_id, user_id, type, title, content, source_meta, is_pinned,
                           created_at, updated_at
                    FROM notebook_notes
                    WHERE notebook_id = $1
                    ORDER BY is_pinned DESC, created_at DESC
                    LIMIT $3 OFFSET $4
                """, notebook_id, limit, offset)

                total = await conn.fetchval("""
                    SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = $1
                """, notebook_id)

            notes = []
            for row in rows:
                data = dict(row)
                if isinstance(data['source_meta'], str):
                    data['source_meta'] = json.loads(data['source_meta'])
                notes.append(NotebookNote(**data))

            return notes, total

    async def update_note(
        self,
        note_id: UUID,
        user_id: int,
        request: UpdateNoteRequest
    ) -> NotebookNote:
        """Update a note"""
        async with self.db_pool.acquire() as conn:
            # Build dynamic update
            updates = []
            params = [note_id, user_id]
            param_idx = 3

            if request.title is not None:
                updates.append(f"title = ${param_idx}")
                params.append(request.title)
                param_idx += 1

            if request.content is not None:
                updates.append(f"content = ${param_idx}")
                params.append(request.content)
                param_idx += 1

            if request.is_pinned is not None:
                updates.append(f"is_pinned = ${param_idx}")
                params.append(request.is_pinned)
                param_idx += 1

            if not updates:
                return await self.get_note(note_id, user_id)

            row = await conn.fetchrow(f"""
                UPDATE notebook_notes
                SET {', '.join(updates)}
                WHERE id = $1 AND user_id = $2
                RETURNING id, notebook_id, user_id, type, title, content, source_meta, is_pinned,
                          created_at, updated_at
            """, *params)

            if not row:
                raise NoteNotFoundError(f"Note {note_id} not found")

            data = dict(row)
            if isinstance(data['source_meta'], str):
                data['source_meta'] = json.loads(data['source_meta'])

            return NotebookNote(**data)

    async def delete_note(self, note_id: UUID, user_id: int) -> bool:
        """Delete a note"""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM notebook_notes WHERE id = $1 AND user_id = $2
            """, note_id, user_id)

            deleted = result == "DELETE 1"
            if deleted:
                logger.info(f"Deleted note {note_id}")

            return deleted

    # ─── Chat Management ───────────────────────────────────────────────────────

    async def add_chat_message(
        self,
        notebook_id: UUID,
        user_id: int,
        role: MessageRole,
        content: str,
        reasoning: Optional[str] = None,
        citations: Optional[List[Citation]] = None,
        model_used: Optional[str] = None
    ) -> NotebookChatMessage:
        """Add a chat message to a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        citations_json = json.dumps([c.dict() for c in (citations or [])])

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebook_chat_messages
                    (notebook_id, user_id, role, content, reasoning, citations, model_used)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, notebook_id, user_id, role, content, reasoning, citations, model_used, created_at
            """, notebook_id, user_id, role.value, content, reasoning, citations_json, model_used)

            data = dict(row)
            if isinstance(data['citations'], str):
                data['citations'] = json.loads(data['citations'])

            # Convert citations back to Citation objects
            data['citations'] = [Citation(**c) for c in data['citations']]

            return NotebookChatMessage(**data)

    async def get_chat_history(
        self,
        notebook_id: UUID,
        user_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[NotebookChatMessage], int]:
        """Get chat history for a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, notebook_id, user_id, role, content, reasoning, citations, model_used, created_at
                FROM notebook_chat_messages
                WHERE notebook_id = $1
                ORDER BY created_at ASC
                LIMIT $2 OFFSET $3
            """, notebook_id, limit, offset)

            total = await conn.fetchval("""
                SELECT COUNT(*) FROM notebook_chat_messages WHERE notebook_id = $1
            """, notebook_id)

            messages = []
            for row in rows:
                data = dict(row)
                if isinstance(data['citations'], str):
                    data['citations'] = json.loads(data['citations'])
                data['citations'] = [Citation(**c) for c in data['citations']]
                messages.append(NotebookChatMessage(**data))

            return messages, total

    async def clear_chat_history(self, notebook_id: UUID, user_id: int) -> bool:
        """Clear all chat messages for a notebook"""
        # Verify notebook ownership
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM notebook_chat_messages WHERE notebook_id = $1
            """, notebook_id)

            logger.info(f"Cleared chat history for notebook {notebook_id}")
            return True

    # ─── Utility Methods ───────────────────────────────────────────────────────

    async def get_notebook_stats(self, notebook_id: UUID, user_id: int) -> Dict[str, Any]:
        """Get statistics for a notebook"""
        await self.get_notebook(notebook_id, user_id)

        async with self.db_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = $1) as source_count,
                    (SELECT COUNT(*) FROM notebook_chunks WHERE notebook_id = $1) as chunk_count,
                    (SELECT COUNT(*) FROM notebook_notes WHERE notebook_id = $1) as note_count,
                    (SELECT COUNT(*) FROM notebook_chat_messages WHERE notebook_id = $1) as message_count,
                    (SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = $1 AND status = 'ready') as ready_sources,
                    (SELECT COUNT(*) FROM notebook_sources WHERE notebook_id = $1 AND status = 'processing') as processing_sources
            """, notebook_id)

            return dict(stats)

    async def ensure_tables(self) -> None:
        """Ensure all NotebookLM tables exist (for initialization)"""
        # Tables are created by db_setup.sql, this is just a health check
        async with self.db_pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'notebooks'
                )
            """)

            if not result:
                logger.warning("Notebooks table does not exist - run db_setup.sql")
            else:
                logger.info("NotebookLM tables verified")
