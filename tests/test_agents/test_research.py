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
        "rufus_questions": [],
        "rufus_screenshots": [],
    }
    result = await research_node(state, mock_toolbox)
    assert result["status"] == "running"
    assert len(result["competitor_listings"]) == 1
