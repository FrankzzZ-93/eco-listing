import pytest

from app.agents.copywriter import copywriter_node


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
        "rufus_questions": ["Is it waterproof?"],
        "rufus_screenshots": [],
    }
    result = await copywriter_node(state, mock_toolbox)

    assert "final_listing" in result
    assert "title" in result["final_listing"]
    assert "bullet_points" in result["final_listing"]
    assert "description" in result["final_listing"]
    assert "draft_listing_v1" in result
    assert "draft_listing_v2" in result
    assert len(result["agent_log"]) >= 3  # round1 + round2 + round3 + self_eval
