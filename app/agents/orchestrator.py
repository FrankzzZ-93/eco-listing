from langgraph.graph import END, StateGraph

from app.agents.base import ToolBox
from app.agents.copywriter import copywriter_node
from app.agents.keyword_strategist import keyword_classify_node, st_optimize_node
from app.agents.product_analyst import product_analyst_node
from app.agents.research import research_node
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


def _bind(fn, toolbox):
    """Create an async wrapper that passes toolbox to a node function."""
    async def _node(state):
        return await fn(state, toolbox)
    _node.__name__ = fn.__name__
    return _node


def build_graph(toolbox: ToolBox) -> StateGraph:
    graph = StateGraph(ListingState)

    graph.add_node("research", _bind(research_node, toolbox))
    graph.add_node("wait_upload", _passthrough)
    graph.add_node("product_analyst", _bind(product_analyst_node, toolbox))
    graph.add_node("human_review", _human_review_passthrough)
    graph.add_node("keyword_upload", _passthrough)
    graph.add_node("keyword_review", _passthrough)
    graph.add_node("keyword_classify", _bind(keyword_classify_node, toolbox))
    graph.add_node("copywriter", _bind(copywriter_node, toolbox))
    graph.add_node("st_optimize", _bind(st_optimize_node, toolbox))
    graph.add_node("export", _bind(_export_node, toolbox))

    graph.set_entry_point("research")

    graph.add_conditional_edges(
        "research",
        _after_research,
        {
            "product_analyst": "product_analyst",
            "wait_upload": "wait_upload",
            "human_review": "human_review",
        },
    )

    graph.add_edge("wait_upload", "research")

    graph.add_conditional_edges(
        "product_analyst",
        _after_analyst,
        {"human_review": "human_review", "keyword_classify": "keyword_classify"},
    )

    graph.add_conditional_edges(
        "human_review",
        _after_human_review,
        {"wait_keyword": "keyword_upload", "keyword_review": "keyword_review"},
    )

    graph.add_edge("keyword_upload", "keyword_review")
    graph.add_edge("keyword_review", "keyword_classify")
    graph.add_edge("keyword_classify", "copywriter")
    graph.add_edge("copywriter", "st_optimize")
    graph.add_edge("st_optimize", "export")
    graph.add_edge("export", END)

    return graph


# --- Routing functions ---


def _after_analyst(state: ListingState) -> str:
    """Always route to human review after attribute generation."""
    return "human_review"


def _after_human_review(state: ListingState) -> str:
    """After human review, check if keyword library is available."""
    if MemoryHelper.has(state, "keyword_library"):
        return "keyword_review"
    return "wait_keyword"


def _after_research(state: ListingState) -> str:
    """After research, decide whether to run cognitive-layer analysis.

    If the user uploaded a ready-made product attribute table, the draft is
    already populated before the analyst runs — skip `product_analyst` (the
    competitor info-fusion LLM step) and go straight to human review of the
    uploaded table. Otherwise fall back to the normal scrape/analyze path.
    """
    if state.get("status") == "waiting_human":
        return "wait_upload"
    if MemoryHelper.has(state, "product_attributes_draft"):
        return "human_review"
    return "product_analyst"


# --- Passthrough nodes ---


def _passthrough(state: ListingState) -> dict:
    """No-op node used as interrupt point."""
    return {}


def _human_review_passthrough(state: ListingState) -> dict:
    """Resume point after the product-attributes interrupt.

    Normally `submit_review` writes `approved_product_attributes` before
    resuming, but the UI also lets the user fast-forward by uploading the
    keyword library directly (`_auto_resume_after_keyword`), which skips
    the explicit approval step. In that case treat the AI-generated draft
    as implicitly approved so downstream nodes always have a populated
    field — and so the memory snapshot reflects what the run will use.
    """
    if MemoryHelper.has(state, "approved_product_attributes"):
        return {}
    draft = state.get("product_attributes_draft") or {}
    if not draft:
        return {}
    return {
        "approved_product_attributes": draft,
        "agent_log": [MemoryHelper.log_action(
            "orchestrator",
            "auto_approve_attributes",
            reason="user skipped explicit review",
        )],
    }


async def _export_node(state: ListingState, toolbox: ToolBox) -> dict:
    """Generate final deliverable files."""
    paths = toolbox.file_store.export_final(
        state["run_id"],
        state["final_listing"],
        state["final_st"],
    )
    return {
        "status": "completed",
        "agent_log": [MemoryHelper.log_action("orchestrator", "export", files=paths)],
    }


# --- Build compiled runnable ---


def create_app_graph(toolbox: ToolBox, checkpointer):
    graph = build_graph(toolbox)
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["wait_upload", "human_review", "keyword_upload", "keyword_review"],
    )
    return compiled
