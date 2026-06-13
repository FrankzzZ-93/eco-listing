import json
import time

from app.agents.base import ToolBox
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


# Top-level keys in the classify output that are not keyword buckets.
_CLASSIFY_META_KEYS = frozenset({"semantic_map", "summary"})
# Source-library fields surfaced as reference columns during review.
_SOURCE_FIELDS = ("translation", "bid_price", "conversion_rate", "search_volume", "competition")


def _backfill_source_fields(classified: dict, keyword_library: list) -> None:
    """Merge source-library reference fields into each classified entry in-place.

    The LLM only emits keyword/rationale/usage (and sometimes a metric), so we
    re-attach translation / CPC / conversion-rate / search-volume from the
    original keyword library (matched on lowercased keyword text). These are
    review-time reference columns; the source library is authoritative.
    """
    if not isinstance(classified, dict):
        return
    lookup: dict[str, dict] = {}
    for item in keyword_library or []:
        if isinstance(item, dict):
            kw = str(item.get("keyword", "")).strip().lower()
            if kw:
                lookup[kw] = item

    for cat, entries in classified.items():
        if cat in _CLASSIFY_META_KEYS or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            src = lookup.get(str(entry.get("keyword", "")).strip().lower())
            if not src:
                continue
            for field in _SOURCE_FIELDS:
                src_val = src.get(field)
                if src_val in (None, ""):
                    continue
                # Source library is authoritative for reference metrics; overwrite
                # any value the LLM may have echoed/drifted (keyword/rationale/
                # usage are NOT in _SOURCE_FIELDS, so they are never touched).
                entry[field] = src_val


async def keyword_classify_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: classify keywords into semantic categories using LLM."""
    t0 = time.time()
    # Defensive fallback: if the user fast-forwarded past human_review without
    # an explicit approval, the orchestrator now copies the draft into
    # `approved_product_attributes`. This `or` keeps us working on any
    # historical run/state that escaped that fix.
    attrs = (
        state.get("approved_product_attributes")
        or state.get("product_attributes_draft")
        or {}
    )
    prompt = toolbox.prompts.render(
        "keyword_strategist",
        "classify",
        {
            "product_attributes": json.dumps(attrs, ensure_ascii=False),
            "keywords": json.dumps(state["keyword_library"], ensure_ascii=False),
        },
    )

    classified = await toolbox.llm.call("claude-sonnet", prompt)

    for category, words in classified.items():
        if isinstance(words, list) and len(words) < 3:
            prompt_retry = (
                prompt
                + f"\n\n注意：「{category}」分类下词太少（{len(words)}个），请补充。"
            )
            classified = await toolbox.llm.call("claude-sonnet", prompt_retry)
            break

    _backfill_source_fields(classified, state.get("keyword_library", []))

    return {
        "classified_keywords": classified,
        "agent_log": [
            MemoryHelper.log_action(
                "keyword_strategist",
                "classify",
                duration_ms=int((time.time() - t0) * 1000),
            )
        ],
    }


async def st_optimize_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: deterministic ST optimization algorithm."""
    t0 = time.time()
    result = toolbox.keyword.optimize_st(
        listing=state["final_listing"],
        st_v3=state.get("st_v3", []),
        classified_keywords=state.get("classified_keywords", {}),
    )

    toolbox.file_store.write_json(state["run_id"], "final_st.json", result)

    return {
        "final_st": result["final_st"],
        "word_frequency_report": result["word_frequency_report"],
        "agent_log": [
            MemoryHelper.log_action(
                "keyword_strategist",
                "optimize_st",
                duration_ms=int((time.time() - t0) * 1000),
            )
        ],
    }
