import json
import os
import re
import time

from app.agents.base import ToolBox
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper
from app.tools.keyword_tool import ASIN_RE

# Matches an ASIN source-label prefix the model tends to emit when competitor
# values differ, e.g. "B0XXXXXXXX: " or "B0AAA/B0BBB: " (full/half-width colon).
_ASIN_LABEL_RE = re.compile(
    r"(?:B0[A-Z0-9]{8})(?:\s*/\s*B0[A-Z0-9]{8})*\s*[:：]\s*",
    re.IGNORECASE,
)
# Matches filler clauses like "；其他ASIN无数据" / "; 其他ASIN无具体人群数据".
_ASIN_FILLER_RE = re.compile(r"[；;，,]?\s*其他\s*ASIN[^；;]*", re.IGNORECASE)


def _strip_asin_text(text: str) -> str:
    """Remove ASIN source-labels/filler so attribute values show content only."""
    s = _ASIN_LABEL_RE.sub("", text)
    s = _ASIN_FILLER_RE.sub("", s)
    s = ASIN_RE.sub("", s)  # any residual standalone ASIN tokens
    s = re.sub(r"\s*[；;]\s*[；;]+", "； ", s)  # collapse empty separators
    s = re.sub(r"^[\s；;，,:：/]+", "", s)  # leading punctuation left over
    s = re.sub(r"[\s；;，,]+$", "", s)  # trailing punctuation left over
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _strip_asins(obj):
    """Recursively strip ASIN labels from every string value in the draft."""
    if isinstance(obj, str):
        return _strip_asin_text(obj)
    if isinstance(obj, list):
        return [_strip_asins(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_asins(v) for k, v in obj.items()}
    return obj


async def product_analyst_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: fuse competitor data into a structured product attribute table."""
    t0 = time.time()

    # Defensive guard: if a ready-made 本品属性表 was uploaded (or a draft was
    # already produced), never overwrite it with a competitor-fused regeneration.
    # The orchestrator routing normally skips this node when a draft exists, but
    # this keeps the node idempotent against routing edge cases / re-entry so an
    # uploaded table is always honored.
    existing_draft = state.get("product_attributes_draft")
    if MemoryHelper.has(state, "product_attributes_draft"):
        return {
            "status": "waiting_human",
            "pending_action": {
                "type": "review_product_attributes",
                "data": existing_draft,
            },
            "agent_log": [
                MemoryHelper.log_action(
                    "product_analyst",
                    "skip_generate_attributes",
                    reason="本品属性表已存在，跳过竞品生成",
                )
            ],
        }

    attachments = [
        p
        for p in (state.get("alex_screenshots") or state.get("rufus_screenshots") or [])
        if os.path.exists(p)
    ]

    prompt = toolbox.prompts.render(
        "product_analyst",
        "info_fusion",
        {
            "competitor_listings": json.dumps(
                state.get("competitor_listings", []), ensure_ascii=False
            ),
            "review_summary": json.dumps(
                state.get("review_summary", {}), ensure_ascii=False
            ),
            "alex_questions": json.dumps(
                state.get("alex_questions") or state.get("rufus_questions") or [],
                ensure_ascii=False,
            ),
        },
    )

    draft = await toolbox.llm.call("gemini-pro", prompt, attachments=attachments)

    eval_prompt = toolbox.prompts.render(
        "product_analyst",
        "self_eval",
        {"draft": json.dumps(draft, ensure_ascii=False)},
    )
    evaluation = await toolbox.llm.call("claude-sonnet", eval_prompt)
    confidence = evaluation.get("confidence", 0.5)
    notes = evaluation.get("notes", "")

    if confidence < 0.7:
        prompt_v2 = prompt + f"\n\n## 上一轮评估反馈\n{notes}\n请据此改进。"
        draft = await toolbox.llm.call("gemini-pro", prompt_v2, attachments=attachments)
        eval2 = await toolbox.llm.call(
            "claude-sonnet",
            toolbox.prompts.render(
                "product_analyst",
                "self_eval",
                {"draft": json.dumps(draft, ensure_ascii=False)},
            ),
        )
        confidence = eval2.get("confidence", confidence)
        notes = eval2.get("notes", notes)

    # Strip ASIN source-labels so the attribute table shows content directly
    # (also keeps ASINs out of the data fed to the copywriter downstream).
    draft = _strip_asins(draft)

    duration = int((time.time() - t0) * 1000)

    return {
        "product_attributes_draft": draft,
        "product_attributes_confidence": confidence,
        "product_attributes_notes": notes,
        "status": "waiting_human",
        "pending_action": {
            "type": "review_product_attributes",
            "data": draft,
            "confidence": confidence,
            "agent_notes": notes,
        },
        "agent_log": [
            MemoryHelper.log_action(
                "product_analyst",
                "generate_attributes",
                confidence=confidence,
                duration_ms=duration,
            )
        ],
    }
