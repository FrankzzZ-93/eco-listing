from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ListingState(TypedDict):
    # --- 输入 ---
    run_id: str
    # Task flavour. "" (default) = the full Listing pipeline. "image_studio" =
    # a standalone image-generation workspace: it owns a run_id (so its images
    # land under artifacts/{run_id}/ and it shows up in the run list) but never
    # enters the graph, so none of the pipeline fields below apply to it.
    kind: str
    site: str
    competitor_asins: list[str]
    # User-facing label shown in the run list. Persisted in the checkpoint so the
    # run list can be derived entirely from checkpoints.db (no separate registry).
    product_name: str
    # Brand / trademark entered at create time; first word of the listing title.
    brand_name: str

    # --- Phase 1: 认知层 ---
    competitor_listings: list[dict]
    customer_reviews: list[dict]
    review_summary: dict
    alex_questions: list[str]
    alex_screenshots: list[str]
    product_attributes_draft: dict
    product_attributes_confidence: float
    product_attributes_notes: str
    approved_product_attributes: dict

    # --- Phase 2: 语义层 ---
    keyword_library: list[dict]
    classified_keywords: dict

    # --- Phase 3: 表达层 ---
    draft_listing_v1: dict
    st_v1: list[str]
    draft_listing_v2: dict
    st_v2: list[str]
    final_listing: dict
    st_v3: list[str]
    final_st: list[str]
    word_frequency_report: dict

    # --- 控制 ---
    status: str  # running | waiting_human | completed | failed
    pending_action: dict
    agent_log: Annotated[list, operator.add]
    error: str
    # Length limits (title / Item Highlights / bullet / description chars, ST
    # bytes). Seeded at create time; the copywriter re-reads the live settings
    # and writes back the limits it enforced.
    length_limits: dict
