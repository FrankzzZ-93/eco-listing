from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings
from app.memory.shared_memory import MemoryHelper
from app.tools import codex_progress

router = APIRouter(prefix="/api")

PROMPTS_DIR = "prompts"

# Graph nodes whose `interrupt_before` makes the run pause for human input.
# Keep in sync with create_app_graph(...).interrupt_before in orchestrator.py.
_WAITING_NODES = (
    "wait_upload",
    "wait_verify",
    "human_review",
    "keyword_upload",
    "keyword_classify_review",
)

# Per-run lock serializing graph-state read-modify-write operations. Without
# it, concurrent uploads (e.g. several files posted in parallel) each read the
# same checkpoint and write back, so the last writer clobbers the others'
# channels (this is how an uploaded keyword_library could silently vanish).
_run_state_locks: dict[str, asyncio.Lock] = {}


def _run_state_lock(run_id: str) -> asyncio.Lock:
    lock = _run_state_locks.get(run_id)
    if lock is None:
        lock = asyncio.Lock()
        _run_state_locks[run_id] = lock
    return lock


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


class GenerateImagesRequest(BaseModel):
    prompt: str
    n: int = 1
    size: str = "1024x1024"
    quality: str = "high"
    # Reference image URLs (e.g. "/artifacts/{run_id}/competitor_images/...") used
    # to keep the generated product consistent. Resolved to local paths server-side.
    reference_urls: list[str] = []
    white_bg: bool = False


# --- Endpoints ---


@router.post("/runs", status_code=201)
async def create_run(req: CreateRunRequest):
    if not req.competitor_asins or len(req.competitor_asins) > 10:
        raise HTTPException(400, "需要 1~10 个 ASIN")

    run_id = f"run_{datetime.date.today():%Y%m%d}_{uuid.uuid4().hex[:6]}"

    graph = _get_graph()
    initial_state = {
        "run_id": run_id,
        "product_name": req.product_name,
        "competitor_asins": req.competitor_asins,
        "site": req.site,
        "status": "pending",
        "length_limits": {
            "title_max_chars": settings.title_max_chars,
            "bullet_max_chars": settings.bullet_max_chars,
            "bullets_total_max_bytes": settings.bullets_total_max_bytes,
            "description_max_chars": settings.description_max_chars,
            "st_max_bytes": settings.st_max_bytes,
            "title_min_chars": settings.title_min_chars,
            "bullets_total_min_bytes": settings.bullets_total_min_bytes,
            "description_min_chars": settings.description_min_chars,
        },
    }
    config = {"configurable": {"thread_id": run_id}}
    await graph.aupdate_state(config, initial_state, as_node="__start__")

    return {"run_id": run_id, "status": "pending"}


@router.post("/runs/{run_id}/start")
async def start_run(run_id: str):
    """Start graph execution after files have been uploaded."""
    from app.api._state import get_run_task, set_run_task

    existing = get_run_task(run_id)
    if existing and not existing.done():
        raise HTTPException(409, "任务已在运行中")

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "任务不存在")

    # _run_graph_from_state flips status to "running"; the run list reads status
    # from the checkpoint, so there's no separate index to update here.
    task = asyncio.create_task(_run_graph_from_state(run_id))
    set_run_task(run_id, task)
    return {"status": "running"}


