"""
TTS/Whisper background worker — runs as a separate pod with CPU-only device.
Processes 'tts-generation' and 'whisper-transcription' queues from PostgreSQL.
"""
import asyncio
import logging
import os
import sys

# Ensure python_back_end is on path when run standalone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_queue import init_job_queue, start_tts_worker, start_whisper_worker, shutdown_job_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("tts_worker")


async def run_worker() -> None:
    logger.info(
        "🎙️  TTS/Whisper worker starting (device: TTS=%s WHISPER=%s)",
        os.getenv("TTS_DEVICE", "cuda"),
        os.getenv("WHISPER_DEVICE", "cuda"),
    )

    queue = await init_job_queue()
    await start_tts_worker()
    await start_whisper_worker()
    logger.info("✅ Listening on tts-generation + whisper-transcription queues")

    # Keep alive
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down tts-worker")
        await shutdown_job_queue()


if __name__ == "__main__":
    asyncio.run(run_worker())
