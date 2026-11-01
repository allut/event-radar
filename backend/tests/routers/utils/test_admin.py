"""Unit tests for app.routers.utils.admin."""

import asyncio
import json
from unittest.mock import patch

import pytest

from app.routers.utils.admin import stream_admin_job


class TestStreamAdminJob:
    """Regression coverage for issue #159: Starlette's StreamingResponse
    cancels its streaming generator on a client disconnect (task-group race
    against listen_for_disconnect on uvicorn's pinned ASGI spec_version
    "2.3"). stream_admin_job must not let that cancellation reach the
    job coroutine itself: the job has to keep running to completion (and
    still get logged) even after the consumer stops reading."""

    @pytest.mark.asyncio
    async def test_job_completes_and_logs_after_generator_is_cancelled(self):
        job_done = asyncio.Event()

        async def slow_job() -> dict:
            await asyncio.sleep(0.05)
            job_done.set()
            return {"ok": True}

        with patch("app.routers.utils.admin.log_admin_action") as mock_log:
            gen = stream_admin_job("Test", "test", "test_action", "target", slow_job())
            first = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.01)  # let the runner task start; job is still sleeping
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await gen.aclose()  # what Starlette does to the generator on disconnect

            await asyncio.wait_for(job_done.wait(), timeout=1)
            await asyncio.sleep(0.02)  # let the runner's log_admin_action call land

        mock_log.assert_called_once_with(None, "test_action", "target", {"ok": True})

    @pytest.mark.asyncio
    async def test_normal_completion_streams_one_ok_line(self):
        async def job() -> dict:
            return {"processed": 3}

        with patch("app.routers.utils.admin.log_admin_action") as mock_log:
            lines = [line async for line in stream_admin_job("Test", "test", "test_action", "target", job())]

        assert len(lines) == 1
        assert json.loads(lines[0]) == {"stage": "test", "status": "ok", "result": {"processed": 3}, "error": None}
        mock_log.assert_called_once_with(None, "test_action", "target", {"processed": 3})
