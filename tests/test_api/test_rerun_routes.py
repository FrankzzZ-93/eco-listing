"""Regression: re-uploading a keyword library must re-run classification and
pause at the classification review — even when the run is currently PAUSED at
that review gate (stored status is still "running" there, but no task is live).

Previously the guard checked ``status == "running"`` and wrongly rejected the
re-upload; users then fell back to "regenerate listing", which reused the stale
classification and jumped straight to the copywriter.
"""
import asyncio
import io

import openpyxl
import pytest
from langgraph.checkpoint.memory import MemorySaver

import app.agents.orchestrator as orch
from app.api import _state, routes
from app.tools.keyword_tool import KeywordTool


def _xiyou_xlsx(keyword: str, volume: int) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["关键词 (数据来源于西柚洞察)", "翻译", "周平均搜索量"])
    ws.append([keyword, "译", volume])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _Upload:
    """Minimal stand-in for FastAPI's UploadFile (only .filename / .read used)."""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _stub(name, **sets):
    async def _node(state, toolbox=None):
        if name == "keyword_classify":
            # Reflect the CURRENT library so the test can prove a re-run happened.
            lib = state.get("keyword_library") or []
            first = lib[0].get("keyword", "") if lib else ""
            return {"classified_keywords": {"A": [{"keyword": first}]}}
        return {"agent_log": [{"agent": name, "action": "ran"}], **sets}

    _node.__name__ = name
    return _node


@pytest.fixture
def stub_graph(monkeypatch):
    monkeypatch.setattr(orch, "research_node", _stub("research"))
    monkeypatch.setattr(orch, "product_analyst_node", _stub("product_analyst"))
    monkeypatch.setattr(orch, "keyword_classify_node", _stub("keyword_classify"))
    monkeypatch.setattr(
        orch, "copywriter_node",
        _stub("copywriter", final_listing={"title": "t", "bullet_points": ["b"], "description": "d"}),
    )
    monkeypatch.setattr(orch, "st_optimize_node", _stub("st_optimize", final_st=["w"]))
    monkeypatch.setattr(orch, "_export_node", _stub("export", status="completed"))

    class _Toolbox:
        keyword = KeywordTool()

    app = orch.create_app_graph(_Toolbox(), MemorySaver())
    monkeypatch.setattr(_state, "_graph", app, raising=False)
    monkeypatch.setattr(_state, "_toolbox", _Toolbox(), raising=False)
    _state._run_tasks.clear()
    return app


async def _drive_to_review(app, run_id):
    cfg = {"configurable": {"thread_id": run_id}}
    await app.ainvoke(
        {"run_id": run_id, "status": "running",
         "product_attributes_draft": {"x": 1},
         "keyword_library": [{"keyword": "old", "search_volume": 1}]},
        cfg,
    )
    await app.ainvoke(None, cfg)  # human_review -> keyword_classify -> pause at review
    return cfg


@pytest.mark.asyncio
async def test_rerun_from_keywords_reclassifies_when_paused_at_review(stub_graph):
    app = stub_graph
    run_id = "run_rerun"
    cfg = await _drive_to_review(app, run_id)

    st = await app.aget_state(cfg)
    assert st.next == ("keyword_classify_review",)
    assert st.values["classified_keywords"]["A"][0]["keyword"] == "old"
    # No live task while paused at the gate — the earlier ainvoke already returned.
    assert not routes._is_actively_running(run_id)

    # Re-upload a NEW library. Must NOT 400, and must re-run classification.
    upload = _Upload("kw.xlsx", _xiyou_xlsx("newkw", 500))
    resp = await routes.rerun_from_keywords(run_id, upload)
    assert resp["status"] == "accepted"

    task = _state.get_run_task(run_id)
    assert task is not None
    await task  # let the resumed graph run to the next pause

    st = await app.aget_state(cfg)
    assert st.next == ("keyword_classify_review",), "must pause at classification review again"
    assert st.values["classified_keywords"]["A"][0]["keyword"] == "newkw", "re-classified with new library"
