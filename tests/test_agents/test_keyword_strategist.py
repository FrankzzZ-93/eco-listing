import pytest

from app.agents.keyword_strategist import keyword_classify_node, st_optimize_node


@pytest.mark.asyncio
async def test_classify_returns_classified(mock_toolbox):
    state = {
        "run_id": "test_run",
        "approved_product_attributes": {
            "target_users": ["home users"],
            "selling_points": ["durable"],
        },
        "keyword_library": [
            {"keyword": "waterproof", "search_volume": 100},
            {"keyword": "durable", "search_volume": 80},
        ],
    }
    result = await keyword_classify_node(state, mock_toolbox)
    assert "classified_keywords" in result
    assert len(result["agent_log"]) >= 1


@pytest.mark.asyncio
async def test_st_optimize_respects_byte_limit(mock_toolbox):
    state = {
        "run_id": "test_run",
        "final_listing": {
            "title": "Test Product",
            "bullet_points": ["Feature"],
            "description": "Description",
        },
        "st_v3": ["keyword1", "keyword2"],
        "classified_keywords": {
            "functional": [
                {"keyword": f"kw{i}", "search_volume": 1000 - i}
                for i in range(30)
            ]
        },
    }
    result = await st_optimize_node(state, mock_toolbox)
    assert "final_st" in result
    total = len(" ".join(result["final_st"]).encode("utf-8"))
    assert total <= 249
