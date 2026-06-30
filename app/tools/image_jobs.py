"""Persistent image-generation jobs, per run.

Image generation runs for 1-3 minutes, so the HTTP request can't hold the
result: a page refresh would lose it. Instead each generation is a persisted
**job** (status running/completed/failed) stored as a JSON sidecar at
``artifacts/{run_id}/image_jobs.json``. The endpoint kicks off an asyncio task
and returns immediately; the frontend polls ``GET /images/jobs`` to render both
in-progress jobs and the full history, and recovers them after a refresh.

Decoupled from the LangGraph checkpoint state — jobs only need a run_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from app.config import settings
from app.tools.image_gen_tool import generate_images

logger = logging.getLogger(__name__)

# Per-run lock serializing the read-modify-write of the jobs JSON so concurrent
# jobs can't clobber each other's status updates.
_locks: dict[str, asyncio.Lock] = {}
# Buffer added on top of the codex timeout before a still-"running" job (e.g.
# orphaned by a server restart) is reported as failed.
_STALE_BUFFER_SECONDS = 180


def _lock(run_id: str) -> asyncio.Lock:
    lock = _locks.get(run_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[run_id] = lock
    return lock


def _jobs_path(run_id: str) -> str:
    d = os.path.join(settings.artifacts_dir, run_id)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "image_jobs.json")


def _read(run_id: str) -> list[dict]:
    path = _jobs_path(run_id)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        logger.warning("image_jobs read failed for %s", run_id, exc_info=True)
        return []


def _write(run_id: str, jobs: list[dict]) -> None:
    path = _jobs_path(run_id)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic-ish swap


def _stale_seconds() -> int:
    from app import app_settings

    return app_settings.get_scrape_param("codex_timeout", settings.codex_timeout) + _STALE_BUFFER_SECONDS


def list_jobs(run_id: str) -> list[dict]:
    """Return jobs newest-first. A job left "running" past the codex timeout
    (e.g. orphaned by a restart) is surfaced as failed without rewriting it."""
    jobs = _read(run_id)
    cutoff = time.time() - _stale_seconds()
    out: list[dict] = []
    for job in jobs:
        if job.get("status") == "running" and job.get("created_at", 0) < cutoff:
            job = {**job, "status": "failed", "error": "任务超时或已中断"}
        out.append(job)
    out.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return out


async def create_job(run_id: str, params: dict) -> dict:
    """Append a new running job and return it."""
    job = {
        "id": uuid.uuid4().hex[:12],
        "status": "running",
        "prompt": params.get("prompt", ""),
        "n": params.get("n", 1),
        "size": params.get("size", ""),
        "quality": params.get("quality", ""),
        "white_bg": params.get("white_bg", False),
        "reference_urls": params.get("reference_urls", []),
        "images": [],
        "error": None,
        "error_log": None,  # /artifacts URL of a full failure report, when failed
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    async with _lock(run_id):
        jobs = _read(run_id)
        jobs.append(job)
        _write(run_id, jobs)
    return job


async def _update_job(run_id: str, job_id: str, **fields) -> None:
    async with _lock(run_id):
        jobs = _read(run_id)
        for job in jobs:
            if job.get("id") == job_id:
                job.update(fields)
                job["updated_at"] = time.time()
                break
        _write(run_id, jobs)


async def run_job(run_id: str, job_id: str, params: dict, reference_paths: list[str]) -> None:
    """Execute one generation job and persist its outcome. Never raises."""
    try:
        urls = await generate_images(
            run_id,
            params["prompt"],
            n=params.get("n", 1),
            size=params.get("size", "1024x1024"),
            quality=params.get("quality", "high"),
            reference_paths=reference_paths,
            white_bg=params.get("white_bg", False),
            job_id=job_id,
        )
        await _update_job(run_id, job_id, status="completed", images=urls)
    except Exception as e:
        # Persist the full error + a link to the downloadable detail log (set by
        # ImageGenError) so a failure on another machine is fully diagnosable.
        log_url = getattr(e, "log_url", None)
        logger.error("image job %s failed for run %s", job_id, run_id, exc_info=True)
        await _update_job(run_id, job_id, status="failed", error=str(e), error_log=log_url)