@router.get("/runs")
async def list_runs():
    from app.api._state import checkpoint_thread_ids, created_at_from_run_id

    run_ids = checkpoint_thread_ids(settings.checkpoint_db)
    graph = _get_graph()

    progress_keys = [
        ("competitor_listings", "竞品数据采集"),
        ("product_attributes_draft", "产品属性分析"),
        ("approved_product_attributes", "人工审核"),
        ("keyword_library", "关键词审核"),
        ("classified_keywords", "关键词分类"),
        ("final_listing", "Listing 文案生成"),
        ("final_st", "ST 词频优化"),
    ]
    total_steps = len(progress_keys)

    results = []
    for rid in run_ids:
        status = "unknown"
        completed_steps = 0
        current_step = ""
        current_agent = None
        product_name = ""
        site = "amazon.com"
        competitor_asins: list = []

        try:
            config = {"configurable": {"thread_id": rid}}
            state = await graph.aget_state(config)
            if state and state.values:
                snapshot = state.values
                product_name = snapshot.get("product_name", "") or ""
                site = snapshot.get("site", "amazon.com")
                competitor_asins = snapshot.get("competitor_asins", []) or []
                status = snapshot.get("status", "running")
                next_nodes = state.next if state.next else ()
                if next_nodes and any(
                    n in next_nodes
                    for n in _WAITING_NODES
                ):
                    status = "waiting_human"

                # When a ready-made attribute table is uploaded, the competitor
                # scraping step is intentionally skipped — treat it as done so
                # progress doesn't get stuck on "竞品数据采集".
                attrs_present = MemoryHelper.has(snapshot, "product_attributes_draft")
                for key, label in progress_keys:
                    done = MemoryHelper.has(snapshot, key)
                    if not done and key == "competitor_listings" and attrs_present:
                        done = True
                    if done:
                        completed_steps += 1
                    elif not current_step:
                        current_step = label

                current_agent = snapshot.get("current_agent")
                if not current_agent:
                    last_logs = snapshot.get("agent_log", [])
                    if last_logs:
                        current_agent = last_logs[-1].get("agent")

                if not current_step and status == "running":
                    current_step = progress_keys[0][1]
        except Exception:
            pass

        results.append({
            "run_id": rid,
            "product_name": product_name,
            "site": site,
            "competitor_asins": competitor_asins,
            "created_at": created_at_from_run_id(rid),
            "status": status,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "current_step": current_step,
            "current_agent": current_agent,
        })

    # Newest first (matches the old registry ordering by created_at desc).
    results.sort(key=lambda r: (r["created_at"], r["run_id"]), reverse=True)
    return results


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    snapshot = state.values
    next_nodes = state.next if state.next else ()

    if next_nodes and any(n in next_nodes for n in _WAITING_NODES):
        effective_status = "waiting_human"
        # A captcha gate stores a rich pending_action (image_url, context) in
        # state; keep it instead of the generic node-derived message.
        stored = snapshot.get("pending_action") or {}
        if "wait_verify" in next_nodes and stored.get("type") == "solve_captcha":
            pending = stored
        else:
            pending = _pending_action_for(next_nodes)
    else:
        effective_status = snapshot.get("status", "running")
        pending = snapshot.get("pending_action")

    mem_keys = [
        "competitor_listings",
        "customer_reviews",
        "review_summary",
        "alex_questions",
        "product_attributes_draft",
        "approved_product_attributes",
        "keyword_library",
        "classified_keywords",
        "final_listing",
        "final_st",
    ]

    current_agent = snapshot.get("current_agent")
    if not current_agent and effective_status == "running":
        last_logs = snapshot.get("agent_log", [])
        if last_logs:
            current_agent = last_logs[-1].get("agent")

    mem_snapshot = {
        f"has_{key}": MemoryHelper.has(snapshot, key)
        for key in mem_keys
    }
    has_kw = mem_snapshot.get("has_keyword_library", False)
    nodes_after_review = {"keyword_classify", "keyword_classify_review", "copywriter", "st_optimize", "export"}
    past_review = (
        MemoryHelper.has(snapshot, "classified_keywords")
        or (bool(next_nodes) and any(n in next_nodes for n in nodes_after_review))
    )
    mem_snapshot["has_keywords_reviewed"] = has_kw and past_review

    live_codex = None
    research_progress = None
    stage_progress = None
    if effective_status == "running":
        try:
            live_codex = codex_progress.snapshot(run_id)
        except Exception:
            live_codex = None
        try:
            research_progress = codex_progress.scrape_snapshot(run_id)
        except Exception:
            research_progress = None
        try:
            stage_progress = codex_progress.stage_snapshot(run_id)
        except Exception:
            stage_progress = None

    return {
        "run_id": run_id,
        "product_name": snapshot.get("product_name", "") or "",
        "status": effective_status,
        "current_agent": current_agent,
        "next_step": list(next_nodes) if next_nodes else None,
        "memory_snapshot": mem_snapshot,
        "pending_action": pending,
        "agent_log": snapshot.get("agent_log", [])[-20:],
        "error": snapshot.get("error") or None,
        "live_codex": live_codex,
        "research_progress": research_progress,
        "stage_progress": stage_progress,
    }


_VIEWABLE_KEYS = frozenset([
    "competitor_listings",
    "customer_reviews",
    "review_summary",
    "alex_questions",
    "product_attributes_draft",
    "approved_product_attributes",
    "keyword_library",
    "classified_keywords",
    "final_listing",
    "final_st",
    "word_frequency_report",
])


@router.get("/runs/{run_id}/screenshots")
async def get_run_screenshots(run_id: str):
    """List captured scrape screenshots (reviews / Alex / verification) so the UI
    can show them for review. The real-Chrome scraper writes PNGs straight into
    the run's artifacts dir, which is served under ``/artifacts/{run_id}/``."""
    import glob
    import re

    asin_re = re.compile(r"(B0[A-Z0-9]{8})")
    base = os.path.join(settings.artifacts_dir, run_id)
    shots: list[dict[str, str]] = []
    if os.path.isdir(base):
        for path in sorted(glob.glob(os.path.join(base, "*.png"))):
            name = os.path.basename(path)
            if name.startswith("reviews_"):
                kind = "reviews"
            elif name.startswith("alex_"):
                kind = "alex"
            elif name.startswith("verify_"):
                kind = "verify"
            else:
                continue  # skip unrelated PNGs (e.g. exported charts)
            m = asin_re.search(name)
            shots.append({
                "name": name,
                "url": f"/artifacts/{run_id}/{name}",
                "kind": kind,
                "asin": m.group(1) if m else "",
            })
    return {"screenshots": shots}


@router.get("/runs/{run_id}/data/{key}")
async def get_run_data(run_id: str, key: str):
    if key not in _VIEWABLE_KEYS:
        raise HTTPException(400, f"不支持查看的数据键: {key}")

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    value = state.values.get(key)
    if value is None:
        raise HTTPException(404, f"数据 '{key}' 尚未产出")

    return {"key": key, "data": value}


def _pending_action_for(next_nodes) -> dict:
    if "wait_upload" in next_nodes:
        return {"type": "upload_competitor_data", "message": "请上传竞品 Listing JSON"}
    if "human_review" in next_nodes:
        return {"type": "review_product_attributes", "message": "请审核产品属性"}
    if "keyword_upload" in next_nodes:
        return {"type": "upload_keywords", "message": "请上传关键词词库"}
    if "keyword_classify_review" in next_nodes:
        return {"type": "review_classified_keywords", "message": "请审核关键词分类结果"}
    if "wait_verify" in next_nodes:
        return {"type": "solve_captcha", "message": "请完成人机验证"}
    return {}


