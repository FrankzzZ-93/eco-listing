"""Convert an uploaded 本品属性表 (excel / md / json) into the canonical schema.

The structured attribute-review panel only renders the internal schema produced
by ``product_analyst`` (keys ``basic_info`` / ``market_analysis`` /
``copywriting_ref``; see ``prompts/product_analyst/info_fusion_v2.md``). Users
may upload a ready-made table in arbitrary shapes/languages (e.g. a 西柚/欧鹭
export, a markdown table, or a Chinese-keyed JSON), so we normalize it into the
canonical schema via the LLM before storing it as ``product_attributes_draft``.

A JSON upload that already contains ``basic_info`` is treated as canonical and
used as-is (no LLM round-trip).
"""
from __future__ import annotations

import io
import json

import openpyxl

from app.agents.base import ToolBox
from app.agents.product_analyst import _strip_asins


def is_canonical(data: object) -> bool:
    """True when ``data`` already follows the internal attribute schema."""
    return isinstance(data, dict) and "basic_info" in data


def xlsx_to_markdown(content: bytes) -> str:
    """Render every sheet/row of an xlsx workbook as plain markdown-ish text.

    Attribute tables have no fixed column layout (unlike keyword exports), so we
    just dump all non-empty rows as ``a | b | c`` lines and let the LLM map the
    content into the canonical schema.
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for ws in wb.worksheets:
            rows = [
                ["" if c is None else str(c) for c in row]
                for row in ws.iter_rows(values_only=True)
            ]
            rows = [r for r in rows if any(cell.strip() for cell in r)]
            if not rows:
                continue
            parts.append(f"### Sheet: {ws.title}")
            parts.extend(" | ".join(r) for r in rows)
    finally:
        wb.close()
    return "\n".join(parts).strip()


async def normalize_uploaded_attributes(toolbox: ToolBox, raw_text: str) -> dict:
    """LLM-convert raw attribute-table text into the canonical schema dict.

    Raises ``ValueError`` when the model returns no parseable structured object,
    so the caller can surface a hard error (and block the run from starting).
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("属性表内容为空")

    prompt = toolbox.prompts.render(
        "product_analyst",
        "attr_normalize",
        {"raw_attributes": raw_text},
    )
    model = toolbox.prompts.get_model("product_analyst", "attr_normalize")
    result = await toolbox.llm.call(model, prompt)

    # LLMTool returns {"text": ...} when it cannot parse a JSON object.
    if not isinstance(result, dict) or not result or set(result.keys()) == {"text"}:
        raise ValueError("模型未返回有效的结构化属性表")

    return _strip_asins(result)
