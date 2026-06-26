from __future__ import annotations

import asyncio
import json
import time

from app.agents.base import ToolBox
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


# Top-level keys in the classify output that are not keyword buckets.
_CLASSIFY_META_KEYS = frozenset({"semantic_map", "summary"})
# Keyword buckets the classifier emits.
_CLASSIFY_BUCKETS = ("A", "B", "C", "D")
# The LLM reliably classifies a tractable chunk but silently drops most entries
# when handed a large library in one shot (e.g. 883 keywords -> ~141 returned).
# So classify in bounded-concurrency batches and merge.
_CLASSIFY_BATCH_SIZE = 100
_CLASSIFY_CONCURRENCY = 3
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


def _kw_key(item: dict) -> str:
    return str(item.get("keyword", "")).strip().lower()


async def _classify_batches(toolbox: ToolBox, attrs_json: str, keywords: list[dict]) -> tuple[dict, dict | None]:
    """Classify ``keywords`` in bounded-concurrency batches and merge the buckets.

    Returns ``(merged, semantic_map)`` where ``merged`` maps each bucket
    (A/B/C/D) to its list of classified entries. A batch that fails or returns
    a non-dict is skipped (its keywords are caught by the caller's completeness
    pass), so one bad batch can't abort the whole classification.
    """
    chunks = [
        keywords[i : i + _CLASSIFY_BATCH_SIZE]
        for i in range(0, len(keywords), _CLASSIFY_BATCH_SIZE)
    ]
    sem = asyncio.Semaphore(_CLASSIFY_CONCURRENCY)

    async def _one(chunk: list[dict]) -> dict:
        prompt = toolbox.prompts.render(
            "keyword_strategist",
            "classify",
            {
                "product_attributes": attrs_json,
                "keywords": json.dumps(chunk, ensure_ascii=False),
            },
        )
        async with sem:
            try:
                res = await toolbox.llm.call("claude-sonnet", prompt)
            except Exception:
                return {}
        return res if isinstance(res, dict) else {}

    results = await asyncio.gather(*(_one(c) for c in chunks))

    merged: dict = {b: [] for b in _CLASSIFY_BUCKETS}
    semantic_map: dict | None = None
    for res in results:
        if semantic_map is None and isinstance(res.get("semantic_map"), dict):
            semantic_map = res["semantic_map"]
        for b in _CLASSIFY_BUCKETS:
            arr = res.get(b)
            if isinstance(arr, list):
                merged[b].extend(it for it in arr if isinstance(it, dict) and it.get("keyword"))
    return merged, semantic_map


async def keyword_classify_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: classify the keyword library into A/B/C/D via the LLM.

    Classifies in batches (the model drops most entries when handed a large
    library at once) and guarantees completeness: any keyword the model skips is
    re-classified once, and anything still missing is parked in D for manual
    review — so the classified set never silently loses keywords.
    """
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
    attrs_json = json.dumps(attrs, ensure_ascii=False)
    library = state.get("keyword_library", []) or []

    merged, semantic_map = await _classify_batches(toolbox, attrs_json, library)

    # Completeness pass 1: re-classify any keyword the model skipped.
    done = {_kw_key(it) for b in _CLASSIFY_BUCKETS for it in merged[b]}
    missing = [k for k in library if _kw_key(k) not in done]
    refilled = 0
    if missing:
        fill, _ = await _classify_batches(toolbox, attrs_json, missing)
        for b in _CLASSIFY_BUCKETS:
            merged[b].extend(fill[b])
        refilled = sum(len(fill[b]) for b in _CLASSIFY_BUCKETS)

    # Completeness pass 2: park anything still missing in D (visible + editable),
    # so no uploaded keyword is silently dropped.
    done = {_kw_key(it) for b in _CLASSIFY_BUCKETS for it in merged[b]}
    uncategorized = [k for k in library if _kw_key(k) not in done]
    for k in uncategorized:
        merged["D"].append({
            "keyword": k.get("keyword", ""),
            "search_volume": k.get("search_volume", 0),
            "rationale": "自动分类未覆盖，已暂归 D 类，请人工复核",
            "exclusion_type": "uncategorized",
        })

    classified: dict = {b: merged[b] for b in _CLASSIFY_BUCKETS}
    if semantic_map:
        classified["semantic_map"] = semantic_map
    classified["summary"] = {
        "total": sum(len(merged[b]) for b in _CLASSIFY_BUCKETS),
        **{f"{b}_count": len(merged[b]) for b in _CLASSIFY_BUCKETS},
    }

    _backfill_source_fields(classified, library)

    return {
        "classified_keywords": classified,
        "agent_log": [
            MemoryHelper.log_action(
                "keyword_strategist",
                "classify",
                library_count=len(library),
                classified_count=classified["summary"]["total"],
                batches=(len(library) + _CLASSIFY_BATCH_SIZE - 1) // _CLASSIFY_BATCH_SIZE,
                refilled=refilled,
                uncategorized=len(uncategorized),
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
