"""Research Agent: automated competitor data collection via browser scraping."""

from __future__ import annotations

import asyncio
import json
import os
import time

from app import app_settings
from app.agents.base import ToolBox
from app.config import settings
from app.errors import CaptchaRequiredError
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper
from app.tools import codex_progress
from app.tools.file_store import to_artifact_url


async def _scrape_asin(
    run_id: str,
    asin: str,
    site: str,
    browser,
    max_review_pages: int,
    *,
    do_listing: bool,
    do_alex: bool,
    do_reviews: bool,
) -> dict:
    """Scrape the requested data types for a single ASIN in sequence.

    Only the buckets requested via ``do_*`` are scraped — so a run that already
    has e.g. user-uploaded reviews still scrapes the missing listing/Alex. The
    returned dict only contains keys for the buckets that were scraped (plus
    their ``*_ms`` durations). Raises ``CaptchaRequiredError`` if a challenge is
    hit so the caller can pause and surface it to the UI.
    """
    result: dict = {}

    if do_listing:
        t1 = time.time()
        result["listing"] = await browser.scrape_listing(asin, site, run_id=run_id)
        result["listing_ms"] = int((time.time() - t1) * 1000)

    if do_alex:
        t1 = time.time()
        result["alex"] = await browser.scrape_alex(asin, site, run_id=run_id)
        result["alex_ms"] = int((time.time() - t1) * 1000)

    if do_reviews:
        t1 = time.time()
        result["reviews"] = await browser.scrape_reviews(
            asin, site, max_pages=max_review_pages, run_id=run_id
        )
        result["reviews_ms"] = int((time.time() - t1) * 1000)

    return result


async def _scrape_all_per_asin(
    run_id: str,
    asins: list[str],
    site: str,
    browser,
    max_review_pages: int,
    concurrency: int,
    *,
    do_listing: bool,
    do_alex: bool,
    do_reviews: bool,
) -> list:
    """Scrape the missing data types per ASIN with bounded concurrency.

    Each worker handles one ASIN end-to-end before the next ASIN starts within
    that slot, so data is collected in ASIN units rather than phase sweeps. Only
    the buckets flagged via ``do_*`` are scraped (the others were already
    collected/uploaded). Progress counter ticks once per completed ASIN.

    Returns an ordered list of ``(asin, result_dict)`` preserving input order.
    Raises ``CaptchaRequiredError`` from the first ASIN that hits a captcha.
    """
    total = len(asins)
    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    codex_progress.set_scrape(run_id, "per_asin", 0, total)
    results: list = [None] * total

    async def worker(i: int, asin: str) -> None:
        nonlocal done
        async with sem:
            res = await _scrape_asin(
                run_id, asin, site, browser, max_review_pages,
                do_listing=do_listing, do_alex=do_alex, do_reviews=do_reviews,
            )
        done += 1
        codex_progress.set_scrape(run_id, "per_asin", done, total)
        results[i] = (asin, res)

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
    concurrency = app_settings.get_scrape_param("research_concurrency", settings.research_concurrency)
    max_review_pages = app_settings.get_scrape_param(
        "scrape_max_review_pages", settings.scrape_max_review_pages
    )

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

        # Restore any data already collected in a previous (interrupted) run.
        listings = list(state.get("competitor_listings", []))
        alex_qs = list(state.get("alex_questions") or state.get("rufus_questions") or [])
        reviews = list(state.get("customer_reviews", []))

        # --- Per-ASIN scrape: only the buckets that are still missing ---
        # Each worker handles one ASIN end-to-end before moving to the next. We
        # scrape per-bucket (not all-or-nothing): if the user uploaded only
        # reviews, we still scrape the missing listing + Alex. A bucket that
        # already has data is left untouched, so this stays idempotent on resume.
        need_listings = not listings
        need_alex = not alex_qs
        need_reviews = not reviews
        if competitor_asins and toolbox.browser and (need_listings or need_alex or need_reviews):
            try:
                scraped = await _scrape_all_per_asin(
                    run_id,
                    competitor_asins,
                    site,
                    toolbox.browser,
                    max_review_pages,
                    concurrency,
                    do_listing=need_listings,
                    do_alex=need_alex,
                    do_reviews=need_reviews,
                )
            except CaptchaRequiredError as e:
                return {
                    "competitor_listings": listings,
                    "alex_questions": alex_qs,
                    "customer_reviews": reviews,
                    "status": "waiting_human",
                    "pending_action": {
                        "type": "solve_captcha",
                        "context": e.context,
                        "image_url": to_artifact_url(e.image_path),
                        "message": str(e),
                    },
                    "agent_log": logs + [
                        MemoryHelper.log_action("research", "captcha_required", context=e.context)
                    ],
                }

            for asin, res in scraped:
                if "listing" in res:
                    listings.append(res["listing"])
                    logs.append(MemoryHelper.log_action(
                        "research", "scrape_listing",
                        asin=asin,
                        has_error="error" in res["listing"],
                        duration_ms=res["listing_ms"],
                    ))

                if "alex" in res:
                    questions = res["alex"].get("questions", [])
                    alex_qs.extend(questions)
                    logs.append(MemoryHelper.log_action(
                        "research", "scrape_alex",
                        asin=asin,
                        question_count=len(questions),
                        has_error="error" in res["alex"],
                        duration_ms=res["alex_ms"],
                    ))

                if "reviews" in res:
                    asin_reviews = res["reviews"] if isinstance(res["reviews"], list) else []
                    reviews.extend(asin_reviews)
                    logs.append(MemoryHelper.log_action(
                        "research", "scrape_reviews",
                        asin=asin,
                        review_count=len(asin_reviews),
                        duration_ms=res["reviews_ms"],
                    ))

        if not listings:
            return {
                "status": "waiting_human",
                "pending_action": {
                    "type": "upload_competitor_data",
                    "message": "无法自动抓取竞品 Listing，请手动上传竞品 Listing 文件",
                },
                "agent_log": [MemoryHelper.log_action("research", "waiting_upload")],
            }

        # Listings exist but none carries a usable title -> the data is unusable
        # for downstream generation; ask for a re-upload (message mentions title).
        if not any(isinstance(l, dict) and l.get("title") for l in listings):
            return {
                "status": "waiting_human",
                "pending_action": {
                    "type": "upload_competitor_data",
                    "message": "竞品 Listing 缺少标题（title），请重新上传包含完整标题的竞品数据",
                },
                "agent_log": [MemoryHelper.log_action("research", "waiting_upload_missing_title")],
            }

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
