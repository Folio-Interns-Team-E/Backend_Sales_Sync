import asyncio
import logging
import os

from app.database import SessionLocal
from app.services.sequence_delivery_service import process_due_enrollments

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def run() -> None:
    interval = max(10, int(os.getenv("SEQUENCE_WORKER_INTERVAL_SECONDS", "60")))
    batch_size = max(1, min(100, int(os.getenv("SEQUENCE_WORKER_BATCH_SIZE", "20"))))
    logger.info("Sequence worker started interval=%ss batch=%s", interval, batch_size)
    while True:
        try:
            async with SessionLocal() as db:
                result = await process_due_enrollments(db, batch_size)
                if result["claimed"]:
                    logger.info("Sequence delivery batch: %s", result)
        except Exception:
            logger.exception("Sequence worker batch failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run())
