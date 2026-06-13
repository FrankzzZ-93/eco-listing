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

        _state.load_registry()
        await _recover_stale_runs(graph)

        yield

    await browser.close()


async def _recover_stale_runs(graph):
    """On startup, resume any runs stuck in 'running' with no live task."""
    import asyncio
    import logging
    from app.api._state import list_runs, get_run_task, set_run_task

    logger = logging.getLogger("eco_listing")
    terminal_statuses = {"completed", "failed", "stopped"}

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
            waiting_nodes = {"wait_upload", "human_review", "keyword_upload", "keyword_classify_review"}

            if status in terminal_statuses:
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
