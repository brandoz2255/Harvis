"""
Artifact storage manager - handles database operations and file management
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta

from .models import (
    ArtifactManifest,
    ArtifactType,
    ArtifactStatus,
    ArtifactResponse,
    ARTIFACT_MIME_TYPES,
    ARTIFACT_EXTENSIONS,
)
from .generators import (
    generate_spreadsheet,
    generate_document,
    generate_pdf,
    generate_presentation,
)

logger = logging.getLogger(__name__)

# Default artifact storage directory (mounted as Docker volume)
DEFAULT_ARTIFACT_DIR = os.environ.get("ARTIFACT_STORAGE_DIR", "/data/artifacts")


class ArtifactStorage:
    """Manages artifact creation, storage, retrieval, and generation"""

    def __init__(self, artifact_dir: str = None):
        self.artifact_dir = artifact_dir or DEFAULT_ARTIFACT_DIR
        os.makedirs(self.artifact_dir, exist_ok=True)
        logger.info(f"Artifact storage initialized at: {self.artifact_dir}")

    async def create_artifact(
        self,
        pool,
        user_id: int,
        manifest: ArtifactManifest,
        session_id: Optional[UUID] = None,
        message_id: Optional[int] = None,
    ) -> UUID:
        """
        Create a new artifact record in database.
        Returns the artifact ID.
        """
        artifact_type = manifest.artifact_type
        if isinstance(artifact_type, ArtifactType):
            artifact_type = artifact_type.value

        # Website/app/code artifacts are stored immediately as ready
        # Document artifacts start as pending
        is_code_type = artifact_type in ["website", "app", "code"]
        initial_status = (
            ArtifactStatus.READY.value if is_code_type else ArtifactStatus.PENDING.value
        )

        # For code artifacts, store content directly
        content = manifest.content
        framework = content.get("framework", "react") if is_code_type else None
        dependencies = content.get("dependencies", {}) if is_code_type else None

        # Set expiration (7 days for documents, no expiration for code)
        expires_at = None if is_code_type else datetime.now() + timedelta(days=7)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO artifacts (
                    user_id, session_id, message_id,
                    artifact_type, title, description,
                    content, status, framework, dependencies, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                user_id,
                session_id,
                message_id,
                artifact_type,
                manifest.title,
                manifest.description,
                content,  # asyncpg handles dict -> JSONB conversion
                initial_status,
                framework,
                dependencies,
                expires_at,
            )

            artifact_id = row["id"]
            logger.info(f"Created artifact {artifact_id} of type {artifact_type}")
            return artifact_id

    async def generate_artifact(self, pool, artifact_id: UUID) -> bool:
        """
        Generate the actual artifact file.
        Updates the artifact record with file path and status.
        """
        async with pool.acquire() as conn:
            # Get artifact info
            artifact = await conn.fetchrow(
                """
                SELECT id, artifact_type, title, content, user_id
                FROM artifacts WHERE id = $1
                """,
                artifact_id,
            )

            if not artifact:
                logger.error(f"Artifact {artifact_id} not found")
                return False

            artifact_type = artifact["artifact_type"]
            content = artifact["content"]

            # Update status to generating
            await conn.execute(
                "UPDATE artifacts SET status = $1 WHERE id = $2",
                ArtifactStatus.GENERATING.value,
                artifact_id,
            )

        try:
            # Generate the file based on type
            filepath = await self._generate_file(artifact_type, content)

            # Get file size
            file_size = os.path.getsize(filepath) if filepath else 0

            # Get MIME type
            mime_type = ARTIFACT_MIME_TYPES.get(
                ArtifactType(artifact_type), "application/octet-stream"
            )

            # Update artifact with file info
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE artifacts
                    SET status = $1, file_path = $2, file_size = $3, mime_type = $4
                    WHERE id = $5
                    """,
                    ArtifactStatus.READY.value,
                    filepath,
                    file_size,
                    mime_type,
                    artifact_id,
                )

            logger.info(f"Generated artifact {artifact_id}: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to generate artifact {artifact_id}: {e}")

            # Update status to failed
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE artifacts SET status = $1, error_message = $2 WHERE id = $3
                    """,
                    ArtifactStatus.FAILED.value,
                    str(e),
                    artifact_id,
                )

            return False

    async def _generate_file(self, artifact_type: str, content: Dict[str, Any]) -> str:
        """Run the appropriate generator for the artifact type"""
        # Run CPU-intensive generation in thread pool
        loop = asyncio.get_event_loop()

        if artifact_type == "spreadsheet":
            return await loop.run_in_executor(
                None, generate_spreadsheet, content, self.artifact_dir
            )
        elif artifact_type == "document":
            return await loop.run_in_executor(
                None, generate_document, content, self.artifact_dir
            )
        elif artifact_type == "pdf":
            return await loop.run_in_executor(
                None, generate_pdf, content, self.artifact_dir
            )
        elif artifact_type == "presentation":
            return await loop.run_in_executor(
                None, generate_presentation, content, self.artifact_dir
            )
        else:
            raise ValueError(f"Unknown artifact type: {artifact_type}")

    async def get_artifact(
        self, pool, artifact_id: UUID, user_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get artifact by ID, verifying user ownership"""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id, message_id, session_id, user_id,
                    artifact_type, title, description,
                    content, file_path, file_size, mime_type,
                    framework, dependencies,
                    status, error_message,
                    created_at, updated_at, expires_at
                FROM artifacts
                WHERE id = $1 AND user_id = $2
                """,
                artifact_id,
                user_id,
            )

            if not row:
                return None

            return dict(row)

    async def get_artifacts_by_session(
        self, pool, session_id: UUID, user_id: int
    ) -> List[Dict[str, Any]]:
        """Get all artifacts for a session"""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, artifact_type, title, status, file_size, created_at
                FROM artifacts
                WHERE session_id = $1 AND user_id = $2
                ORDER BY created_at DESC
                """,
                session_id,
                user_id,
            )

            return [dict(row) for row in rows]

    async def get_user_artifacts(
        self, pool, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get all artifacts for a user"""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id, artifact_type, title, description, status,
                    file_size, created_at, updated_at
                FROM artifacts
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )

            return [dict(row) for row in rows]

    async def get_artifact_file_path(
        self, pool, artifact_id: UUID, user_id: int
    ) -> Optional[str]:
        """Get artifact file path, verifying user ownership"""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT file_path FROM artifacts
                WHERE id = $1 AND user_id = $2 AND status = $3
                """,
                artifact_id,
                user_id,
                ArtifactStatus.READY.value,
            )

            if row and row["file_path"]:
                return row["file_path"]
            return None

    async def delete_artifact(self, pool, artifact_id: UUID, user_id: int) -> bool:
        """Delete an artifact and its file"""
        async with pool.acquire() as conn:
            # Get file path first
            row = await conn.fetchrow(
                "SELECT file_path FROM artifacts WHERE id = $1 AND user_id = $2",
                artifact_id,
                user_id,
            )

            if not row:
                return False

            # Delete file if exists
            file_path = row["file_path"]
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted artifact file: {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete artifact file {file_path}: {e}")

            # Delete database record
            await conn.execute(
                "DELETE FROM artifacts WHERE id = $1 AND user_id = $2",
                artifact_id,
                user_id,
            )

            logger.info(f"Deleted artifact {artifact_id}")
            return True

    async def cleanup_expired(self, pool) -> int:
        """Clean up expired artifacts. Returns count of deleted artifacts."""
        async with pool.acquire() as conn:
            # Get expired artifacts
            rows = await conn.fetch(
                """
                SELECT id, file_path FROM artifacts
                WHERE expires_at IS NOT NULL AND expires_at < NOW()
                """
            )

            count = 0
            for row in rows:
                # Delete file
                file_path = row["file_path"]
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass

                # Delete record
                await conn.execute("DELETE FROM artifacts WHERE id = $1", row["id"])
                count += 1

            if count > 0:
                logger.info(f"Cleaned up {count} expired artifacts")

            return count

    def to_response(self, artifact: Dict[str, Any]) -> ArtifactResponse:
        """Convert database row to ArtifactResponse"""
        artifact_id = artifact["id"]
        artifact_type = artifact["artifact_type"]

        # Build URLs
        download_url = None
        preview_url = None

        if artifact["status"] == ArtifactStatus.READY.value:
            if artifact_type in ["website", "app", "code"]:
                preview_url = f"/api/artifacts/{artifact_id}/preview"
            else:
                download_url = f"/api/artifacts/{artifact_id}/download"

        return ArtifactResponse(
            id=artifact_id,
            artifact_type=artifact_type,
            title=artifact["title"],
            description=artifact.get("description"),
            status=artifact["status"],
            download_url=download_url,
            preview_url=preview_url,
            content=artifact.get("content")
            if artifact_type in ["website", "app", "code"]
            else None,
            framework=artifact.get("framework"),
            dependencies=artifact.get("dependencies"),
            file_size=artifact.get("file_size"),
            mime_type=artifact.get("mime_type"),
            error_message=artifact.get("error_message"),
            created_at=artifact["created_at"],
        )


# Singleton instance
_artifact_storage: ArtifactStorage = None


def get_artifact_storage(artifact_dir: str = None) -> ArtifactStorage:
    """Get or create the singleton ArtifactStorage instance"""
    global _artifact_storage
    if _artifact_storage is None:
        _artifact_storage = ArtifactStorage(artifact_dir)
    return _artifact_storage
