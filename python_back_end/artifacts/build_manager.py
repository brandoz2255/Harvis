"""
Artifact Build Manager - handles job queue and Kubernetes pod orchestration
for isolated code execution
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
import aiohttp

from .executor_models import (
    BuildJobStatus,
    BuildRequest,
    BuildStatusUpdate,
    BuildJobCreate,
    ExecutorPodInfo,
)

logger = logging.getLogger(__name__)

# Configuration
EXECUTOR_NAMESPACE = os.environ.get("ARTIFACT_EXECUTOR_NAMESPACE", "artifact-executor")
EXECUTOR_IMAGE = os.environ.get(
    "ARTIFACT_EXECUTOR_IMAGE", "harvis-artifact-executor:latest"
)
EXECUTOR_NODE_NAME = os.environ.get("ARTIFACT_EXECUTOR_NODE", "rockyvm3")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://harvis-ai-backend:8000")

# Port range for apps
PORT_RANGE_START = int(os.environ.get("ARTIFACT_PORT_START", "30000"))
PORT_RANGE_END = int(os.environ.get("ARTIFACT_PORT_END", "31000"))

# Resource defaults
DEFAULT_MEMORY_LIMIT = os.environ.get("ARTIFACT_MEMORY_LIMIT", "1Gi")
DEFAULT_CPU_LIMIT = os.environ.get("ARTIFACT_CPU_LIMIT", "1000m")


class ArtifactBuildManager:
    """
    Manages build job queue and Kubernetes pod lifecycle for artifact execution.

    This manager:
    1. Queues build jobs in the database
    2. Spawns executor pods on rockyvm3 node
    3. Monitors build status via callbacks
    4. Handles cleanup of expired jobs
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._running_builds: Dict[str, asyncio.Task] = {}
        self._port_pool = set(range(PORT_RANGE_START, PORT_RANGE_END + 1))
        self._used_ports: Dict[str, int] = {}  # job_id -> port

    async def create_build_job(
        self,
        artifact_id: UUID,
        framework: str = "nextjs",
        node_version: str = "18",
        memory_limit: str = None,
        cpu_limit: str = None,
    ) -> UUID:
        """
        Create a new build job for an artifact.

        Returns:
            job_id: UUID of the created build job
        """
        memory_limit = memory_limit or DEFAULT_MEMORY_LIMIT
        cpu_limit = cpu_limit or DEFAULT_CPU_LIMIT

        async with self.db_pool.acquire() as conn:
            # Check if there's already a running job for this artifact
            existing = await conn.fetchrow(
                """
                SELECT id FROM artifact_build_jobs
                WHERE artifact_id = $1 AND status IN ('queued', 'building', 'running')
                """,
                artifact_id,
            )

            if existing:
                logger.warning(
                    f"Build job already exists for artifact {artifact_id}: {existing['id']}"
                )
                return existing["id"]

            # Create new build job
            row = await conn.fetchrow(
                """
                INSERT INTO artifact_build_jobs (
                    artifact_id, status, framework, node_version,
                    memory_limit, cpu_limit, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                artifact_id,
                BuildJobStatus.QUEUED.value,
                framework,
                node_version,
                memory_limit,
                cpu_limit,
                datetime.utcnow() + asyncio.timedelta(hours=24),
            )

            job_id = row["id"]
            logger.info(f"Created build job {job_id} for artifact {artifact_id}")
            return job_id

    async def get_build_job(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        """Get build job by ID"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM artifact_build_jobs WHERE id = $1
                """,
                job_id,
            )
            return dict(row) if row else None

    async def get_build_job_by_artifact(
        self, artifact_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent build job for an artifact"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM artifact_build_jobs
                WHERE artifact_id = $1
                ORDER BY queued_at DESC
                LIMIT 1
                """,
                artifact_id,
            )
            return dict(row) if row else None

    async def update_build_status(self, update: BuildStatusUpdate) -> bool:
        """
        Update build job status from executor callback.

        This is called by the executor service to report progress.
        """
        async with self.db_pool.acquire() as conn:
            # Build update query dynamically based on provided fields
            updates = ["status = $1"]
            params = [update.status.value]
            param_idx = 2

            if update.progress_percentage is not None:
                updates.append(f"progress = ${param_idx}")
                params.append(update.progress_percentage)
                param_idx += 1

            if update.current_phase:
                updates.append(f"current_phase = ${param_idx}")
                params.append(update.current_phase)
                param_idx += 1

            if update.preview_url:
                updates.append(f"preview_url = ${param_idx}")
                params.append(update.preview_url)
                param_idx += 1

            if update.pod_name:
                updates.append(f"pod_name = ${param_idx}")
                params.append(update.pod_name)
                param_idx += 1

            if update.namespace:
                updates.append(f"namespace = ${param_idx}")
                params.append(update.namespace)
                param_idx += 1

            if update.node_name:
                updates.append(f"node_name = ${param_idx}")
                params.append(update.node_name)
                param_idx += 1

            if update.build_logs:
                updates.append(f"build_logs = ${param_idx}")
                params.append(update.build_logs)
                param_idx += 1

            if update.error_message:
                updates.append(f"error_message = ${param_idx}")
                params.append(update.error_message)
                param_idx += 1

            # Set timestamps based on status
            if update.status == BuildJobStatus.BUILDING and update.started_at:
                updates.append(f"started_at = ${param_idx}")
                params.append(update.started_at)
                param_idx += 1

            if update.status == BuildJobStatus.RUNNING and update.running_at:
                updates.append(f"running_at = ${param_idx}")
                params.append(update.running_at)
                param_idx += 1

            if (
                update.status in [BuildJobStatus.FAILED, BuildJobStatus.STOPPED]
                and update.completed_at
            ):
                updates.append(f"completed_at = ${param_idx}")
                params.append(update.completed_at)
                param_idx += 1

            # Add job_id to params
            params.append(update.job_id)

            query = f"""
                UPDATE artifact_build_jobs
                SET {", ".join(updates)}
                WHERE id = ${param_idx}
            """

            await conn.execute(query, *params)
            logger.info(
                f"Updated build job {update.job_id} status to {update.status.value}"
            )
            return True

    async def process_build_queue(self):
        """
        Background task to process queued build jobs.

        This spawns executor pods for queued jobs.
        """
        while True:
            try:
                async with self.db_pool.acquire() as conn:
                    # Get next queued job
                    row = await conn.fetchrow(
                        """
                        SELECT id, artifact_id, framework, node_version
                        FROM artifact_build_jobs
                        WHERE status = 'queued'
                        ORDER BY queued_at
                        LIMIT 1
                        """
                    )

                    if row:
                        job_id = row["id"]
                        artifact_id = row["artifact_id"]

                        logger.info(
                            f"Processing build job {job_id} for artifact {artifact_id}"
                        )

                        # Get artifact details
                        artifact_row = await conn.fetchrow(
                            """
                            SELECT content, dependencies, title
                            FROM artifacts WHERE id = $1
                            """,
                            artifact_id,
                        )

                        if not artifact_row:
                            logger.error(f"Artifact {artifact_id} not found")
                            await conn.execute(
                                """
                                UPDATE artifact_build_jobs
                                SET status = 'failed', error_message = 'Artifact not found'
                                WHERE id = $1
                                """,
                                job_id,
                            )
                            continue

                        # Assign port
                        port = self._allocate_port(job_id)
                        if not port:
                            logger.warning("No ports available, waiting...")
                            await asyncio.sleep(5)
                            continue

                        # Spawn executor pod
                        try:
                            await self._spawn_executor_pod(
                                job_id=job_id,
                                artifact_id=artifact_id,
                                content=artifact_row["content"],
                                dependencies=artifact_row["dependencies"] or {},
                                framework=row["framework"],
                                node_version=row["node_version"],
                                port=port,
                            )

                            # Update status to building
                            await conn.execute(
                                """
                                UPDATE artifact_build_jobs
                                SET status = 'building', port = $2, started_at = NOW()
                                WHERE id = $1
                                """,
                                job_id,
                                port,
                            )

                        except Exception as e:
                            logger.error(f"Failed to spawn executor pod: {e}")
                            self._release_port(job_id)
                            await conn.execute(
                                """
                                UPDATE artifact_build_jobs
                                SET status = 'failed', error_message = $2
                                WHERE id = $1
                                """,
                                job_id,
                                str(e),
                            )
                    else:
                        # No queued jobs, sleep before checking again
                        await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error in build queue processor: {e}")
                await asyncio.sleep(10)

    async def _spawn_executor_pod(
        self,
        job_id: UUID,
        artifact_id: UUID,
        content: Dict[str, Any],
        dependencies: Dict[str, str],
        framework: str,
        node_version: str,
        port: int,
    ):
        """
        Spawn a Kubernetes executor pod for the build job.

        In a real implementation, this would use the Kubernetes Python client
        to create a Pod resource. For now, we assume the executor pod is managed
        externally and we just notify it via HTTP.
        """
        # Build request to executor
        build_request = BuildRequest(
            job_id=job_id,
            artifact_id=artifact_id,
            artifact_type="website" if framework == "nextjs" else "app",
            files=content.get("files", {}),
            entry_file=content.get("entry_file", "App.tsx"),
            dependencies=dependencies,
            framework=framework,
            node_version=node_version,
            port=port,
            output_dir=f"/data/artifacts/builds/{artifact_id}",
            backend_url=BACKEND_URL,
        )

        # In Kubernetes, the executor pod would be created here
        # For now, we just log that it should be created
        logger.info(f"Would spawn executor pod for job {job_id} on port {port}")

        # TODO: Implement actual K8s pod creation using kubernetes client
        # This would create a Pod with:
        # - nodeSelector: kubernetes.io/hostname: rockyvm3
        # - Container with EXECUTOR_IMAGE
        # - Volume mount for artifact_data PVC
        # - Environment variables for build_request

    def _allocate_port(self, job_id: str) -> Optional[int]:
        """Allocate an available port for a build job"""
        available = self._port_pool - set(self._used_ports.values())
        if not available:
            return None
        port = min(available)
        self._used_ports[job_id] = port
        return port

    def _release_port(self, job_id: str):
        """Release a port allocation"""
        if job_id in self._used_ports:
            del self._used_ports[job_id]

    async def stop_build_job(self, job_id: UUID) -> bool:
        """Stop a running build job"""
        async with self.db_pool.acquire() as conn:
            # Get job details
            row = await conn.fetchrow(
                """
                SELECT status, pod_name, namespace FROM artifact_build_jobs
                WHERE id = $1
                """,
                job_id,
            )

            if not row:
                return False

            if row["status"] not in ["queued", "building", "running"]:
                logger.warning(f"Cannot stop job {job_id} with status {row['status']}")
                return False

            # TODO: Send stop signal to executor pod
            # This would call the executor service's /stop endpoint

            # Update status
            await conn.execute(
                """
                UPDATE artifact_build_jobs
                SET status = 'stopped', completed_at = NOW()
                WHERE id = $1
                """,
                job_id,
            )

            self._release_port(str(job_id))
            logger.info(f"Stopped build job {job_id}")
            return True

    async def cleanup_expired_jobs(self) -> int:
        """
        Clean up expired build jobs.

        Returns:
            Number of jobs cleaned up
        """
        async with self.db_pool.acquire() as conn:
            # Stop old running jobs
            old_running = await conn.fetch(
                """
                SELECT id FROM artifact_build_jobs
                WHERE status = 'running'
                AND running_at < NOW() - INTERVAL '24 hours'
                """
            )

            for row in old_running:
                await self.stop_build_job(row["id"])

            # Delete old stopped/failed jobs
            deleted = await conn.fetchval(
                """
                DELETE FROM artifact_build_jobs
                WHERE status IN ('stopped', 'failed')
                AND completed_at < NOW() - INTERVAL '7 days'
                RETURNING COUNT(*)
                """
            )

            logger.info(f"Cleaned up {deleted} expired build jobs")
            return deleted

    async def get_active_builds(self) -> List[Dict[str, Any]]:
        """Get all active (queued, building, running) build jobs"""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    j.id, j.artifact_id, j.status, j.framework,
                    j.port, j.preview_url, j.pod_name, j.node_name,
                    j.queued_at, j.started_at, j.built_at, j.running_at,
                    a.title as artifact_title
                FROM artifact_build_jobs j
                JOIN artifacts a ON j.artifact_id = a.id
                WHERE j.status IN ('queued', 'building', 'running')
                ORDER BY j.queued_at
                """
            )
            return [dict(row) for row in rows]

    async def start_queue_processor(self):
        """Start the background queue processor task"""
        logger.info("Starting build queue processor")
        self._queue_task = asyncio.create_task(self.process_build_queue())

        # Also start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """Background task to periodically clean up expired jobs"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self.cleanup_expired_jobs()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def stop(self):
        """Stop the build manager"""
        if hasattr(self, "_queue_task"):
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, "_cleanup_task"):
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
