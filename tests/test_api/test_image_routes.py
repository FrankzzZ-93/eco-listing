"""Endpoint-wiring tests for the async image-generation job flow.

Exercises the route functions directly (no live server / codex): generation must
create a running job, spawn a background task, and the task's outcome must be
visible via the jobs listing — i.e. results survive beyond the request.
"""
import asyncio

import pytest

from app.api import routes
from app.tools import image_jobs as ij


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(ij.settings, "artifacts_dir", str(tmp_path))
    ij._locks.clear()
    routes._image_job_tasks.clear()
    yield


@pytest.mark.asyncio
async def test_generate_creates_job_and_background_task_records_result(monkeypatch):
    async def fake_gen(run_id, prompt, **kw):
        return [f"/artifacts/{run_id}/generated/out.png"]
    monkeypatch.setattr(ij, "generate_images", fake_gen)

    req = routes.GenerateImagesRequest(prompt="a white mug", n=1, size="1024x1024")
    resp = await routes.generate_run_images("run1", req)

    assert resp["job"]["status"] == "running"
    # The endpoint returns immediately with a running job (survives a refresh).
    assert routes.list_run_image_jobs.__name__  # sanity

    # Let the fire-and-forget task finish, then the persisted job is completed.
    await asyncio.gather(*list(routes._image_job_tasks))
    jobs = (await routes.list_run_image_jobs("run1"))["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "completed"
    assert jobs[0]["images"] == ["/artifacts/run1/generated/out.png"]


@pytest.mark.asyncio
async def test_generate_rejects_empty_prompt():
    from fastapi import HTTPException

    req = routes.GenerateImagesRequest(prompt="   ")
    with pytest.raises(HTTPException) as exc:
        await routes.generate_run_images("run1", req)
    assert exc.value.status_code == 400