@router.put("/runs/{run_id}/review")
async def submit_review(run_id: str, req: SubmitReviewRequest):
    from app.api._state import set_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    update = {
        "approved_product_attributes": req.approved_data,
        "status": "running",
        "pending_action": {},
    }
    # Keep the draft in sync with the approved edits so that re-opening the
    # review tab (which loads product_attributes_draft) shows the user's edits
    # instead of the stale AI/uploaded draft. Skip on reject (empty approved_data
    # + feedback) so the draft isn't wiped.
    if req.approved_data:
        update["product_attributes_draft"] = req.approved_data
    await graph.aupdate_state(config, update)
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted"}


class SaveAttributesRequest(BaseModel):
    data: dict


@router.put("/runs/{run_id}/attributes")
async def save_attributes(run_id: str, req: SaveAttributesRequest):
    """Persist edited product attributes without resuming the graph.

    Lets the user revise the attribute table after the run has moved past the
    review gate (e.g. before regenerating the listing). Both the draft and the
    approved copy are updated so downstream nodes and the review panel agree.
    Refused while the run is actively running to avoid a mid-node write race.
    """
    if not isinstance(req.data, dict) or not req.data:
        raise HTTPException(400, "属性表需为非空对象")

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    async with _run_state_lock(run_id):
        state = await graph.aget_state(config)
        if not state or not state.values:
            raise HTTPException(404, "Run not found")
        if state.values.get("status") == "running":
            raise HTTPException(400, "任务运行中，暂不能修改属性表")
        await graph.aupdate_state(config, {
            "product_attributes_draft": req.data,
            "approved_product_attributes": req.data,
        })
    return {"status": "saved"}


class RerunFromAttributesRequest(BaseModel):
    # Optional: persist these edited attributes before re-running. When omitted,
    # the currently-saved attributes are used as-is.
    data: Optional[dict] = None


@router.post("/runs/{run_id}/rerun-from-attributes")
async def rerun_from_attributes(run_id: str, req: RerunFromAttributesRequest):
    """Persist edited attributes (if given) and re-run the whole downstream
    pipeline from keyword classification onward.

    The attribute table feeds keyword classification, so a change there should
    propagate through *re-classification* — not just the copy step. We reposition
    the graph as if the attribute-review (``human_review``) just completed; its
    conditional edge then routes to ``keyword_classify`` (keyword library present)
    and the run continues keyword_classify → keyword_classify_review (pause for
    review) → copywriter → st_optimize → export. Contrast with
    ``regenerate-listing``, which only re-runs the copy step with the existing
    classification. Refused while the run is already running.
    """
    from app.api._state import set_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    async with _run_state_lock(run_id):
        state = await graph.aget_state(config)
        if not state or not state.values:
            raise HTTPException(404, "Run not found")
        s = state.values
        if s.get("status") == "running":
            raise HTTPException(400, "任务正在运行中，请等待当前流程完成")
        if not MemoryHelper.has(s, "keyword_library"):
            raise HTTPException(400, "缺少关键词词库，无法重新执行后续流程")

        update = {"status": "running", "pending_action": {}, "error": ""}
        if req.data is not None:
            if not isinstance(req.data, dict) or not req.data:
                raise HTTPException(400, "属性表需为非空对象")
            update["product_attributes_draft"] = req.data
            update["approved_product_attributes"] = req.data

        # Reposition as if attribute review just completed → next is
        # keyword_classify (the conditional edge picks it when a keyword library
        # exists). The classification review gate (interrupt_before) will pause
        # the run again so the user can review the re-classified keywords.
        await graph.aupdate_state(config, update, as_node="human_review")
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted"}


@router.post("/runs/{run_id}/regenerate-listing")
async def regenerate_listing(run_id: str):
    """Re-run only the expression layer (copywriter → st_optimize → export).

    Uses the *current* state — the latest edited attribute table and classified
    keywords, plus the live copywriter model and on-disk prompts — without
    re-scraping or re-classifying. We reposition the graph just after the
    keyword-classification review gate and resume, so only the copy-generation
    tail runs again. Refused while the run is already running.
    """
    from app.api._state import set_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    async with _run_state_lock(run_id):
        state = await graph.aget_state(config)
        if not state or not state.values:
            raise HTTPException(404, "Run not found")
        s = state.values
        if s.get("status") == "running":
            raise HTTPException(400, "任务正在运行中，请等待当前生成完成")
        if not MemoryHelper.has(s, "classified_keywords"):
            raise HTTPException(400, "缺少关键词分类结果，无法重新生成文案")
        if not (
            MemoryHelper.has(s, "approved_product_attributes")
            or MemoryHelper.has(s, "product_attributes_draft")
        ):
            raise HTTPException(400, "缺少产品属性表，无法重新生成文案")

        # Reposition as if keyword_classify_review just completed → next node is
        # copywriter. interrupt_before only fires when *entering* that node, so
        # the resume runs straight through copywriter → st_optimize → export.
        await graph.aupdate_state(
            config,
            {"status": "running", "pending_action": {}, "error": ""},
            as_node="keyword_classify_review",
        )
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted"}


class UpdateProductNameRequest(BaseModel):
    product_name: str


@router.put("/runs/{run_id}/product-name")
async def update_product_name(run_id: str, req: UpdateProductNameRequest):
    """Rename a run (the user-facing label shown in the run list / dashboard)."""
    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")
    await graph.aupdate_state(config, {"product_name": (req.product_name or "").strip()})
    return {"status": "saved"}


