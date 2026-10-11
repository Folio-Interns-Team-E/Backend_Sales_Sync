import asyncio
import logging
import os

from app.database import SessionLocal
from app.services.sequence_delivery_service import process_due_enrollments
from app.services.inbound_email_service import detect_sequence_replies_and_bounces
from app.core.observability import configure_logging
from app.core.worker_health import record_sequence_worker_heartbeat

configure_logging()
logger = logging.getLogger(__name__)


async def run() -> None:
    interval = max(10, int(os.getenv("SEQUENCE_WORKER_INTERVAL_SECONDS", "60")))
    batch_size = max(1, min(100, int(os.getenv("SEQUENCE_WORKER_BATCH_SIZE", "20"))))
    logger.info("Sequence worker started interval=%ss batch=%s", interval, batch_size)
    consecutive_failures = 0
    while True:
        try:
            async with SessionLocal() as db:
                inbound = await detect_sequence_replies_and_bounces(db, batch_size)
                if inbound["checked"]:
                    logger.info("Sequence inbox batch: %s", inbound)
                result = await process_due_enrollments(db, batch_size)
                if result["claimed"]:
                    logger.info("Sequence delivery batch: %s", result)
            await record_sequence_worker_heartbeat(interval)
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            logger.exception("Sequence worker batch failed")
            if consecutive_failures >= 3:
                logger.critical("Sequence worker stopped after three consecutive failed batches")
                raise
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run())
