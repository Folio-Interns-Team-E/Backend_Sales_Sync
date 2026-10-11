import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.core import worker_health
from app.routers import health


async def test_worker_heartbeat_expires_when_batches_stop():
    redis = MagicMock()
    redis.get.return_value = "ok"
    with patch.object(worker_health, "get_redis", return_value=redis):
        await worker_health.record_sequence_worker_heartbeat(60)
        assert await worker_health.sequence_worker_is_healthy()
    redis.set.assert_called_once_with(worker_health.SEQUENCE_WORKER_HEARTBEAT_KEY, "ok", ex=210)


@pytest.mark.parametrize("healthy,status", [(True, 200), (False, 503)])
async def test_worker_readiness_reports_stale_heartbeat_without_details(healthy, status):
    async def check():
        return healthy

    with patch.object(health, "sequence_worker_is_healthy", check):
        response = await health.sequence_worker_readiness()
    assert response.status_code == status
    assert json.loads(response.body)["data"] == {"sequence_worker": healthy}
    assert response.headers["Cache-Control"] == "no-store"


async def test_worker_exits_after_three_consecutive_batch_failures():
    from app.workers import sequence_worker
    @asynccontextmanager
    async def failing_session():
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    async def no_sleep(_):
        pass

    with patch.object(sequence_worker, "SessionLocal", failing_session), patch.object(
        sequence_worker.asyncio, "sleep", no_sleep
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await sequence_worker.run()
