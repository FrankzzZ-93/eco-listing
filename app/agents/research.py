"""Research Agent: automated competitor data collection via browser scraping."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Awaitable, Callable

from app.agents.base import ToolBox
from app.config import settings
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper
from app.tools import codex_progress


async def _scrape_all(
    run_id: str,
    phase: str,
    asins: list[str],
    scrape_one: Callable[[str], Awaitable],
    concurrency: int,
) -> list:
    """Scrape a set of ASINs with bounded concurrency, reporting x/y progress.

    Returns an ordered list of ``(asin, result, duration_ms)`` matching the
    input ``asins`` order so callers can build deterministic logs. Progress is
    pushed to ``codex_progress`` after each scrape completes.
    """
    total = len(asins)
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    codex_progress.set_scrape(run_id, phase, 0, total)
    results: list = [None] * total

    async def worker(i: int, asin: str) -> None:
        nonlocal done
        async with sem:
            t1 = time.time()
            res = await scrape_one(asin)
            dur = int((time.time() - t1) * 1000)
        # Single event loop → plain increment is safe (no preemption mid-stmt).
        done += 1
        codex_progress.set_scrape(run_id, phase, done, total)
        results[i] = (asin, res, dur)

    await asyncio.gather(*(worker(i, a) for i, a in enumerate(asins)))
    return results


async def research_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: scrape competitor listings, reviews, and Alex Q&A.

    Execution flow:
      1. If a 本品属性表 was uploaded, skip the whole cognitive layer.
      2. Otherwise scrape each competitor ASIN with bounded concurrency.
      3. Scrape Alex Q&A and customer reviews per competitor.
      4. Summarize reviews into review_summary for the analyst.
      5. Fall back to manual upload if BrowserTool is unavailable.
    """
    logs = []
    t0 = time.time()
    run_id = state.get("run_id", "")
    concurrency = settings.research_concurrency

    try:
        # If a ready-made 本品属性表 was uploaded, skip the entire cognitive layer
        # (competitor scraping + info fusion) and use the uploaded table directly.
        if MemoryHelper.has(state, "product_attributes_draft"):
            return {
                "status": "running",
                "agent_log": [
                    MemoryHelper.log_action(
                        "research",
                        "skip_uploaded_attributes",
                        reason="本品属性表已上传，跳过认知层分析",
                    )
                ],
            }

        site = state.get("site", "amazon.com")
        competitor_asins = state.get("competitor_asins", [])

        # --- Phase 1: Competitor Listings ---
        listings = list(state.get("competitor_listings", []))

        if not listings and competitor_asins and toolbox.browser:
            scraped = await _scrape_all(
                run_id,
                "competitor_listings",
                competitor_asins,
                lambda a: toolbox.browser.scrape_listing(a, site),
                concurrency,
            )
            for asin, result, dur in scraped:
                listings.append(result)
                logs.append(
                    MemoryHelper.log_action(
                        "research",
                        "scrape_listing",
                        asin=asin,
                        has_error="error" in result,
                        duration_ms=dur,
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

        # --- Phase 2: Alex Q&A (from each competitor) ---
        # Read alex_*; fall back to legacy rufus_* keys for older runs.
        alex_qs = list(state.get("alex_questions") or state.get("rufus_questions") or [])

        if not alex_qs and competitor_asins and toolbox.browser:
            scraped = await _scrape_all(
                run_id,
                "alex",
                competitor_asins,
                lambda a: toolbox.browser.scrape_alex(a, site),
                concurrency,
            )
            for asin, alex_result, dur in scraped:
                qa = alex_result.get("qa_pairs", [])
                alex_qs.extend(qa)
                logs.append(
                    MemoryHelper.log_action(
                        "research",
                        "scrape_alex",
                        asin=asin,
                        qa_count=len(qa),
                        has_error="error" in alex_result,
                        duration_ms=dur,
                    )
                )

        # Also try Alex screenshots (legacy path / manual fallback)
        screenshots = state.get("alex_screenshots") or state.get("rufus_screenshots") or []
        for img_path in screenshots:
            if os.path.exists(img_path):
                t1 = time.time()
                prompt = toolbox.prompts.render(
                    "research",
                    "alex_extract",
                    {"screenshot_count": str(len(screenshots))},
                )
                result = await toolbox.llm.call(
                    "gemini-pro", prompt, attachments=[img_path]
                )
                alex_qs.extend(result.get("questions", []))
                logs.append(
                    MemoryHelper.log_action(
                        "research",
                        "extract_alex_screenshot",
                        duration_ms=int((time.time() - t1) * 1000),
                    )
                )

        # --- Phase 3: Customer Reviews (from each competitor) ---
        reviews = list(state.get("customer_reviews", []))

        if not reviews and competitor_asins and toolbox.browser:
            scraped = await _scrape_all(
                run_id,
                "reviews",
                competitor_asins,
                lambda a: toolbox.browser.scrape_reviews(a, site),
                concurrency,
            )
            for asin, asin_reviews, dur in scraped:
                reviews.extend(asin_reviews)
                logs.append(
                    MemoryHelper.log_action(
                        "research",
                        "scrape_reviews",
                        asin=asin,
                        review_count=len(asin_reviews),
                        duration_ms=dur,
                    )
                )

        # --- Phase 4: Review summarization ---
        # product_analyst consumes `review_summary` (not the raw list), so distill
        # the collected reviews here. Covers both auto-scraped and manually
        # uploaded reviews; skip if already summarized or if there are no reviews.
        review_summary = state.get("review_summary") or {}
        if reviews and not review_summary:
            t1 = time.time()
            summary_prompt = toolbox.prompts.render(
                "research",
                "review_summary",
                {"customer_reviews": json.dumps(reviews, ensure_ascii=False)},
            )
            review_summary = await toolbox.llm.call("gemini-pro", summary_prompt)
            logs.append(
                MemoryHelper.log_action(
                    "research",
                    "summarize_reviews",
                    review_count=len(reviews),
                    duration_ms=int((time.time() - t1) * 1000),
                )
            )

        logs.insert(
            0,
            MemoryHelper.log_action(
                "research",
                "research_complete",
                listing_count=len(listings),
                alex_count=len(alex_qs),
                review_count=len(reviews),
                total_duration_ms=int((time.time() - t0) * 1000),
            ),
        )

        return {
            "competitor_listings": listings,
            "alex_questions": alex_qs,
            "customer_reviews": reviews,
            "review_summary": review_summary,
            "status": "running",
            "agent_log": logs,
        }
    finally:
        codex_progress.clear_scrape(run_id)
