"""Runtime state holder — set during FastAPI lifespan, accessed by routes.

The run list is derived directly from the LangGraph checkpoint DB
(``checkpoints.db``) — the single source of truth. There is no separate run
registry/index file; this avoids the index-vs-data desync that previously made
the list go blank, resurrect deleted runs, or break on a different cwd.
"""
from __future__ import annotations

import asyncio
import datetime
import os
import re
import sqlite3
from typing import Optional

from app.agents.base import ToolBox

_graph = None
_toolbox: Optional[ToolBox] = None

# In-memory task tracker: run_id -> asyncio.Task
_run_tasks: dict[str, asyncio.Task] = {}

_RUN_ID_DATE_RE = re.compile(r"run_(\d{4})(\d{2})(\d{2})_")


def set_run_task(run_id: str, task: asyncio.Task):
    _run_tasks[run_id] = task


def get_run_task(run_id: str) -> Optional[asyncio.Task]:
    return _run_tasks.get(run_id)


def remove_run_task(run_id: str):
    _run_tasks.pop(run_id, None)


def set_graph(graph):
    global _graph
    _graph = graph


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph not initialized. Is the server running?")
    return _graph


def set_toolbox(toolbox: ToolBox):
    global _toolbox
    _toolbox = toolbox


def get_toolbox() -> ToolBox:
    if _toolbox is None:
        raise RuntimeError("ToolBox not initialized. Is the server running?")
    return _toolbox


# --- Run enumeration (derived from the checkpoint DB) ---


def checkpoint_thread_ids(db_path: str) -> list[str]:
    """Distinct ``thread_id``s (= run ids) present in the LangGraph SQLite DB.

    Read with a throwaway connection so we never interfere with the live
    AsyncSqliteSaver. Returns [] if the DB is missing or unreadable.
    """
    if not os.path.exists(db_path):
        return []
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def created_at_from_run_id(run_id: str) -> str:
    """Best-effort creation time parsed from a run id (``run_YYYYMMDD_xxxxxx``);
    falls back to epoch so ordering is still deterministic when it doesn't match."""
    m = _RUN_ID_DATE_RE.match(run_id)
    if m:
        try:
            y, mo, d = (int(g) for g in m.groups())
            return datetime.datetime(y, mo, d, tzinfo=datetime.timezone.utc).isoformat()
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(0, datetime.timezone.utc).isoformat()
