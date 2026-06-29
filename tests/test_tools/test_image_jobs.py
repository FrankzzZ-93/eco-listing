"""Unit tests for the persistent image-generation job store."""
import time

import pytest

from app.tools import image_jobs as ij


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(ij.settings, "artifacts_dir", str(tmp_path))
    ij._locks.clear()
    yield


@pytest.mark.asyncio
async def test_create_list_update_lifecycle():
    job = await ij.create_job("run1", {"prompt": "a mug", "n": 2, "size": "1024x1024"})
    assert job["status"] == "running"

    listed = ij.list_jobs("run1")
    assert len(listed) == 1 and listed[0]["id"] == job["id"]
    assert listed[0]["prompt"] == "a mug"

    await ij._update_job("run1", job["id"], status="completed", images=["/artifacts/run1/generated/x.png"])
    done = ij.list_jobs("run1")[0]
    assert done["status"] == "completed"
    assert done["images"] == ["/artifacts/run1/generated/x.png"]


@pytest.mark.asyncio
async def test_list_jobs_newest_first():
    a = await ij.create_job("run1", {"prompt": "first"})
    await ij._update_job("run1", a["id"], created_at=time.time() - 100)
    b = await ij.create_job("run1", {"prompt": "second"})
    ids = [j["id"] for j in ij.list_jobs("run1")]
    assert ids[0] == b["id"]  # newest first


@pytest.mark.asyncio
async def test_running_job_past_timeout_reported_failed():
    job = await ij.create_job("run1", {"prompt": "stuck"})
    # Backdate well beyond the stale window so it's surfaced as failed.
    await ij._update_job("run1", job["id"], created_at=time.time() - ij._stale_seconds() - 10)
    reported = ij.list_jobs("run1")[0]
    assert reported["status"] == "failed"
    assert "超时" in (reported["error"] or "")


def test_list_jobs_empty_for_unknown_run():
    assert ij.list_jobs("nope") == []


@pytest.mark.asyncio
async def test_run_job_records_completion(monkeypatch):
    async def fake_gen(run_id, prompt, **kw):
        return ["/artifacts/run1/generated/a.png", "/artifacts/run1/generated/b.png"]
    monkeypatch.setattr(ij, "generate_images", fake_gen)

    job = await ij.create_job("run1", {"prompt": "x", "n": 2})
    await ij.run_job("run1", job["id"], {"prompt": "x", "n": 2}, [])

    done = ij.list_jobs("run1")[0]
    assert done["status"] == "completed"
    assert len(done["images"]) == 2


@pytest.mark.asyncio
async def test_run_job_records_failure(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("codex blew up")
    monkeypatch.setattr(ij, "generate_images", boom)

    job = await ij.create_job("run1", {"prompt": "x"})
    await ij.run_job("run1", job["id"], {"prompt": "x"}, [])

    done = ij.list_jobs("run1")[0]
    assert done["status"] == "failed"
    assert "codex blew up" in done["error"]
