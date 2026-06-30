from unittest.mock import AsyncMock

import pytest

from app.agents.copywriter import copywriter_node

_BASE_STATE = {
    "run_id": "test_run",
    "approved_product_attributes": {
        "target_users": ["home users"],
        "use_cases": ["daily use"],
        "pain_points": ["breaks easily"],
        "core_features": ["durable"],
        "selling_points": ["premium quality"],
        "language_patterns": ["love it"],
    },
    "classified_keywords": {
        "functional": [{"keyword": "waterproof", "search_volume": 100}],
        "scenario": [{"keyword": "outdoor", "search_volume": 50}],
    },
    "alex_questions": ["Is it waterproof?"],
    "alex_screenshots": [],
}


@pytest.mark.asyncio
async def test_copywriter_falls_back_when_round3_returns_empty(mock_toolbox):
    """Regression: an empty round-3 compliance draft must NOT overwrite the
    good round-2 copy. Rounds 1-2 return real content; every round-3 attempt
    returns a structurally valid but empty listing. The final listing should
    fall back to round 2, not ship blank fields."""
    good = {
        "title": "Premium Waterproof Case for Outdoor Use",
        "bullet_points": [
            "DURABLE - built to last",
            "WATERPROOF - rated for outdoor",
            "LIGHTWEIGHT - easy to carry",
            "VERSATILE - fits many devices",
            "WARRANTY - peace of mind",
        ],
        "description": "A durable waterproof case for everyday outdoor adventures.",
        "search_terms": ["waterproof case", "outdoor", "durable"],
    }
    empty = {"title": "", "bullet_points": [], "description": "", "search_terms": []}

    calls = {"n": 0}

    # Mock at the public ``call`` level (the real one shells out to the Codex
    # CLI). Call 1 = round 1, call 2 = round 2; everything after is round-3 retries.
    async def _call(_model, _prompt, **_kwargs):
        calls["n"] += 1
        return dict(good if calls["n"] <= 2 else empty)

    mock_toolbox.llm.call = AsyncMock(side_effect=_call)

    result = await copywriter_node(dict(_BASE_STATE), mock_toolbox)

    listing = result["final_listing"]
    assert listing["title"].strip(), "title must not be empty after fallback"
    assert listing["bullet_points"], "bullet_points must not be empty after fallback"
    assert listing["description"].strip(), "description must not be empty after fallback"
    # Falls back to round 2 (== the good payload's title here).
    assert listing["title"] == good["title"]
    assert any(
        log.get("action") == "round_3_fallback" for log in result["agent_log"]
    )


@pytest.mark.asyncio
async def test_copywriter_produces_listing(mock_toolbox):
    state = {
        "run_id": "test_run",
        "approved_product_attributes": {
            "target_users": ["home users"],
            "use_cases": ["daily use"],
            "pain_points": ["breaks easily"],
            "core_features": ["durable"],
            "selling_points": ["premium quality"],
            "language_patterns": ["love it"],
        },
        "classified_keywords": {
            "functional": [{"keyword": "waterproof", "search_volume": 100}],
            "scenario": [{"keyword": "outdoor", "search_volume": 50}],
        },
        "alex_questions": ["Is it waterproof?"],
        "alex_screenshots": [],
    }
    result = await copywriter_node(state, mock_toolbox)

    assert "final_listing" in result
    assert "title" in result["final_listing"]
    assert "bullet_points" in result["final_listing"]
    assert "description" in result["final_listing"]
    assert "draft_listing_v1" in result
    assert "draft_listing_v2" in result
    assert len(result["agent_log"]) >= 3  # round1 + round2 + round3 + self_eval
