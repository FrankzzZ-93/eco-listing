import json
import os
import time

from app.agents.base import ToolBox
from app.memory.schemas import ListingState
from app.memory.shared_memory import MemoryHelper


async def product_analyst_node(state: ListingState, toolbox: ToolBox) -> dict:
    """LangGraph node: fuse competitor data into a structured product attribute table."""
    t0 = time.time()
    attachments = [
        p for p in state.get("rufus_screenshots", []) if os.path.exists(p)
    ]

    prompt = toolbox.prompts.render(
        "product_analyst",
        "info_fusion",
        {
            "competitor_listings": json.dumps(
                state["competitor_listings"], ensure_ascii=False
            ),
            "review_summary": json.dumps(
                state.get("review_summary", {}), ensure_ascii=False
            ),
            "rufus_questions": json.dumps(
                state.get("rufus_questions", []), ensure_ascii=False
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
