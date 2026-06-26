import re
from unittest.mock import AsyncMock

import pytest

from app.agents.keyword_strategist import keyword_classify_node, st_optimize_node


@pytest.mark.asyncio
async def test_classify_is_complete_across_batches(mock_toolbox):
    """Every uploaded keyword is classified even when the LLM drops some per
    batch — regression for 883 keywords classifying down to ~141."""
    library = [{"keyword": f"kw{i}", "search_volume": 250 - i} for i in range(250)]

    # Classify a batch's keywords into A, but drop the LAST one each call to
    # simulate the model silently skipping entries on large inputs.
    def fake_call(model, prompt, **kwargs):
        kws = [k for k in re.findall(r'"keyword":\s*"([^"]+)"', prompt) if k.startswith("kw")]
        keep = kws[:-1] if len(kws) > 1 else kws
        return {"A": [{"keyword": k} for k in keep], "B": [], "C": [], "D": []}

    mock_toolbox.llm.call = AsyncMock(side_effect=fake_call)

    state = {
        "run_id": "test_run",
        "approved_product_attributes": {"x": 1},
        "keyword_library": library,
    }
    result = await keyword_classify_node(state, mock_toolbox)
    ck = result["classified_keywords"]
    classified = {it["keyword"] for b in ("A", "B", "C", "D") for it in ck[b]}
    # Nothing silently dropped: all 250 present (the few the model skipped land
    # in D via the completeness passes).
    assert classified == {k["keyword"] for k in library}
    assert ck["summary"]["total"] == 250


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
