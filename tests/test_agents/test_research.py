import dataclasses
from unittest.mock import AsyncMock

import pytest

from app.agents.research import research_node


@pytest.mark.asyncio
async def test_empty_listings_returns_waiting(mock_toolbox):
    state = {
        "run_id": "test_run",
        "competitor_asins": ["B0TEST"],
        "competitor_listings": [],
    }
    result = await research_node(state, mock_toolbox)
    assert result["status"] == "waiting_human"
    assert result["pending_action"]["type"] == "upload_competitor_data"


@pytest.mark.asyncio
async def test_missing_title_returns_waiting(mock_toolbox):
    state = {
        "run_id": "test_run",
        "competitor_asins": ["B0TEST"],
        "competitor_listings": [{"bullet_points": ["point1"]}],
    }
    result = await research_node(state, mock_toolbox)
    assert result["status"] == "waiting_human"
    assert "title" in result["pending_action"]["message"]


@pytest.mark.asyncio
async def test_valid_listings_pass(mock_toolbox):
    state = {
        "run_id": "test_run",
        "competitor_asins": ["B0TEST"],
        "competitor_listings": [
            {"title": "Test Product", "bullet_points": ["Feature 1"]}
        ],
        "alex_questions": [],
        "alex_screenshots": [],
    }
    result = await research_node(state, mock_toolbox)
    assert result["status"] == "running"
    assert len(result["competitor_listings"]) == 1


@pytest.mark.asyncio
async def test_uploaded_reviews_do_not_block_listing_scrape(mock_toolbox):
    """Per-bucket scrape: pre-uploaded reviews must NOT skip listing/Alex scrape.

    Regression for the per-ASIN refactor where a single combined guard
    (``if not listings and not alex_qs and not reviews``) skipped ALL scraping
    when any one bucket had data — so uploading only reviews left listings
    unscraped and the run stuck at "upload competitor data".
    """
    browser = AsyncMock()
    browser.scrape_listing = AsyncMock(return_value={"title": "T", "bullet_points": ["b"]})
    browser.scrape_alex = AsyncMock(return_value={"questions": ["q1"]})
    browser.scrape_reviews = AsyncMock(return_value=[{"body": "should not be called"}])
    toolbox = dataclasses.replace(mock_toolbox, browser=browser)

    state = {
        "run_id": "test_run",
        "competitor_asins": ["B0TEST"],
        "customer_reviews": [{"body": "user-uploaded review"}],  # already present
        # competitor_listings + alex_questions are missing
    }
    result = await research_node(state, toolbox)

    # Missing buckets get scraped...
    browser.scrape_listing.assert_awaited()
    browser.scrape_alex.assert_awaited()
    # ...but the already-present reviews are NOT re-scraped.
    browser.scrape_reviews.assert_not_awaited()
    assert result["status"] == "running"
    assert len(result["competitor_listings"]) == 1
