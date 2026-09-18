from unittest.mock import AsyncMock

import pytest

from app.agents.copywriter import copywriter_node
from app.errors import EcoListingError

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
async def test_copywriter_raises_when_all_rounds_empty(mock_toolbox):
    """Final non-empty guard: if every round AND every fallback is empty, the
    node must raise (run marked 'failed') rather than silently shipping a blank
    listing that gets marked 'completed'."""
    empty = {"title": "", "bullet_points": [], "description": "", "search_terms": []}
    mock_toolbox.llm.call = AsyncMock(return_value=dict(empty))

    with pytest.raises(EcoListingError):
        await copywriter_node(dict(_BASE_STATE), mock_toolbox)


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


_TEST_LIMITS = {
    "title_max_chars": 75,
    "item_highlights_max_chars": 125,
    "bullet_max_chars": 500,
    "bullets_total_max_bytes": 1000,
    "description_max_chars": 2000,
    "st_max_bytes": 249,
    # Soft minimums off so a short fixture listing passes on the first try.
    "title_min_chars": 0,
    "bullets_total_min_bytes": 0,
    "description_min_chars": 0,
}

_V3_LISTING = {
    "title": "Acme Waterproof Phone Case for Outdoor Use",
    "item_highlights": "Sealed rugged shell keeps your phone dry on hikes and at the beach",
    "bullet_points": [
        "WATERPROOF SEALED SHELL: Keeps water out when fully closed",
        "RUGGED OUTDOOR BUILD: Protects the phone on trails",
        "CLEAR TOUCH WINDOW: Operate the screen without opening the case",
        "FITS MOST PHONES: Holds phones up to 6.7 inches",
        "WHAT YOU GET: One case and one lanyard",
    ],
    "description": "<p>A sealed waterproof case for outdoor use.</p>",
    # v3 prompts ask for an array, but a space-separated string must still work.
    "search_terms": "dry bag pouch",
}


def _spy_render(toolbox):
    calls = []
    real_render = toolbox.prompts.render

    def _render(agent, template, variables):
        calls.append((template, dict(variables)))
        return real_render(agent, template, variables)

    toolbox.prompts.render = _render
    return calls


@pytest.mark.asyncio
async def test_copywriter_v3_variables_and_item_highlights(mock_toolbox, monkeypatch):
    monkeypatch.setattr(
        "app.agents.copywriter.get_listing_limits", lambda: dict(_TEST_LIMITS)
    )
    mock_toolbox.llm.call = AsyncMock(return_value=dict(_V3_LISTING))
    renders = _spy_render(mock_toolbox)

    state = {**_BASE_STATE, "brand_name": "Acme", "site": "amazon.com"}
    result = await copywriter_node(state, mock_toolbox)

    by_template = {}
    for template, variables in renders:
        by_template.setdefault(template, variables)
    r1, r2, r3 = (
        by_template["round_1_draft"],
        by_template["round_2_alex"],
        by_template["round_3_compliance"],
    )
    assert r1["brand_name"] == "Acme"
    assert r1["marketplace"] == "Amazon US"
    assert r1["title_max_chars"] == "75"
    assert r1["item_highlights_max_chars"] == "125"
    assert r1["brand_in_title_policy"] == "Title 首词写品牌"
    assert "Is it waterproof?" in r2["alexa_questions"]
    assert "waterproof" in r2["classified_keywords"]
    assert r3["brand_name"] == "Acme"
    assert r3["item_highlights_max_chars"] == "125"
    assert r3["previous_violations"] == "无"

    listing = result["final_listing"]
    assert listing["item_highlights"] == _V3_LISTING["item_highlights"]
    assert result["st_v3"] == ["dry", "bag", "pouch"]
    assert result["length_limits"] == _TEST_LIMITS
    assert mock_toolbox.llm.call.await_count == 3  # clean on the first round-3 try


@pytest.mark.asyncio
async def test_copywriter_retries_when_title_misses_brand(mock_toolbox, monkeypatch):
    monkeypatch.setattr(
        "app.agents.copywriter.get_listing_limits", lambda: dict(_TEST_LIMITS)
    )
    no_brand = {**_V3_LISTING, "title": "Waterproof Phone Case for Outdoor Use"}
    responses = [dict(_V3_LISTING), dict(_V3_LISTING), no_brand, dict(_V3_LISTING)]
    mock_toolbox.llm.call = AsyncMock(side_effect=responses)
    renders = _spy_render(mock_toolbox)

    state = {**_BASE_STATE, "brand_name": "Acme", "site": "amazon.com"}
    result = await copywriter_node(state, mock_toolbox)

    round3 = [v for t, v in renders if t == "round_3_compliance"]
    assert len(round3) == 2
    assert "Acme" in round3[1]["previous_violations"]
    assert result["final_listing"]["title"].startswith("Acme ")


@pytest.mark.asyncio
async def test_copywriter_clamps_item_highlights(mock_toolbox, monkeypatch):
    limits = {**_TEST_LIMITS, "item_highlights_max_chars": 20}
    monkeypatch.setattr("app.agents.copywriter.get_listing_limits", lambda: dict(limits))
    monkeypatch.setattr("app.agents.copywriter.settings.copywriter_max_retries", 0)
    mock_toolbox.llm.call = AsyncMock(return_value=dict(_V3_LISTING))

    state = {**_BASE_STATE, "brand_name": "Acme", "site": "amazon.com"}
    result = await copywriter_node(state, mock_toolbox)

    assert len(result["final_listing"]["item_highlights"]) <= 20
