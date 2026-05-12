from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import MemorySaver

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

    checkpointer = MemorySaver()
    graph = create_app_graph(toolbox, checkpointer)

    _state.set_toolbox(toolbox)
    _state.set_graph(graph)

    yield

    await browser.close()


app = FastAPI(title="Eco Listing Agent", version="0.2.0-mvp", lifespan=lifespan)
app.include_router(router)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


@app.exception_handler(EcoListingError)
async def handle_eco_listing_error(req, exc):
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "message": str(exc)},
    )
