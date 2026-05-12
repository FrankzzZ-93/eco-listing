from __future__ import annotations

import asyncio
import datetime
import json
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.memory.shared_memory import MemoryHelper

router = APIRouter(prefix="/api")

PROMPTS_DIR = "prompts"


# --- Request / Response models ---


class CreateRunRequest(BaseModel):
    product_name: str = ""
    competitor_asins: list[str]
    site: str = "amazon.com.au"


class SubmitReviewRequest(BaseModel):
    type: str = "product_attributes"
    approved_data: dict
    feedback: str = ""


class UpdatePromptRequest(BaseModel):
    content: str


# --- Endpoints ---


@router.post("/runs", status_code=201)
async def create_run(req: CreateRunRequest):
    from app.api._state import get_graph, get_toolbox

    if not req.competitor_asins or len(req.competitor_asins) > 10:
        raise HTTPException(400, "需要 1~10 个 ASIN")

    run_id = f"run_{datetime.date.today():%Y%m%d}_{uuid.uuid4().hex[:6]}"
    initial_state = {
        "run_id": run_id,
        "competitor_asins": req.competitor_asins,
        "status": "running",
    }

    asyncio.create_task(_run_graph(run_id, initial_state))
    return {"run_id": run_id, "status": "running"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    snapshot = state.values
    next_nodes = state.next if state.next else ()

    if next_nodes and any(n in next_nodes for n in ("wait_upload", "human_review", "keyword_upload")):
        effective_status = "waiting_human"
        pending = _pending_action_for(next_nodes)
    else:
        effective_status = snapshot.get("status", "running")
        pending = snapshot.get("pending_action")

    return {
        "run_id": run_id,
        "status": effective_status,
        "next_step": list(next_nodes) if next_nodes else None,
        "memory_snapshot": {
            key: MemoryHelper.has(snapshot, key)
            for key in [
                "competitor_listings",
                "review_summary",
                "approved_product_attributes",
                "classified_keywords",
                "final_listing",
                "final_st",
            ]
        },
        "pending_action": pending,
        "agent_log": snapshot.get("agent_log", [])[-20:],
    }


def _pending_action_for(next_nodes) -> dict:
    if "wait_upload" in next_nodes:
        return {"type": "upload_competitor_data", "message": "请上传竞品 Listing JSON"}
    if "human_review" in next_nodes:
        return {"type": "review_product_attributes", "message": "请审核产品属性"}
    if "keyword_upload" in next_nodes:
        return {"type": "upload_keywords", "message": "请上传关键词 JSON"}
    return {}


@router.put("/runs/{run_id}/review")
async def submit_review(run_id: str, req: SubmitReviewRequest):
    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    update = {
        "approved_product_attributes": req.approved_data,
        "status": "running",
        "pending_action": {},
    }
    await graph.aupdate_state(config, update)
    asyncio.create_task(_resume_graph(run_id))
    return {"status": "accepted"}


@router.put("/runs/{run_id}/upload")
async def upload_data(
    run_id: str,
    file: UploadFile = File(...),
    data_type: str = "auto",
):
    graph = _get_graph()
    toolbox = _get_toolbox()
    config = {"configurable": {"thread_id": run_id}}
    content = await file.read()

    if file.filename and file.filename.endswith(".json"):
        data = json.loads(content)
        if data_type == "keywords" or (
            data_type == "auto" and "keyword" in str(data)[:200]
        ):
            cleaned = toolbox.keyword.clean(data)
            update = {
                "keyword_library": cleaned,
                "status": "running",
                "pending_action": {},
            }
        else:
            update = {
                "competitor_listings": data,
                "status": "running",
                "pending_action": {},
            }
        await graph.aupdate_state(config, update)
        asyncio.create_task(_resume_graph(run_id))

    elif file.filename and file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        save_path = toolbox.file_store.run_dir(run_id) + f"/{file.filename}"
        with open(save_path, "wb") as f:
            f.write(content)
        state = await graph.aget_state(config)
        existing = state.values.get("rufus_screenshots", []) if state else []
        existing.append(save_path)
        await graph.aupdate_state(config, {"rufus_screenshots": existing})
        return {"status": "accepted", "saved": save_path}
    else:
        raise HTTPException(400, "支持 .json / .png / .jpg 文件")

    return {"status": "accepted"}


@router.get("/runs/{run_id}/final")
async def get_final(run_id: str):
    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404)
    s = state.values
    if s.get("status") != "completed":
        raise HTTPException(400, f"Run 未完成: {s.get('status')}")
    return {
        "final_listing": s["final_listing"],
        "final_st": s["final_st"],
        "word_frequency_report": s.get("word_frequency_report", {}),
        "download": {
            "json": f"/artifacts/{run_id}/final/final_listing.json",
            "markdown": f"/artifacts/{run_id}/final/final_listing.md",
        },
    }


