"""Research Agent: automated competitor data collection via browser scraping."""

from __future__ import annotations

import os
import time

from app.agents.base import ToolBox
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


async def research_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: scrape competitor listings, reviews, and Rufus Q&A.

    Execution flow:
      1. If competitor_listings already provided (file upload), skip scraping.
      2. Otherwise, use BrowserTool to scrape each competitor ASIN.
      3. Scrape Rufus Q&A via Codex CLI (requires interaction).
      4. Scrape customer reviews for sentiment analysis.
      5. Fall back to manual upload if BrowserTool is unavailable.
    """
    logs = []
    t0 = time.time()

    product_asin = state.get("product_asin", "")
    site = state.get("site", "amazon.com")
    competitor_asins = state.get("competitor_asins", [])

    # --- Phase 1: Competitor Listings ---
    listings = list(state.get("competitor_listings", []))

    if not listings and competitor_asins and toolbox.browser:
        for asin in competitor_asins:
            t1 = time.time()
            result = await toolbox.browser.scrape_listing(asin, site)
            listings.append(result)
            logs.append(
                MemoryHelper.log_action(
                    "research",
                    "scrape_listing",
                    asin=asin,
                    has_error="error" in result,
                    duration_ms=int((time.time() - t1) * 1000),
                )
            )

    if not listings:
        return {
            "status": "waiting_human",
            "pending_action": {
                "type": "upload_competitor_data",
                "message": "无法自动抓取竞品数据，请手动上传竞品 Listing 文件",
            },
            "agent_log": [MemoryHelper.log_action("research", "waiting_upload")],
        }

    # --- Phase 2: Rufus Q&A ---
    rufus_qs = list(state.get("rufus_questions", []))

    if not rufus_qs and product_asin and toolbox.browser:
        t1 = time.time()
        rufus_result = await toolbox.browser.scrape_rufus(product_asin, site)
        rufus_qs = rufus_result.get("qa_pairs", [])
        logs.append(
            MemoryHelper.log_action(
                "research",
                "scrape_rufus",
                qa_count=len(rufus_qs),
                has_error="error" in rufus_result,
                duration_ms=int((time.time() - t1) * 1000),
            )
        )

    # Also try Rufus screenshots (legacy path / manual fallback)
    screenshots = state.get("rufus_screenshots", [])
    for img_path in screenshots:
        if os.path.exists(img_path):
            t1 = time.time()
            prompt = toolbox.prompts.render(
                "research",
                "rufus_extract",
                {"screenshot_count": str(len(screenshots))},
            )
            result = await toolbox.llm.call(
                "gemini-pro", prompt, attachments=[img_path]
            )
            rufus_qs.extend(result.get("questions", []))
            logs.append(
                MemoryHelper.log_action(
                    "research",
                    "extract_rufus_screenshot",
                    duration_ms=int((time.time() - t1) * 1000),
                )
            )

    # --- Phase 3: Customer Reviews ---
    reviews = list(state.get("customer_reviews", []))

    if not reviews and toolbox.browser:
        asins_to_review = [product_asin] + competitor_asins[:2] if product_asin else competitor_asins[:3]
        for asin in asins_to_review:
            if not asin:
                continue
            t1 = time.time()
            asin_reviews = await toolbox.browser.scrape_reviews(asin, site)
            reviews.extend(asin_reviews)
            logs.append(
                MemoryHelper.log_action(
                    "research",
                    "scrape_reviews",
                    asin=asin,
                    review_count=len(asin_reviews),
                    duration_ms=int((time.time() - t1) * 1000),
                )
            )

    logs.insert(
        0,
        MemoryHelper.log_action(
            "research",
            "research_complete",
            listing_count=len(listings),
            rufus_count=len(rufus_qs),
            review_count=len(reviews),
            total_duration_ms=int((time.time() - t0) * 1000),
        ),
    )

    return {
        "competitor_listings": listings,
        "rufus_questions": rufus_qs,
        "customer_reviews": reviews,
        "status": "running",
        "agent_log": logs,
    }
