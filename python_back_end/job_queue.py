"""
Job Queue System for Async Document Generation
Compatible with pg-boss schema for cross-language compatibility
Works with both Docker and K8s deployments
"""

import os
import json
import uuid
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict
import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Represents a job in the queue"""

    id: str
    name: str  # queue name, e.g., 'generate-document'
    data: Dict[str, Any]
    state: str  # 'created', 'retry', 'active', 'completed', 'cancelled', 'failed'
    retry_count: int = 0
    retry_limit: int = 3
    start_after: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    async def done(self, result: Dict[str, Any] = None):
        """Mark job as completed"""
        # This will be implemented by the queue
        pass

    async def fail(self, error: str = None):
        """Mark job as failed"""
        pass


class JobQueue:
    """
    Async job queue using PostgreSQL
    Compatible with pg-boss schema
    """

    def __init__(self, dsn: str = None, schema: str = "boss"):
        self.dsn = dsn or os.getenv("DATABASE_URL")
        self.schema = schema
        self.pool: Optional[asyncpg.Pool] = None
        self.workers: Dict[str, List[Callable]] = {}
        self._running = False
        self._worker_tasks = []

    async def start(self):
        """Initialize the job queue"""
        self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)

        # Create pg-boss compatible schema if not exists
        await self._init_schema()

        self._running = True
        logger.info("✅ Job queue started")

    async def stop(self):
        """Stop the job queue"""
        self._running = False

        # Cancel all worker tasks
        for task in self._worker_tasks:
            task.cancel()

        if self.pool:
            await self.pool.close()

        logger.info("🛑 Job queue stopped")

    async def _init_schema(self):
        """Create pg-boss compatible schema"""
        async with self.pool.acquire() as conn:
            # Create schema
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")

            # Create jobs table (pg-boss compatible)
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.job (
                    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                    name text NOT NULL,
                    priority integer DEFAULT 0,
                    data jsonb DEFAULT '{{}}'::jsonb,
                    state text DEFAULT 'created'::text,
                    retry_limit integer DEFAULT 3,
                    retry_count integer DEFAULT 0,
                    retry_delay integer DEFAULT 0,
                    retry_backoff boolean DEFAULT false,
                    start_after timestamp with time zone DEFAULT now(),
                    started_at timestamp with time zone,
                    completed_at timestamp with time zone,
                    created_at timestamp with time zone DEFAULT now(),
                    updated_at timestamp with time zone DEFAULT now(),
                    keep_until timestamp with time zone DEFAULT (now() + interval '14 days')
                )
            """)

            # Create indexes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_job_fetch 
                ON {self.schema}.job (priority desc, created_at) 
                WHERE state < 'completed'
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_job_name 
                ON {self.schema}.job (name)
            """)

            # Create archive table for completed jobs
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.archive (
                    LIKE {self.schema}.job INCLUDING ALL,
                    archived_at timestamp with time zone DEFAULT now()
                )
            """)

            logger.info(f"✅ Job queue schema initialized in {self.schema}")

    async def send(
        self,
        name: str,
        data: Dict[str, Any],
        start_after: int = 0,
        retry_limit: int = 3,
        priority: int = 0,
    ) -> str:
        """
        Send a job to the queue

        Args:
            name: Queue name (e.g., 'generate-document')
            data: Job payload
            start_after: Delay in seconds before job can be processed
            retry_limit: Max retry attempts
            priority: Higher = processed first

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        start_time = datetime.utcnow()
        if start_after > 0:
            from datetime import timedelta

            start_time = start_time + timedelta(seconds=start_after)

        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.schema}.job 
                (id, name, data, state, retry_limit, priority, start_after)
                VALUES ($1, $2, $3, 'created', $4, $5, $6)
            """,
                job_id,
                name,
                json.dumps(data),
                retry_limit,
                priority,
                start_time,
            )

        logger.info(f"📨 Job queued: {name} (id: {job_id})")
        return job_id

    async def fetch(self, name: str, batch_size: int = 1) -> Optional[Job]:
        """
        Fetch next available job from queue

        Args:
            name: Queue name to fetch from
            batch_size: Number of jobs to fetch (currently only 1 supported)

        Returns:
            Job object or None if no jobs available
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Fetch and lock next job
                row = await conn.fetchrow(
                    f"""
                    UPDATE {self.schema}.job 
                    SET state = 'active',
                        started_at = NOW(),
                        updated_at = NOW(),
                        retry_count = retry_count + 1
                    WHERE id = (
                        SELECT id FROM {self.schema}.job
                        WHERE name = $1 
                          AND state IN ('created', 'retry')
                          AND start_after <= NOW()
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, name, data, state, retry_count, retry_limit, 
                              started_at, created_at
                """,
                    name,
                )

                if row:
                    job = Job(
                        id=str(row["id"]),
                        name=row["name"],
                        data=json.loads(row["data"]) if row["data"] else {},
                        state=row["state"],
                        retry_count=row["retry_count"],
                        retry_limit=row["retry_limit"],
                        started_at=row["started_at"],
                        created_at=row["created_at"],
                    )

                    # Bind done/fail methods
                    job.done = lambda result=None: self._complete_job(job.id, result)
                    job.fail = lambda error=None: self._fail_job(job.id, error)

                    return job

        return None

    async def _complete_job(self, job_id: str, result: Dict[str, Any] = None):
        """Mark job as completed and store result in data field"""
        async with self.pool.acquire() as conn:
            if result:
                # Update job data with result before archiving
                await conn.execute(
                    f"""
                    UPDATE {self.schema}.job
                    SET data = data || $2::jsonb,
                        state = 'completed',
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    job_id,
                    json.dumps(result),
                )

            # Move to archive
            await conn.execute(
                f"""
                WITH archived AS (
                    DELETE FROM {self.schema}.job
                    WHERE id = $1
                    RETURNING *
                )
                INSERT INTO {self.schema}.archive
                SELECT *, NOW() as archived_at FROM archived
            """,
                job_id,
            )

        logger.info(f"✅ Job completed: {job_id}")

    async def _fail_job(self, job_id: str, error: str = None):
        """Mark job as failed or retry"""
        async with self.pool.acquire() as conn:
            # Check retry limit
            row = await conn.fetchrow(
                f"""
                SELECT retry_count, retry_limit FROM {self.schema}.job WHERE id = $1
            """,
                job_id,
            )

            if row and row["retry_count"] < row["retry_limit"]:
                # Retry
                await conn.execute(
                    f"""
                    UPDATE {self.schema}.job 
                    SET state = 'retry',
                        updated_at = NOW(),
                        start_after = NOW() + INTERVAL '30 seconds',
                        data = jsonb_set(data, '{{error}}', $2::jsonb)
                    WHERE id = $1
                """,
                    job_id,
                    json.dumps(error or "Unknown error"),
                )

                logger.warning(
                    f"🔄 Job retry scheduled: {job_id} (attempt {row['retry_count']}/{row['retry_limit']})"
                )
            else:
                # Fail permanently
                await conn.execute(
                    f"""
                    WITH archived AS (
                        UPDATE {self.schema}.job 
                        SET state = 'failed',
                            completed_at = NOW(),
                            updated_at = NOW(),
                            data = jsonb_set(data, '{{error}}', $2::jsonb)
                        WHERE id = $1
                        RETURNING *
                    )
                    INSERT INTO {self.schema}.archive 
                    SELECT *, NOW() as archived_at FROM archived
                """,
                    job_id,
                    json.dumps(error or "Max retries exceeded"),
                )

                logger.error(f"❌ Job failed permanently: {job_id} - {error}")

    def work(self, name: str, handler: Callable[[Job], Any]):
        """
        Register a worker handler for a queue

        Args:
            name: Queue name
            handler: Async function that processes jobs
        """
        if name not in self.workers:
            self.workers[name] = []
        self.workers[name].append(handler)

        # Start worker task
        task = asyncio.create_task(self._worker_loop(name, handler))
        self._worker_tasks.append(task)

        logger.info(f"👷 Worker registered for queue: {name}")

    async def _worker_loop(self, name: str, handler: Callable[[Job], Any]):
        """Main worker loop"""
        while self._running:
            try:
                job = await self.fetch(name)

                if job:
                    try:
                        logger.info(f"🔄 Processing job: {job.id} ({name})")
                        await handler(job)
                    except Exception as e:
                        logger.exception(f"💥 Job handler error: {e}")
                        await job.fail(str(e))
                else:
                    # No jobs, wait before polling again
                    await asyncio.sleep(1)

            except Exception as e:
                logger.exception(f"💥 Worker loop error: {e}")
                await asyncio.sleep(5)  # Back off on error

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a job"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, name, data, state, retry_count, retry_limit,
                       created_at, started_at, completed_at
                FROM {self.schema}.job
                WHERE id = $1
                UNION ALL
                SELECT id, name, data, state, retry_count, retry_limit,
                       created_at, started_at, completed_at
                FROM {self.schema}.archive
                WHERE id = $1
            """,
                job_id,
            )

            if row:
                return {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "data": json.loads(row["data"]) if row["data"] else {},
                    "state": row["state"],
                    "retry_count": row["retry_count"],
                    "retry_limit": row["retry_limit"],
                    "created_at": row["created_at"].isoformat()
                    if row["created_at"]
                    else None,
                    "started_at": row["started_at"].isoformat()
                    if row["started_at"]
                    else None,
                    "completed_at": row["completed_at"].isoformat()
                    if row["completed_at"]
                    else None,
                }
            return None


# Global queue instance
_job_queue: Optional[JobQueue] = None


async def get_job_queue() -> JobQueue:
    """Get or create global job queue instance"""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
        await _job_queue.start()
    return _job_queue


async def init_job_queue():
    """Initialize job queue on app startup"""
    queue = await get_job_queue()
    return queue


async def shutdown_job_queue():
    """Shutdown job queue on app shutdown"""
    global _job_queue
    if _job_queue:
        await _job_queue.stop()
        _job_queue = None


# ═══════════════════════════════════════════════════════════════════════════════
# TTS and Whisper Job Handlers
# ═══════════════════════════════════════════════════════════════════════════════


async def process_tts_job(job: Job):
    """
    Process TTS generation job
    """
    import tempfile
    import soundfile as sf
    from model_manager import generate_speech_unified

    data = job.data
    text = data.get("text", "")
    voice_id = data.get("voice_id")
    tts_engine = data.get("tts_engine", "qwen")
    user_id = data.get("user_id")

    logger.info(f"🎙️ Processing TTS job {job.id} for user {user_id}")

    try:
        # Generate speech using unified TTS
        audio_prompt = voice_id if voice_id and os.path.exists(voice_id) else None

        sr, wav = generate_speech_unified(
            text=text,
            engine=tts_engine,
            audio_prompt=audio_prompt,
            temperature=0.5,
            auto_unload=True,  # Unload after generation to free memory
        )

        if sr is None or wav is None:
            raise Exception("TTS generation failed - no audio produced")

        # Save audio file
        filename = f"tts_{job.id}_{uuid.uuid4().hex[:8]}.wav"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        sf.write(filepath, wav, sr)

        audio_path = f"/api/audio/{filename}"

        # Calculate processing time (handle timezone-aware vs naive datetimes)
        processing_time = None
        if job.created_at:
            try:
                from datetime import timezone

                now = datetime.now(timezone.utc)
                created = job.created_at
                if created.tzinfo is None:
                    # Make naive datetime timezone-aware
                    created = created.replace(tzinfo=timezone.utc)
                processing_time = (now - created).total_seconds()
            except Exception:
                processing_time = None

        result = {
            "status": "completed",
            "audio_path": audio_path,
            "tts_engine": tts_engine,
            "text_length": len(text),
            "processing_time": processing_time,
        }

        logger.info(f"✅ TTS job {job.id} completed. Audio: {audio_path}")
        await job.done(result)

    except Exception as e:
        logger.error(f"❌ TTS job {job.id} failed: {e}")
        await job.fail(str(e))


async def process_whisper_job(job: Job):
    """
    Process Whisper transcription job
    """
    from model_manager import transcribe_with_whisper_optimized

    data = job.data
    audio_path = data.get("audio_path")
    user_id = data.get("user_id")

    logger.info(f"🎤 Processing Whisper job {job.id} for user {user_id}")

    try:
        if not audio_path or not os.path.exists(audio_path):
            raise Exception(f"Audio file not found: {audio_path}")

        text = transcribe_with_whisper_optimized(audio_path)

        result = {
            "status": "completed",
            "text": text,
            "audio_path": audio_path,
            "processing_time": (datetime.utcnow() - job.created_at).total_seconds()
            if job.created_at
            else None,
        }

        logger.info(f"✅ Whisper job {job.id} completed. Text length: {len(text)}")
        await job.done(result)

    except Exception as e:
        logger.error(f"❌ Whisper job {job.id} failed: {e}")
        await job.fail(str(e))


async def enqueue_tts_job(
    text: str,
    voice_id: Optional[str] = None,
    tts_engine: str = "qwen",
    user_id: Optional[int] = None,
) -> str:
    """
    Enqueue a TTS job for background processing

    Returns:
        job_id: Unique identifier for tracking the job
    """
    queue = await get_job_queue()

    job_id = await queue.send(
        name="tts-generation",
        data={
            "text": text,
            "voice_id": voice_id,
            "tts_engine": tts_engine,
            "user_id": user_id,
        },
        retry_limit=2,  # Retry up to 2 times on failure
        priority=10,  # Higher priority for TTS
    )

    logger.info(f"📥 Enqueued TTS job {job_id}")
    return job_id


async def enqueue_whisper_job(audio_path: str, user_id: Optional[int] = None) -> str:
    """
    Enqueue a Whisper transcription job

    Returns:
        job_id: Unique identifier for tracking the job
    """
    queue = await get_job_queue()

    job_id = await queue.send(
        name="whisper-transcription",
        data={"audio_path": audio_path, "user_id": user_id},
        retry_limit=2,
        priority=5,
    )

    logger.info(f"📥 Enqueued Whisper job {job_id}")
    return job_id


async def start_tts_worker():
    """Start the TTS worker"""
    queue = await get_job_queue()
    queue.work("tts-generation", process_tts_job)
    logger.info("👷 TTS worker started")


async def start_whisper_worker():
    """Start the Whisper worker"""
    queue = await get_job_queue()
    queue.work("whisper-transcription", process_whisper_job)
    logger.info("👷 Whisper worker started")
