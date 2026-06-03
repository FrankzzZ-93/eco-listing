from __future__ import annotations

import json
import os
import time

from app.agents.base import ToolBox
from app.config import settings
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


async def copywriter_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: three-round iterative listing generation."""
    logs: list[dict] = []

    # Defensive fallback: human_review now copies the draft when no explicit
    # approval is submitted, but we also degrade gracefully for any historical
    # state that escaped that fix.
    attrs = (
        state.get("approved_product_attributes")
        or state.get("product_attributes_draft")
        or {}
    )
    attrs_json = json.dumps(attrs, ensure_ascii=False)

    # Round 1: Draft generation (Gemini)
    t0 = time.time()
    p1 = toolbox.prompts.render(
        "copywriter",
        "round_1_draft",
        {
            "approved_product_attributes": attrs_json,
            "classified_keywords": json.dumps(
                state["classified_keywords"], ensure_ascii=False
            ),
        },
    )
    v1 = await toolbox.llm.call("gemini-pro", p1)
    logs.append(
        MemoryHelper.log_action(
            "copywriter",
            "round_1_draft",
            model="gemini-pro",
            duration_ms=int((time.time() - t0) * 1000),
        )
    )

    # Round 2: Rufus optimization (Claude)
    t0 = time.time()
    p2 = toolbox.prompts.render(
        "copywriter",
        "round_2_rufus",
        {
            "draft_v1": json.dumps(v1, ensure_ascii=False),
            "product_attributes": attrs_json,
            "rufus_questions": json.dumps(
                state.get("rufus_questions", []), ensure_ascii=False
            ),
        },
    )
    attachments = [
        p for p in state.get("rufus_screenshots", []) if os.path.exists(p)
    ]
    v2 = await toolbox.llm.call("claude-sonnet", p2, attachments=attachments)
    logs.append(
        MemoryHelper.log_action(
            "copywriter",
            "round_2_rufus",
            model="claude-sonnet",
            duration_ms=int((time.time() - t0) * 1000),
        )
    )

    # Round 3: Compliance + length correction with retry loop.
    # Length limits live in state (seeded from settings at create time) so they
    # are checkpointed and per-run customizable; any over-limit field is fed
    # back as a violation and the whole listing is regenerated.
    rules_text = toolbox.compliance.load_rules()
    limits = state.get("length_limits") or {}
    violations_ctx = ""
    final = None
    MAX_RETRIES = settings.copywriter_max_retries

    for attempt in range(MAX_RETRIES + 1):
        t0 = time.time()
        p3 = toolbox.prompts.render(
            "copywriter",
            "round_3_compliance",
            {
                "draft_v2": json.dumps(v2, ensure_ascii=False),
                "product_attributes": attrs_json,
                "compliance_rules": rules_text,
                "previous_violations": violations_ctx,
            },
        )
        v3 = await toolbox.llm.call("claude-sonnet", p3)

        listing_for_check = {
            "title": v3.get("title", ""),
            "bullet_points": v3.get("bullet_points", []),
            "description": v3.get("description", ""),
            "search_terms": v3.get("search_terms", []),
        }
        violations = toolbox.compliance.validate(listing_for_check, limits)

        logs.append(
            MemoryHelper.log_action(
                "copywriter",
                "round_3_compliance",
                attempt=attempt,
                violations=len(violations),
                duration_ms=int((time.time() - t0) * 1000),
            )
        )

        if not violations:
            final = v3
            break

        violations_ctx = "上一次违规：\n" + "\n".join(f"- {v}" for v in violations)

    if final is None:
        final = v3

    listing = {
        "title": final["title"],
        "bullet_points": final["bullet_points"],
        "description": final["description"],
    }

    # Self-evaluation: keyword coverage
    kw_all: set[str] = set()
    for words in state.get("classified_keywords", {}).values():
        if isinstance(words, list):
            for w in words:
                kw_all.add(
                    w.lower() if isinstance(w, str) else w.get("keyword", "").lower()
                )
    listing_text = (
        f"{listing['title']} {' '.join(listing['bullet_points'])} {listing['description']}"
    ).lower()
    covered = sum(1 for kw in kw_all if kw in listing_text)
    coverage = covered / len(kw_all) if kw_all else 0
    logs.append(
        MemoryHelper.log_action(
            "copywriter", "self_eval", keyword_coverage=f"{coverage:.0%}"
        )
    )

    return {
        "draft_listing_v1": v1,
        "st_v1": v1.get("search_terms", []),
        "draft_listing_v2": v2,
        "st_v2": v2.get("search_terms", []),
        "final_listing": listing,
        "st_v3": final.get("search_terms", []),
        "agent_log": logs,
    }