@router.post("/runs/{run_id}/rerun-from-keywords")
async def rerun_from_keywords(run_id: str, file: UploadFile = File(...)):
    """Replace the keyword library with an uploaded file and re-run the semantic +
    expression layers: keyword_classify → review → copywriter → st_optimize →
    export. Lets a finished run be refreshed with new traffic words (e.g. as the
    competitive landscape shifts) without re-scraping competitors or re-analyzing
    product attributes. Refused while the run is already running.
    """
    from app.api._state import set_run_task

    graph = _get_graph()
    toolbox = _get_toolbox()
    config = {"configurable": {"thread_id": run_id}}
    content = await file.read()

    fname = (file.filename or "").lower()
    if fname.endswith(".xlsx"):
        cleaned = toolbox.keyword.clean(content)
    elif fname.endswith(".json"):
        try:
            cleaned = toolbox.keyword.clean(json.loads(content))
        except json.JSONDecodeError:
            raise HTTPException(400, "关键词词库 JSON 解析失败")
    else:
        raise HTTPException(400, "关键词词库请上传 .xlsx 或 .json 文件")

    if not cleaned:
        raise HTTPException(400, "关键词词库为空或无法解析")

    async with _run_state_lock(run_id):
        state = await graph.aget_state(config)
        if not state or not state.values:
            raise HTTPException(404, "Run not found")
        s = state.values
        if s.get("status") == "running":
            raise HTTPException(400, "任务正在运行中，请等待当前流程完成")
        if not (
            MemoryHelper.has(s, "approved_product_attributes")
            or MemoryHelper.has(s, "product_attributes_draft")
        ):
            raise HTTPException(400, "缺少产品属性表，无法重新分类")

        # Reposition as if attribute review just completed → the conditional edge
        # routes to keyword_classify (a keyword library now exists). Re-classify
        # with the new library, pause at the classification review, then
        # copywriter → st_optimize → export.
        await graph.aupdate_state(
            config,
            {
                "keyword_library": cleaned,
                "status": "running",
                "pending_action": {},
                "error": "",
            },
            as_node="human_review",
        )
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted", "keywords_count": len(cleaned)}


class SubmitCaptchaRequest(BaseModel):
    answer: str


@router.post("/runs/{run_id}/captcha")
async def submit_captcha(run_id: str, req: SubmitCaptchaRequest):
    """Feed a user-entered captcha/verification answer into the parked browser-act
    session, then resume the run (research re-enters and retries the reviews scrape)."""
    import logging

    from app.api._state import get_toolbox, set_run_task

    logger = logging.getLogger("eco_listing")

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    pending = state.values.get("pending_action") or {}
    if pending.get("type") != "solve_captcha":
        raise HTTPException(400, "当前任务未在等待人机验证")

    # Type the answer into the same live session that is parked on the challenge.
    try:
        toolbox = get_toolbox()
        if toolbox.browser is not None:
            await toolbox.browser.browser_act.submit_verification(req.answer)
    except Exception:
        logger.warning("submit_verification failed for run %s", run_id, exc_info=True)

    await graph.aupdate_state(config, {"status": "running", "pending_action": {}})
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted"}


class SubmitClassifiedReviewRequest(BaseModel):
    classified_keywords: dict
    # True  -> save + approve: persist and resume into copywriter.
    # False -> save only: persist edits but stay paused at the review gate.
    approve: bool = True


