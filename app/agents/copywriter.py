from __future__ import annotations

import json
import os
import time

from app.agents.base import ToolBox
from app.app_settings import get_listing_limits
from app.config import settings
from app.errors import EcoListingError
from app.llm_settings import PROVIDER_OPENAI_COMPATIBLE, get_listing_llm_config, is_configured
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper
from app.tools import codex_progress

# Hard-maximum fallbacks, mirrored from ComplianceTool so the deterministic
# safety net stays correct even if the configured limits are partial/missing.
_LIMIT_DEFAULTS = {
    "title_max_chars": 75,
    "item_highlights_max_chars": 125,
    "bullet_max_chars": 500,
    "bullets_total_max_bytes": 1000,
    "description_max_chars": 2000,
    "st_max_bytes": 249,
}

_MARKETPLACES = {
    "amazon.com": "Amazon US",
    "amazon.com.au": "Amazon AU",
    "amazon.co.uk": "Amazon UK",
    "amazon.de": "Amazon DE",
    "amazon.co.jp": "Amazon JP",
}


def _resolve_limits(limits: dict) -> dict:
    """Effective hard maximums (configured values, else defaults)."""
    return {k: limits.get(k, default) for k, default in _LIMIT_DEFAULTS.items()}


def _as_text(value) -> str:
    """Coerce a string field the model may return as a list into plain text."""
    if isinstance(value, list):
        return " ".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "")


def _as_terms(value) -> list[str]:
    """Search Terms as a list of phrases (prompts ask for an array; a
    space-separated string is split so downstream never iterates characters)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return value.split()
    return []


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
    highlights = _as_text(listing.get("item_highlights"))
    bullets = [str(b) for b in listing.get("bullet_points", [])]
    desc = str(listing.get("description", ""))

    if len(title) > limits["title_max_chars"]:
        title = _trim_to_chars(title, limits["title_max_chars"])
        notes.append(f"标题硬裁剪至 {limits['title_max_chars']} 字符")

    if len(highlights) > limits["item_highlights_max_chars"]:
        highlights = _trim_to_chars(highlights, limits["item_highlights_max_chars"])
        notes.append(f"Item Highlights 硬裁剪至 {limits['item_highlights_max_chars']} 字符")

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

    corrected = {
        **listing,
        "title": title,
        "item_highlights": highlights,
        "bullet_points": bullets,
        "description": desc,
    }
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
    keywords_json = json.dumps(state["classified_keywords"], ensure_ascii=False)

    # Length rules come from the settings page at generation time (so a
    # regenerate picks up edited rules); written back to state below.
    limits = get_listing_limits()
    eff_limits = _resolve_limits(limits)
    brand = (state.get("brand_name") or "").strip()
    alexa_questions = json.dumps(
        state.get("alex_questions") or state.get("rufus_questions") or [],
        ensure_ascii=False,
    )
    # Variables shared by all three rounds (extra keys are ignored by templates).
    common_vars = {
        "brand_name": brand,
        "brand_in_title_policy": (
            "Title 首词写品牌" if brand else "未提供品牌：Title 不写品牌，首词直接写核心产品词"
        ),
        "marketplace": _MARKETPLACES.get(state.get("site", ""), state.get("site") or "Amazon US"),
        # No category-rule source yet; stated explicitly rather than left blank.
        "category_rules": "无",
        **{k: str(v) for k, v in eff_limits.items()},
    }

    # Round 1: Draft generation (Gemini)
    codex_progress.set_stage(run_id, "初稿生成", 1, 3)
    t0 = time.time()
    p1 = toolbox.prompts.render(
        "copywriter",
        "round_1_draft",
        {
            **common_vars,
            "approved_product_attributes": attrs_json,
            "classified_keywords": keywords_json,
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
            **common_vars,
            "draft_v1": json.dumps(v1, ensure_ascii=False),
            "product_attributes": attrs_json,
            "classified_keywords": keywords_json,
            "alexa_questions": alexa_questions,
            # v1/v2 templates still use the old variable name.
            "alex_questions": alexa_questions,
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
    # Any over-limit field (limits resolved above) is fed back as a violation
    # and the whole listing is regenerated.
    rules_text = toolbox.compliance.load_rules()
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
                **common_vars,
                "draft_v2": json.dumps(v2, ensure_ascii=False),
                "product_attributes": attrs_json,
                "compliance_rules": rules_text,
                "previous_violations": violations_ctx or "无",
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
            "item_highlights": _as_text(v3.get("item_highlights")),
            "bullet_points": v3.get("bullet_points", []),
            "description": v3.get("description", ""),
            "search_terms": _as_terms(v3.get("search_terms")),
        }
        violations = toolbox.compliance.validate(listing_for_check, limits, brand=brand)

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
        "item_highlights": final["item_highlights"],
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
        f"{listing['title']} {listing['item_highlights']} "
        f"{' '.join(listing['bullet_points'])} {listing['description']}"
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
        "st_v1": _as_terms(v1.get("search_terms")),
        "draft_listing_v2": v2,
        "st_v2": _as_terms(v2.get("search_terms")),
        "final_listing": listing,
        "st_v3": _as_terms(final.get("search_terms")),
        "length_limits": limits,
        "agent_log": logs,
    }
