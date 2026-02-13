"""
Document Generation Worker
Processes document generation jobs from the queue
"""

import os
import sys
import json
import uuid
import asyncio
import logging
from typing import Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_queue import JobQueue, Job, get_job_queue, init_job_queue, shutdown_job_queue
from artifacts.code_generator import generate_document_from_code
from artifacts.storage import get_artifact_storage
import asyncpg

logger = logging.getLogger(__name__)

# Initialize artifact storage
artifact_storage = get_artifact_storage()


async def update_document_job(
    pool: asyncpg.Pool,
    job_id: str,
    status: str,
    result: Dict[str, Any] = None,
    error: str = None,
):
    """Update document_jobs table with status"""
    try:
        update_data = {"status": status, "updated_at": "NOW()"}

        if result:
            update_data["result"] = json.dumps(result)
        if error:
            update_data["result"] = json.dumps({"error": error})
        if status in ["completed", "failed"]:
            update_data["completed_at"] = "NOW()"
        if status == "processing":
            update_data["started_at"] = "NOW()"

        # Build dynamic query
        fields = []
        values = []
        for key, val in update_data.items():
            if val == "NOW()":
                fields.append(f"{key} = NOW()")
            else:
                fields.append(f"{key} = ${len(values) + 2}")
                values.append(val)

        query = f"""
            UPDATE document_jobs 
            SET {", ".join(fields)}
            WHERE id = $1
        """

        await pool.execute(query, job_id, *values)

    except Exception as e:
        logger.error(f"Failed to update document job {job_id}: {e}")


async def process_document_job(job: Job):
    """
    Process a document generation job
    This is called by the worker when a job is fetched from the queue
    """
    job_data = job.data
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))

    try:
        # Extract job details
        document_job_id = job_data.get("document_job_id")
        code = job_data.get("code")
        doc_type = job_data.get("document_type")
        title = job_data.get("title")
        user_id = job_data.get("user_id")

        logger.info(f"📄 Processing document job: {document_job_id} ({doc_type})")

        # Update job status to processing
        await update_document_job(pool, document_job_id, "processing")

        # Generate the document
        result = generate_document_from_code(
            llm_response=code,
            artifact_type=doc_type,
            title=title,
            artifact_id=str(uuid.uuid4()),
            use_docker=True,
        )

        if result.get("success"):
            # Save artifact to database
            artifact_data = {
                "id": result["artifact_id"],
                "type": doc_type,
                "title": title,
                "file_path": result["file_path"],
                "file_size": result.get("file_size", 0),
                "mime_type": result.get("mime_type", "application/octet-stream"),
                "user_id": user_id,
                "created_at": "NOW()",
                "status": "ready",
            }

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO artifacts (id, artifact_type, title, file_path, 
                                         file_size, mime_type, user_id, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        file_path = EXCLUDED.file_path,
                        file_size = EXCLUDED.file_size
                """,
                    artifact_data["id"],
                    artifact_data["type"],
                    artifact_data["title"],
                    artifact_data["file_path"],
                    artifact_data["file_size"],
                    artifact_data["mime_type"],
                    artifact_data["user_id"],
                    artifact_data["status"],
                )

            # Update document_jobs with result
            job_result = {
                "artifact_id": result["artifact_id"],
                "download_url": f"/api/artifacts/{result['artifact_id']}/download",
                "file_path": result["file_path"],
                "file_size": result.get("file_size", 0),
            }

            await update_document_job(pool, document_job_id, "completed", job_result)

            # Complete the queue job with result
            await job.done(
                {
                    "artifact_id": result["artifact_id"],
                    "download_url": job_result["download_url"],
                    "status": "ready",
                }
            )

            logger.info(f"✅ Document job completed: {document_job_id}")

        else:
            error_msg = result.get("error", "Document generation failed")
            logger.error(f"❌ Document generation failed: {error_msg}")

            await update_document_job(pool, document_job_id, "failed", error=error_msg)
            await job.fail(error_msg)

    except Exception as e:
        logger.exception(f"💥 Document job error: {e}")
        await update_document_job(pool, document_job_id, "failed", error=str(e))
        await job.fail(str(e))
    finally:
        await pool.close()


async def run_worker():
    """
    Run the document generation worker
    This is the entry point for the worker process
    """
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("🚀 Starting Document Generation Worker...")

    # Initialize job queue
    queue = await init_job_queue()

    # Register worker for 'generate-document' queue
    queue.work("generate-document", process_document_job)

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down worker...")
        await shutdown_job_queue()


if __name__ == "__main__":
    asyncio.run(run_worker())