@router.put("/runs/{run_id}/classified-review")
async def submit_classified_review(run_id: str, req: SubmitClassifiedReviewRequest):
    """Save the human-reviewed keyword classification.

    On approve, also resume the graph so it proceeds to the copywriter; on a
    plain save, only persist the edits and keep the run paused at the
    keyword_classify_review interrupt so the user can keep editing.
    """
    from app.api._state import set_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}

    if not req.approve:
        await graph.aupdate_state(config, {"classified_keywords": req.classified_keywords})
        return {"status": "saved"}

    update = {
        "classified_keywords": req.classified_keywords,
        "status": "running",
        "pending_action": {},
    }
    await graph.aupdate_state(config, update)
    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "accepted"}


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause a running task by cancelling the asyncio task and setting status to paused."""
    from app.api._state import get_run_task, remove_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    current_status = state.values.get("status", "unknown")
    if current_status not in ("running",):
        raise HTTPException(400, f"无法暂停状态为 {current_status} 的任务")

    task = get_run_task(run_id)
    if task and not task.done():
        task.cancel()
    remove_run_task(run_id)

    await graph.aupdate_state(config, {"status": "paused"})
    return {"status": "paused"}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """Resume a paused or stale-running task."""
    from app.api._state import get_run_task, set_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    current_status = state.values.get("status", "unknown")
    existing_task = get_run_task(run_id)
    task_alive = existing_task is not None and not existing_task.done()

    # A run that stalled without competitor listings (parked at the upload gate,
    # or failed mid-cognitive-layer) can be retried: re-enter research, which now
    # scrapes only the still-missing buckets. We reposition as if the upload gate
    # just ran so research RE-RUNS — setting status without as_node would instead
    # make _after_research route straight to product_analyst (skipping the scrape).
    has_listings = MemoryHelper.has(state.values, "competitor_listings")
    retry_scrape = current_status in ("waiting_human", "failed") and not has_listings

    if current_status == "running" and task_alive:
        raise HTTPException(400, "任务正在执行中，无需恢复")

    if current_status not in ("paused", "running", "failed") and not retry_scrape:
        raise HTTPException(400, f"只能恢复暂停、中断或失败的任务，当前状态: {current_status}")

    if retry_scrape:
        await graph.aupdate_state(
            config,
            {"status": "running", "pending_action": {}, "error": ""},
            as_node="wait_upload",
        )
    else:
        await graph.aupdate_state(config, {"status": "running", "error": ""})

    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)
    return {"status": "running"}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str):
    """Stop a running or paused task permanently."""
    from app.api._state import get_run_task, remove_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    current_status = state.values.get("status", "unknown")
    if current_status in ("completed", "failed", "stopped"):
        raise HTTPException(400, f"任务已经是终态: {current_status}")

    task = get_run_task(run_id)
    if task and not task.done():
        task.cancel()
    remove_run_task(run_id)

    update_kwargs = {"as_node": "__start__"} if current_status == "pending" else {}
    await graph.aupdate_state(config, {"status": "stopped"}, **update_kwargs)
    return {"status": "stopped"}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """Stop (if running) and permanently delete a run.

    Purges the LangGraph checkpoint thread — the run's only persistence. Since
    the run list is derived from the checkpoint DB, deleting the thread removes
    the run from the list for good.
    """
    import logging

    from app.api._state import get_run_task, remove_run_task

    graph = _get_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise HTTPException(404, "Run not found")

    task = get_run_task(run_id)
    if task and not task.done():
        task.cancel()
    remove_run_task(run_id)

    try:
        await graph.checkpointer.adelete_thread(run_id)
    except Exception:
        logging.getLogger("eco_listing").warning(
            "Failed to purge checkpoint for deleted run %s", run_id, exc_info=True
        )

    return {"status": "deleted"}


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

    # Serialize state mutations for this run so parallel uploads can't clobber
    # each other's channels (lost-update race on the shared checkpoint).
    async with _run_state_lock(run_id):
        cur_state = await graph.aget_state(config)
        is_pending = cur_state and cur_state.values and cur_state.values.get("status") == "pending"
        update_kwargs = {"as_node": "__start__"} if is_pending else {}

        next_nodes = cur_state.next if cur_state and cur_state.next else ()
        is_waiting_keyword = "keyword_upload" in next_nodes

        # Ready-made 本品属性表 (product attribute table). When provided we seed it
        # as the analyst draft so the cognitive-layer LLM analysis is skipped
        # entirely (see research_node / orchestrator routing) and the uploaded
        # table is used as-is. Accepts excel/md/json; non-canonical content is
        # LLM-normalized into the internal schema so the review panel renders.
        if data_type == "product_attributes":
            from app.tools import attr_convert

            fname = (file.filename or "").lower()
            canonical: dict | None = None
            raw_text = ""

            if fname.endswith(".json"):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    raise HTTPException(400, "本品属性表 JSON 解析失败")
                if attr_convert.is_canonical(parsed):
                    canonical = parsed
                elif isinstance(parsed, (dict, list)) and parsed:
                    # Non-canonical JSON (e.g. Chinese-keyed): normalize via LLM.
                    raw_text = json.dumps(parsed, ensure_ascii=False, indent=2)
                else:
                    raise HTTPException(400, "本品属性表需为非空 JSON")
            elif fname.endswith(".xlsx"):
                try:
                    raw_text = attr_convert.xlsx_to_markdown(content)
                except Exception:
                    raise HTTPException(400, "本品属性表 Excel 解析失败")
                if not raw_text:
                    raise HTTPException(400, "本品属性表 Excel 为空")
            elif fname.endswith((".md", ".txt")):
                raw_text = content.decode("utf-8", errors="replace").strip()
                if not raw_text:
                    raise HTTPException(400, "本品属性表文件为空")
            else:
                raise HTTPException(400, "本品属性表支持 .json / .xlsx / .md / .txt 文件")

            if canonical is None:
                try:
                    canonical = await attr_convert.normalize_uploaded_attributes(
                        toolbox, raw_text
                    )
                except Exception as e:
                    raise HTTPException(400, f"本品属性表转换失败：{e}")

            if not isinstance(canonical, dict) or not canonical:
                raise HTTPException(400, "本品属性表需为非空对象")

            update = {"product_attributes_draft": canonical}
            if not is_pending:
                update.update({"status": "running", "pending_action": {}})
            await graph.aupdate_state(config, update, **update_kwargs)
            return {"status": "accepted", "product_attributes": True}

        if file.filename and file.filename.lower().endswith(".xlsx") and data_type in ("keywords", "auto"):
            cleaned = toolbox.keyword.clean(content)
            update: dict = {"keyword_library": cleaned}
            if not is_pending:
                update.update({"status": "running", "pending_action": {}})
            await graph.aupdate_state(config, update, **update_kwargs)
            if is_waiting_keyword:
                await _auto_resume_after_keyword(run_id)
            return {"status": "accepted", "keywords_count": len(cleaned)}

        if file.filename and file.filename.endswith(".json"):
            data = json.loads(content)

            if data_type == "keywords" or (
                data_type == "auto" and "keyword" in str(data)[:200]
            ):
                cleaned = toolbox.keyword.clean(data)
                update = {"keyword_library": cleaned}
                if not is_pending:
                    update.update({"status": "running", "pending_action": {}})
            elif data_type == "reviews":
                items = data if isinstance(data, list) else [data]
                existing_reviews = list(cur_state.values.get("customer_reviews", [])) if cur_state and cur_state.values else []
                existing_reviews.extend(items)
                update = {"customer_reviews": existing_reviews}
            elif data_type == "listings":
                items = data if isinstance(data, list) else [data]
                existing_listings = list(cur_state.values.get("competitor_listings", [])) if cur_state and cur_state.values else []
                existing_listings.extend(items)
                update = {"competitor_listings": existing_listings}
                if not is_pending:
                    update.update({"status": "running", "pending_action": {}})
            else:
                update = {"competitor_listings": data if isinstance(data, list) else [data]}
                if not is_pending:
                    update.update({"status": "running", "pending_action": {}})
            await graph.aupdate_state(config, update, **update_kwargs)
            if is_waiting_keyword and data_type in ("keywords", "auto") and "keyword_library" in update:
                await _auto_resume_after_keyword(run_id)

        elif file.filename and file.filename.lower().endswith((".md", ".txt")):
            text = content.decode("utf-8", errors="replace").strip()
            if data_type in ("reviews", "auto"):
                review_item = {"title": file.filename, "body": text, "rating": 0, "source": "uploaded_file"}
                existing_reviews = list(cur_state.values.get("customer_reviews", [])) if cur_state and cur_state.values else []
                existing_reviews.append(review_item)
                await graph.aupdate_state(config, {"customer_reviews": existing_reviews}, **update_kwargs)
                return {"status": "accepted", "review_count": len(existing_reviews)}
            elif data_type == "listings":
                listing_item = {"raw_text": text, "source": file.filename}
                existing_listings = list(cur_state.values.get("competitor_listings", [])) if cur_state and cur_state.values else []
                existing_listings.append(listing_item)
                update = {"competitor_listings": existing_listings}
                if not is_pending:
                    update.update({"status": "running", "pending_action": {}})
                await graph.aupdate_state(config, update, **update_kwargs)
                return {"status": "accepted", "listing_count": len(existing_listings)}
            else:
                raise HTTPException(400, "MD/TXT 文件请指定 data_type 为 reviews 或 listings")

        elif file.filename and file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            save_path = toolbox.file_store.run_dir(run_id) + f"/{file.filename}"
            with open(save_path, "wb") as f:
                f.write(content)
            existing_screenshots = (
                (cur_state.values.get("alex_screenshots") or cur_state.values.get("rufus_screenshots") or [])
                if cur_state and cur_state.values else []
            )
            existing_screenshots.append(save_path)
            await graph.aupdate_state(config, {"alex_screenshots": existing_screenshots}, **update_kwargs)
            return {"status": "accepted", "saved": save_path}
        else:
            raise HTTPException(400, "支持 .json / .xlsx / .md / .txt / .png / .jpg 文件")

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


# --- Image generation endpoints ---
#
# A standalone subsystem decoupled from the LangGraph pipeline: it only needs a
# run_id and (optional) reference images, and never touches the checkpoint state.
# Images are generated via the codex CLI built-in `image_gen` tool (ChatGPT
# OAuth, no API key) and persisted under artifacts/{run_id}/generated/.

# Strong references to in-flight generation tasks (the event loop only keeps a
# weak ref, so without this a fire-and-forget task can be GC'd mid-run).
_image_job_tasks: set[asyncio.Task] = set()


@router.post("/runs/{run_id}/images/generate")
async def generate_run_images(run_id: str, req: GenerateImagesRequest):
    """Kick off a generation job and return immediately.

    Generation takes 1-3 minutes, so it runs as a persisted background job; the
    client polls ``GET /images/jobs``. Validation happens synchronously here so
    bad input still gets a 400.
    """
    from app.tools.file_store import from_artifact_url
    from app.tools.image_jobs import create_job, run_job

    if not req.prompt or not req.prompt.strip():
        raise HTTPException(400, "生图提示词不能为空")

    ref_paths = [p for u in req.reference_urls if (p := from_artifact_url(u))]
    params = {
        "prompt": req.prompt.strip(),
        "n": req.n,
        "size": req.size,
        "quality": req.quality,
        "white_bg": req.white_bg,
        "reference_urls": req.reference_urls,
    }
    job = await create_job(run_id, params)
    # Fire-and-forget: the task persists its own outcome to the jobs sidecar.
    # Hold a strong reference so the loop doesn't GC the task mid-run.
    task = asyncio.create_task(run_job(run_id, job["id"], params, ref_paths))
    _image_job_tasks.add(task)
    task.add_done_callback(_image_job_tasks.discard)
    return {"job": job}


@router.get("/runs/{run_id}/images/jobs")
async def list_run_image_jobs(run_id: str):
    from app.tools.image_jobs import list_jobs

    return {"jobs": list_jobs(run_id)}


@router.post("/runs/{run_id}/images/upload-reference")
async def upload_reference_image(run_id: str, file: UploadFile = File(...)):
    """Save a user-uploaded reference image under the run's artifacts dir and
    return its ``/artifacts`` URL, so it can be selected as a generation reference."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "仅支持 png/jpg/jpeg/webp 图片")
    out_dir = os.path.join(settings.artifacts_dir, run_id, "ref_uploads")
    os.makedirs(out_dir, exist_ok=True)
    name = f"{int(datetime.datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"name": name, "url": f"/artifacts/{run_id}/ref_uploads/{name}"}


