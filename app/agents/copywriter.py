from __future__ import annotations

import json
import os
import time

from app.agents.base import ToolBox
from app.config import settings
from app.llm_settings import PROVIDER_OPENAI_COMPATIBLE, get_listing_llm_config, is_configured
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper

# Hard-maximum fallbacks, mirrored from ComplianceTool so the deterministic
# safety net stays correct even if a run's length_limits is partial/missing.
_LIMIT_DEFAULTS = {
    "title_max_chars": 200,
    "bullet_max_chars": 500,
    "bullets_total_max_bytes": 1000,
    "description_max_chars": 2000,
    "st_max_bytes": 249,
}


def _resolve_limits(state: ListingState) -> dict:
    """Effective hard maximums for this run (state overrides, else defaults)."""
    limits = state.get("length_limits") or {}
    return {k: limits.get(k, default) for k, default in _LIMIT_DEFAULTS.items()}


def _trim_to_chars(text: str, max_chars: int) -> str:
    """Trim plain text to ``max_chars``, preferring a word boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    sp = cut.rfind(" ")
    if sp > max_chars * 0.6:
        cut = cut[:sp]
    return cut.rstrip()


def _trim_description(desc: str, max_chars: int) -> str:
    """Trim an HTML description to ``max_chars`` without leaving a broken tag.

    Cuts at ``max_chars``, then: drops a dangling partial ``<tag`` (when the
    cut landed inside a tag), and prefers a block/sentence/word boundary so the
    output stays readable. This is a last-resort safety net; the prompt should
    keep the model within budget in the common case.
    """
    if len(desc) <= max_chars:
        return desc
    cut = desc[:max_chars]
    # If we cut inside a tag (an unmatched '<' after the last '>'), drop it.
    if cut.rfind("<") > cut.rfind(">"):
        cut = cut[: cut.rfind("<")]
    for sep in ("</p>", "</li>", "</ul>", "</ol>", ". ", " "):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.5:
            cut = cut[: idx + (len(sep) if sep.startswith("<") else 0)]
            break
    return cut.rstrip()


def _enforce_limits(listing: dict, limits: dict) -> tuple[dict, list[str]]:
    """Deterministically clamp a listing to the hard maximums.

    Guarantees compliance regardless of LLM behavior. Returns the corrected
    listing plus a list of human-readable notes for any field that was trimmed.
    """
    notes: list[str] = []
    title = str(listing.get("title", ""))
    bullets = [str(b) for b in listing.get("bullet_points", [])]
    desc = str(listing.get("description", ""))

    if len(title) > limits["title_max_chars"]:
        title = _trim_to_chars(title, limits["title_max_chars"])
        notes.append(f"标题硬裁剪至 {limits['title_max_chars']} 字符")

    for i, b in enumerate(bullets):
        if len(b) > limits["bullet_max_chars"]:
            bullets[i] = _trim_to_chars(b, limits["bullet_max_chars"])
            notes.append(f"Bullet #{i + 1} 硬裁剪至 {limits['bullet_max_chars']} 字符")

    def _bullets_bytes() -> int:
        return len("\n".join(bullets).encode("utf-8"))

    budget = limits["bullets_total_max_bytes"]
    trimmed_total = False
    guard = 0
    while _bullets_bytes() > budget and guard < 5000:
        guard += 1
        i = max(range(len(bullets)), key=lambda k: len(bullets[k].encode("utf-8")))
        b = bullets[i].rstrip()
        if not b:
            break
        # Drop ~the overflow in one shot (chars≈bytes for ASCII; multibyte just
        # loops again), at least 1 char, preferring a word boundary.
        over = _bullets_bytes() - budget
        target_len = max(0, len(b) - max(1, over))
        cut = b[:target_len]
        sp = cut.rfind(" ")
        if sp > target_len * 0.6:
            cut = cut[:sp]
        bullets[i] = cut.rstrip()
        trimmed_total = True
    if trimmed_total:
        notes.append(f"五点合计硬裁剪至 ≤ {budget} 字节")

    if len(desc) > limits["description_max_chars"]:
        desc = _trim_description(desc, limits["description_max_chars"])
        notes.append(f"Description 硬裁剪至 ≤ {limits['description_max_chars']} 字符")

    corrected = {**listing, "title": title, "bullet_points": bullets, "description": desc}
    return corrected, notes


async def copywriter_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: three-round iterative listing generation."""
    logs: list[dict] = []

    # Resolve the listing copywriter model. Defaults to codex-cli; users can
    # switch to an OpenAI-compatible API (Opus/Claude/etc.) in the UI settings.
    llm_cfg = get_listing_llm_config()
    use_api = (
        llm_cfg.get("provider") == PROVIDER_OPENAI_COMPATIBLE and is_configured(llm_cfg)
    )
    model_label = llm_cfg.get("model") if use_api else "codex-cli"

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
    v1 = await toolbox.llm.call("gemini-pro", p1, llm_config=llm_cfg)
    logs.append(
        MemoryHelper.log_action(
            "copywriter",
            "round_1_draft",
            model=model_label,
            duration_ms=int((time.time() - t0) * 1000),
        )
    )

    # Round 2: Alex optimization (Claude)
    t0 = time.time()
    p2 = toolbox.prompts.render(
        "copywriter",
        "round_2_alex",
        {
            "draft_v1": json.dumps(v1, ensure_ascii=False),
            "product_attributes": attrs_json,
            "alex_questions": json.dumps(
                state.get("alex_questions") or state.get("rufus_questions") or [],
                ensure_ascii=False,
            ),
        },
    )
    attachments = [
        p
        for p in (state.get("alex_screenshots") or state.get("rufus_screenshots") or [])
        if os.path.exists(p)
    ]
    v2 = await toolbox.llm.call("claude-sonnet", p2, attachments=attachments, llm_config=llm_cfg)
    logs.append(
        MemoryHelper.log_action(
            "copywriter",
            "round_2_alex",
            model=model_label,
            duration_ms=int((time.time() - t0) * 1000),
        )
    )

    # Round 3: Compliance + length correction with retry loop.
    # Length limits live in state (seeded from settings at create time) so they
    # are checkpointed and per-run customizable; any over-limit field is fed
    # back as a violation and the whole listing is regenerated.
    rules_text = toolbox.compliance.load_rules()
    limits = state.get("length_limits") or {}
    eff_limits = _resolve_limits(state)
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
                "title_max_chars": str(eff_limits["title_max_chars"]),
                "bullet_max_chars": str(eff_limits["bullet_max_chars"]),
                "bullets_total_max_bytes": str(eff_limits["bullets_total_max_bytes"]),
                "description_max_chars": str(eff_limits["description_max_chars"]),
                "st_max_bytes": str(eff_limits["st_max_bytes"]),
            },
        )
        v3 = await toolbox.llm.call("claude-sonnet", p3, llm_config=llm_cfg)

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

    # Deterministic safety net: the LLM loop ships its last draft even when
    # length violations remain, so hard-clamp the binding maximums here to
    # guarantee the shipped listing is never over-limit.
    final, trim_notes = _enforce_limits(final, eff_limits)
    if trim_notes:
        logs.append(
            MemoryHelper.log_action(
                "copywriter",
                "enforce_limits",
                trims="; ".join(trim_notes),
            )
        )

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