# --- Prompt Management Endpoints ---


@router.get("/prompts")
async def list_prompts():
    """List all prompt files with metadata."""
    results = []
    if not os.path.isdir(PROMPTS_DIR):
        return results

    for agent_dir in sorted(os.listdir(PROMPTS_DIR)):
        agent_path = os.path.join(PROMPTS_DIR, agent_dir)
        if not os.path.isdir(agent_path):
            continue
        for filename in sorted(os.listdir(agent_path)):
            if not filename.endswith(".md"):
                continue
            override_path = os.path.join(agent_path, f".override_{filename}")
            results.append({
                "agent": agent_dir,
                "name": filename.removesuffix(".md"),
                "filename": filename,
                "modified": os.path.exists(override_path),
            })
    return results


@router.get("/prompts/{agent}/{name}")
async def get_prompt(agent: str, name: str):
    """Get prompt content. Returns override if exists, otherwise default."""
    base_path = os.path.join(PROMPTS_DIR, agent, f"{name}.md")
    override_path = os.path.join(PROMPTS_DIR, agent, f".override_{name}.md")

    if os.path.exists(override_path):
        with open(override_path, encoding="utf-8") as f:
            content = f.read()
        modified = True
    elif os.path.exists(base_path):
        with open(base_path, encoding="utf-8") as f:
            content = f.read()
        modified = False
    else:
        raise HTTPException(404, f"Prompt not found: {agent}/{name}")

    return {
        "agent": agent,
        "name": name,
        "content": content,
        "modified": modified,
    }


@router.put("/prompts/{agent}/{name}")
async def update_prompt(agent: str, name: str, req: UpdatePromptRequest):
    """Save prompt override."""
    agent_path = os.path.join(PROMPTS_DIR, agent)
    base_path = os.path.join(agent_path, f"{name}.md")

    if not os.path.exists(base_path):
        raise HTTPException(404, f"Prompt not found: {agent}/{name}")

    override_path = os.path.join(agent_path, f".override_{name}.md")
    with open(override_path, "w", encoding="utf-8") as f:
        f.write(req.content)

    return {"status": "saved", "agent": agent, "name": name}


@router.delete("/prompts/{agent}/{name}")
async def reset_prompt(agent: str, name: str):
    """Reset prompt to default by removing override file."""
    override_path = os.path.join(PROMPTS_DIR, agent, f".override_{name}.md")
    if os.path.exists(override_path):
        os.remove(override_path)
    return {"status": "reset", "agent": agent, "name": name}


# --- Helpers ---


def _get_graph():
    from app.api._state import get_graph

    return get_graph()


def _get_toolbox():
    from app.api._state import get_toolbox

    return get_toolbox()


async def _run_graph(thread_id: str, initial_state: dict):
    graph = _get_graph()
    await graph.ainvoke(initial_state, {"configurable": {"thread_id": thread_id}})


async def _resume_graph(thread_id: str):
    graph = _get_graph()
    await graph.ainvoke(None, {"configurable": {"thread_id": thread_id}})