@router.get("/runs/{run_id}/images")
async def list_run_images(run_id: str):
    from app.tools.image_gen_tool import list_generated_images

    return {"images": list_generated_images(run_id)}


@router.get("/runs/{run_id}/images/export.zip")
async def export_run_images(run_id: str):
    import glob
    import io
    import zipfile

    out_dir = os.path.join(settings.artifacts_dir, run_id, "generated")
    files = sorted(glob.glob(os.path.join(out_dir, "*"))) if os.path.isdir(out_dir) else []
    files = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not files:
        raise HTTPException(404, "暂无可下载的生成图片")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=os.path.basename(f))
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{run_id}_images.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


@router.get("/runs/{run_id}/competitor-images")
async def list_competitor_images(run_id: str):
    """List competitor product images captured during the listing scrape, grouped
    by ASIN. They live under ``artifacts/{run_id}/competitor_images/{asin}/`` and
    are served via ``/artifacts``; the image studio offers them as references."""
    base = os.path.join(settings.artifacts_dir, run_id, "competitor_images")
    groups: list[dict] = []
    if os.path.isdir(base):
        for asin in sorted(os.listdir(base)):
            asin_dir = os.path.join(base, asin)
            if not os.path.isdir(asin_dir):
                continue
            images = [
                {"name": name, "url": f"/artifacts/{run_id}/competitor_images/{asin}/{name}"}
                for name in sorted(os.listdir(asin_dir))
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            ]
            if images:
                groups.append({"asin": asin, "images": images})
    return {"competitors": groups}


