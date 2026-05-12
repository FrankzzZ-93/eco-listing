from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ListingState(TypedDict):
    # --- 输入 ---
    run_id: str
    product_asin: str
    site: str
    competitor_asins: list[str]

    # --- Phase 1: 认知层 ---
    competitor_listings: list[dict]
    customer_reviews: list[dict]
    review_summary: dict
    rufus_questions: list[str]
    rufus_screenshots: list[str]
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
