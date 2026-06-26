from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.base import ToolBox
from app.agents.orchestrator import create_app_graph
from app.agents.prompts import PromptRegistry
from app.api import _state
from app.api.routes import router
from app.config import settings
from app.errors import EcoListingError
from app.tools.browser_tool import BrowserTool
from app.tools.compliance_tool import ComplianceTool
from app.tools.file_store import FileStoreTool
from app.tools.keyword_tool import KeywordTool
from app.tools.llm_tool import LLMTool

if not hasattr(aiosqlite.Connection, "is_alive"):
    aiosqlite.Connection.is_alive = lambda self: getattr(self, "_running", True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    browser = BrowserTool()

    toolbox = ToolBox(
        llm=LLMTool(),
        keyword=KeywordTool(),
        compliance=ComplianceTool(),
        file_store=FileStoreTool(settings.artifacts_dir),
        prompts=PromptRegistry(),
        browser=browser,
    )

    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as checkpointer:
        graph = create_app_graph(toolbox, checkpointer)

        _state.set_toolbox(toolbox)
        _state.set_graph(graph)

        from app.llm_settings import load_llm_settings
        load_llm_settings()

        from app.app_settings import load_app_settings
        load_app_settings()

        _state.load_registry()
        await _reconcile_registry(graph)
        await _recover_stale_runs(graph)

        yield

    await browser.close()


def _created_at_from_run_id(run_id: str) -> str:
    """Best-effort creation time for a reconciled run, parsed from its id
    (``run_YYYYMMDD_xxxxxx``); falls back to now when it doesn't match."""
    import datetime
    import re

    m = re.match(r"run_(\d{4})(\d{2})(\d{2})_", run_id)
    if m:
        try:
            y, mo, d = (int(g) for g in m.groups())
            return datetime.datetime(y, mo, d, tzinfo=datetime.timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _reconcile_registry(graph):
    """Rebuild the run registry from checkpoints ONLY when the registry is empty.

    The registry (run_registry.json) is the source of truth for which runs the
    user cares about; the authoritative per-run state lives in the checkpoint DB.
    Reconciliation exists purely to recover from a *wiped* index (the desync
    incident where run_registry.json became ``{}`` while checkpoints kept the
    data) — so the run list doesn't go permanently blank.

    It deliberately does NOT run when the registry already has entries. Re-adding
    every checkpoint thread on each boot would resurface long-abandoned runs
    (pending / waiting_human that were never finished) and even undo user
    deletes whose checkpoints predate the purge-on-delete fix — flooding the
    homepage's "进行中" list with stale tasks. Trust the curated registry; only
    rebuild from scratch when there's nothing to trust.
    """
    import logging

    logger = logging.getLogger("eco_listing")

    # Registry already has content -> trust it; don't pull orphaned checkpoints
    # (abandoned/old runs) back into the list.
    if _state.list_runs():
        return

    thread_ids = _state.checkpoint_thread_ids(settings.checkpoint_db)
    new_entries: list[dict] = []
    for tid in thread_ids:
        if _state.has_run(tid):
            continue
        try:
            state = await graph.aget_state({"configurable": {"thread_id": tid}})
            if not state or not state.values:
                continue
            v = state.values
            new_entries.append({
                "run_id": tid,
                # product_name isn't part of graph state, so it can't be
                # recovered — left blank (matches runs created without one).
                "product_name": "",
                "site": v.get("site", "amazon.com"),
                "competitor_asins": v.get("competitor_asins", []),
                "created_at": _created_at_from_run_id(tid),
            })
        except Exception:
            logger.warning("Failed to reconcile run %s", tid, exc_info=True)

    added = _state.register_runs_bulk(new_entries)
    if added:
        logger.warning("Reconciled %d run(s) into the registry from checkpoints", added)


async def _recover_stale_runs(graph):
    """On startup, resume only runs left mid-execution (status 'running') with
    no live task.

    Restricted to ``running`` on purpose: a ``pending`` run was created but never
    started by the user, and terminal runs (completed/failed/stopped) are done —
    none of those should auto-start. This matters now that the registry is
    reconciled from checkpoints (see _reconcile_registry), which re-surfaces such
    runs; without this guard a reconciled ``pending`` run would scrape on boot.
    """
    import asyncio
    import logging
    from app.api._state import list_runs, get_run_task, set_run_task

    logger = logging.getLogger("eco_listing")

    for meta in list_runs():
        run_id = meta["run_id"]
        existing = get_run_task(run_id)
        if existing and not existing.done():
            continue

        try:
            config = {"configurable": {"thread_id": run_id}}
            state = await graph.aget_state(config)
            if not state or not state.values:
                continue

            status = state.values.get("status", "")
            next_nodes = state.next if state.next else ()
            waiting_nodes = {"wait_upload", "wait_verify", "human_review", "keyword_upload", "keyword_classify_review"}

            if status != "running":
                continue
            if any(n in next_nodes for n in waiting_nodes):
                continue
            if not next_nodes:
                continue

            logger.warning("Recovering stale run %s (status=%s, next=%s)", run_id, status, next_nodes)
            from app.api.routes import _resume_graph
            task = asyncio.create_task(_resume_graph(run_id))
            set_run_task(run_id, task)
        except Exception:
            logger.error("Failed to recover run %s", run_id, exc_info=True)


app = FastAPI(title="Eco Listing Agent", version="0.2.0-mvp", lifespan=lifespan)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


@app.exception_handler(EcoListingError)
async def handle_eco_listing_error(req, exc):
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "message": str(exc)},
    )