# --- LLM Settings Endpoints ---


class UpdateLlmSettingsRequest(BaseModel):
    provider: str = "codex-cli"
    base_url: str = ""
    model: str = ""
    # Optional: when omitted/empty on an existing key, the stored key is kept.
    api_key: Optional[str] = None


class TestLlmSettingsRequest(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = ""
    model: str = ""
    api_key: Optional[str] = None


@router.get("/settings/llm")
async def get_llm_settings():
    from app import llm_settings

    return llm_settings.public_view(llm_settings.get_listing_llm_config())


@router.put("/settings/llm")
async def update_llm_settings(req: UpdateLlmSettingsRequest):
    from app import llm_settings

    if req.provider not in llm_settings.VALID_PROVIDERS:
        raise HTTPException(400, f"不支持的 provider: {req.provider}")

    current = llm_settings.get_listing_llm_config()
    # Keep the existing API key when the client doesn't send a new one (the
    # GET response masks it, so the form normally submits an empty key).
    api_key = req.api_key if req.api_key else current.get("api_key", "")

    new_cfg = {
        "provider": req.provider,
        "base_url": (req.base_url or "").strip(),
        "model": (req.model or "").strip(),
        "api_key": api_key,
    }

    if req.provider == llm_settings.PROVIDER_OPENAI_COMPATIBLE:
        if not new_cfg["base_url"]:
            raise HTTPException(400, "OpenAI 兼容模式需要填写 Base URL")
        if not new_cfg["model"]:
            raise HTTPException(400, "OpenAI 兼容模式需要填写 Model")
        if not new_cfg["api_key"]:
            raise HTTPException(400, "OpenAI 兼容模式需要填写 API Key")

    saved = llm_settings.save_llm_settings(new_cfg)
    return llm_settings.public_view(saved)


# --- Unified App Settings (account + scrape params + engine) ---


class AccountUpdate(BaseModel):
    site: Optional[str] = None
    email: Optional[str] = None
    # Optional: when omitted/empty, the stored password is kept.
    password: Optional[str] = None
    # Optional stealth-browser exit region (e.g. "US"); empty = host IP.
    proxy_region: Optional[str] = None


class ScrapeUpdate(BaseModel):
    browser_headless: Optional[bool] = None
    scrape_max_review_pages: Optional[int] = None
    research_concurrency: Optional[int] = None
    codex_timeout: Optional[int] = None


class UpdateAppSettingsRequest(BaseModel):
    account: Optional[AccountUpdate] = None
    scrape: Optional[ScrapeUpdate] = None
    review_engine: Optional[str] = None


@router.get("/settings/app")
async def get_app_settings_route():
    from app import app_settings

    return app_settings.public_view()


@router.put("/settings/app")
async def update_app_settings_route(req: UpdateAppSettingsRequest):
    from app import app_settings

    if req.review_engine is not None and req.review_engine not in app_settings.VALID_ENGINES:
        raise HTTPException(400, f"不支持的抓取引擎: {req.review_engine}")

    current = app_settings.get_app_settings()

    if req.account is not None:
        if req.account.site is not None:
            current["account"]["site"] = req.account.site.strip() or "amazon.com"
        if req.account.email is not None:
            current["account"]["email"] = req.account.email.strip()
        # Keep existing password when the client sends nothing (GET masks it).
        if req.account.password:
            current["account"]["password"] = req.account.password
        if req.account.proxy_region is not None:
            current["account"]["proxy_region"] = req.account.proxy_region.strip()

    if req.scrape is not None:
        s = req.scrape
        if s.browser_headless is not None:
            current["scrape"]["browser_headless"] = s.browser_headless
        for field in ("scrape_max_review_pages", "research_concurrency", "codex_timeout"):
            val = getattr(s, field)
            if val is not None:
                if val <= 0:
                    raise HTTPException(400, f"{field} 必须为正整数")
                current["scrape"][field] = val

    if req.review_engine is not None:
        current["review_engine"] = req.review_engine

    saved = app_settings.save_app_settings(current)
    return app_settings.public_view(saved)


@router.post("/settings/llm/test")
async def test_llm_settings(req: TestLlmSettingsRequest):
    """Probe an OpenAI-compatible endpoint with a tiny request (no persistence)."""
    from app import llm_settings
    from app.tools import openai_compatible

    if req.provider != llm_settings.PROVIDER_OPENAI_COMPATIBLE:
        return {"ok": True, "message": "codex-cli 无需测试连接"}

    # Fall back to the stored key so the user can test without re-entering it.
    api_key = req.api_key or llm_settings.get_listing_llm_config().get("api_key", "")

    candidate = {
        "provider": llm_settings.PROVIDER_OPENAI_COMPATIBLE,
        "base_url": (req.base_url or "").strip(),
        "model": (req.model or "").strip(),
        "api_key": api_key or "",
    }
    if not llm_settings.is_configured(candidate):
        return {"ok": False, "message": "请先填写完整的 Base URL、Model 和 API Key"}

    ok, message = await openai_compatible.probe(candidate)
    return {"ok": ok, "message": message}


# --- Account Login Session Endpoints ---


class AccountCaptchaRequest(BaseModel):
    answer: str


@router.get("/account/status")
async def account_status(probe: bool = False):
    from app import account_session

    if probe:
        return await account_session.refresh_status()
    return account_session.get_status()


@router.post("/account/login")
async def account_login():
    from app import account_session

    return await account_session.start_login()


@router.post("/account/confirm")
async def account_confirm():
    """User finished signing in manually — re-check the live Chrome session."""
    from app import account_session

    return await account_session.confirm_login()


@router.post("/account/captcha")
async def account_captcha(req: AccountCaptchaRequest):
    from app import account_session

    return await account_session.submit_captcha(req.answer)


@router.post("/account/logout")
async def account_logout():
    from app import account_session

    return await account_session.logout()


# --- Prompt Management Endpoints ---


@router.get("/prompts")
async def list_prompts():
    """List only the active version of each prompt template."""
    results = []
    if not os.path.isdir(PROMPTS_DIR):
        return results

    for agent_dir in sorted(os.listdir(PROMPTS_DIR)):
        agent_path = os.path.join(PROMPTS_DIR, agent_dir)
        if not os.path.isdir(agent_path):
            continue

        meta_path = os.path.join(agent_path, "meta.json")
        active_versions: dict[str, str] = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            for tpl_name, tpl_cfg in meta.get("templates", {}).items():
                version = tpl_cfg.get("active", "v1")
                active_versions[tpl_name] = version

        for filename in sorted(os.listdir(agent_path)):
            if not filename.endswith(".md"):
                continue
            name = filename.removesuffix(".md")
            tpl_name = _strip_version(name)
            if tpl_name in active_versions:
                expected = f"{tpl_name}_{active_versions[tpl_name]}"
                if name != expected:
                    continue

            override_path = os.path.join(agent_path, f".override_{filename}")
            results.append({
                "agent": agent_dir,
                "name": name,
                "filename": filename,
                "modified": os.path.exists(override_path),
            })
    return results


def _strip_version(name: str) -> str:
    """Remove trailing _v1, _v2 etc. from a template name."""
    m = re.match(r"^(.+)_v\d+$", name)
    return m.group(1) if m else name


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


async def _auto_resume_after_keyword(run_id: str):
    """Resume the graph after a keyword upload.

    With the keyword review gate removed, the run proceeds through
    keyword_classify and pauses at the keyword_classify_review interrupt.
    """
    from app.api._state import set_run_task

    task = asyncio.create_task(_resume_graph(run_id))
    set_run_task(run_id, task)


async def _run_graph(thread_id: str, initial_state: dict):
    token = codex_progress.current_run_id.set(thread_id)
    try:
        graph = _get_graph()
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await graph.ainvoke(initial_state, config)
        except Exception as e:
            await _mark_graph_error(graph, config, e)
    finally:
        codex_progress.current_run_id.reset(token)


async def _run_graph_from_state(thread_id: str):
    """Start graph execution from a pre-populated state (pending → running)."""
    token = codex_progress.current_run_id.set(thread_id)
    try:
        graph = _get_graph()
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = await graph.aget_state(config)
            initial = dict(state.values) if state and state.values else {}
            initial["status"] = "running"
            await graph.ainvoke(initial, config)
        except Exception as e:
            await _mark_graph_error(graph, config, e)
    finally:
        codex_progress.current_run_id.reset(token)


async def _resume_graph(thread_id: str):
    token = codex_progress.current_run_id.set(thread_id)
    try:
        graph = _get_graph()
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await graph.ainvoke(None, config)
        except Exception as e:
            await _mark_graph_error(graph, config, e)
    finally:
        codex_progress.current_run_id.reset(token)


async def _mark_graph_error(graph, config, exc: Exception):
    """Persist error info into graph state so the frontend can display it."""
    import logging
    import traceback

    logger = logging.getLogger("eco_listing")
    logger.error("Graph execution error: %s", exc, exc_info=True)

    error_msg = f"{type(exc).__name__}: {exc}"
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    short_tb = "".join(tb[-3:]) if len(tb) > 3 else "".join(tb)

    try:
        await graph.aupdate_state(config, {
            "status": "failed",
            "error": error_msg,
            "agent_log": [MemoryHelper.log_action(
                "orchestrator", "error",
                error=error_msg,
                traceback=short_tb,
            )],
        })
    except Exception:
        logger.error("Failed to persist error state", exc_info=True)
