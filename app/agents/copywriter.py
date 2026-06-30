from __future__ import annotations

import json
import os
import time

from app.agents.base import ToolBox
from app.config import settings
from app.errors import EcoListingError
from app.llm_settings import PROVIDER_OPENAI_COMPATIBLE, get_listing_llm_config, is_configured
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper
from app.tools import codex_progress

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


def _is_complete_listing(listing: dict) -> bool:
    """True only if title, bullet points, and description all carry real content.

    The round-3 compliance LLM occasionally returns a structurally valid but
    empty draft (all fields ``""``/``[]``). Such a draft passes length
    validation (nothing is over-limit), so without this guard it would be
    accepted and silently overwrite the good round-2 copy with a blank listing.
    """
    if not isinstance(listing, dict):
        return False
    title = (listing.get("title") or "").strip()
    desc = (listing.get("description") or "").strip()
    bullets = listing.get("bullet_points") or []
    has_bullets = isinstance(bullets, list) and any(
        isinstance(b, str) and b.strip() for b in bullets
    )
    return bool(title) and bool(desc) and has_bullets


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

    # Last-resort: never ship an empty bullet (an empty "•"). The retry loop
    # should produce 5 complete bullets, but if one slips through empty, drop it
    # rather than render a blank line.
    non_empty_bullets = [b for b in bullets if str(b).strip()]
    if len(non_empty_bullets) != len(bullets):
        notes.append(f"剔除 {len(bullets) - len(non_empty_bullets)} 条空五点")
        bullets = non_empty_bullets

    corrected = {**listing, "title": title, "bullet_points": bullets, "description": desc}
    return corrected, notes


async def copywriter_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: three-round iterative listing generation."""
    logs: list[dict] = []
    # Live-progress sidecar: copywriter's per-round agent_log only lands when the
    # node finishes, and API runs have no codex event stream — so push the
    # current round here for the dashboard ("文案生成中 第 x/3 轮").
    run_id = codex_progress.current_run_id.get() or state.get("run_id", "")

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
    codex_progress.set_stage(run_id, "初稿生成", 1, 3)
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
    codex_progress.set_stage(run_id, "Alex 优化", 2, 3)
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
    # Best complete-but-not-yet-clean round-3 draft seen so far; used as a
    # fallback before degrading to round 2, so we keep round-3 improvements
    # whenever the model produced real content (length is clamped below).
    best_complete_v3 = None
    MAX_RETRIES = settings.copywriter_max_retries

    for attempt in range(MAX_RETRIES + 1):
        codex_progress.set_stage(
            run_id,
            "合规校正" + (f"（重试 {attempt}）" if attempt else ""),
            3,
            3,
        )
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

        # An empty/incomplete draft must never be accepted: it would pass length
        # validation (nothing over-limit) yet ship a blank listing. Treat it as a
        # violation so the loop retries, and never let it become ``final``.
        complete = _is_complete_listing(v3)
        if complete:
            best_complete_v3 = v3

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
                empty=not complete,
                duration_ms=int((time.time() - t0) * 1000),
            )
        )

        if complete and not violations:
            final = v3
            break

        if not complete:
            violations_ctx = (
                "上一次返回了空文案（title/bullet_points/description 至少一项为空）。"
                "必须返回完整的非空文案。"
            )
        else:
            violations_ctx = "上一次违规：\n" + "\n".join(f"- {v}" for v in violations)

    # Fallback chain when no clean+complete round-3 draft emerged. Best first: a
    # complete round-3 attempt (only length issues, clamped below), then round-2,
    # then round-1. Every candidate is completeness-checked, so a blank draft can
    # never become the shipped listing (the original bug: an empty round-3 result
    # silently overwrote the good round-2 copy).
    if final is None:
        fallback_to = None
        for label, cand in (
            ("round_3_with_violations", best_complete_v3),
            ("round_2", v2),
            ("round_1", v1),
        ):
            if cand is not None and _is_complete_listing(cand):
                final = cand
                fallback_to = label
                break
        logs.append(
            MemoryHelper.log_action(
                "copywriter",
                "round_3_fallback",
                fallback_to=fallback_to or "none",
            )
        )

    # Final non-empty guard: if every round AND every fallback produced an
    # empty/incomplete draft, fail loudly. Shipping a blank listing here is what
    # let a broken run get marked "completed" with empty title/bullets/description.
    if final is None or not _is_complete_listing(final):
        raise EcoListingError(
            "Copywriter 生成的文案为空（title/bullet_points/description 至少一项为空），"
            "且三轮草稿均无可用回退稿。拒绝导出空 listing。"
        )

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

    codex_progress.clear_stage(run_id)
    return {
        "draft_listing_v1": v1,
        "st_v1": v1.get("search_terms", []),
        "draft_listing_v2": v2,
        "st_v2": v2.get("search_terms", []),
        "final_listing": listing,
        "st_v3": final.get("search_terms", []),
        "agent_log": logs,
    }
