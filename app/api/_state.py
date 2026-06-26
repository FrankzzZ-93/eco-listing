"""Runtime state holder — set during FastAPI lifespan, accessed by routes."""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import tempfile
from typing import Optional

from app.agents.base import ToolBox

_graph = None
_toolbox: Optional[ToolBox] = None

_REGISTRY_FILE = "run_registry.json"

# In-memory run registry: run_id -> metadata
_run_registry: dict[str, dict] = {}

# In-memory task tracker: run_id -> asyncio.Task
_run_tasks: dict[str, asyncio.Task] = {}


def _save_registry():
    """Atomically persist _run_registry to disk."""
    dir_name = os.path.dirname(os.path.abspath(_REGISTRY_FILE))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_run_registry, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _REGISTRY_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_registry():
    """Load run registry from disk. Called once at startup."""
    global _run_registry
    if os.path.exists(_REGISTRY_FILE):
        try:
            with open(_REGISTRY_FILE, encoding="utf-8") as f:
                _run_registry = json.load(f)
        except (json.JSONDecodeError, OSError):
            _run_registry = {}


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


def register_run(run_id: str, product_name: str, site: str, competitor_asins: list[str]):
    _run_registry[run_id] = {
        "run_id": run_id,
        "product_name": product_name,
        "site": site,
        "competitor_asins": competitor_asins,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _save_registry()


def list_runs() -> list[dict]:
    return sorted(_run_registry.values(), key=lambda r: r["created_at"], reverse=True)


def remove_run(run_id: str):
    _run_registry.pop(run_id, None)
    _save_registry()


def get_run_meta(run_id: str) -> dict | None:
    return _run_registry.get(run_id)


def has_run(run_id: str) -> bool:
    return run_id in _run_registry


def register_runs_bulk(entries: list[dict]) -> int:
    """Add registry entries that aren't already present; persist once.

    Used by startup reconciliation to backfill the registry from surviving
    checkpoints. Returns the number of entries added.
    """
    added = 0
    for entry in entries:
        rid = entry.get("run_id")
        if rid and rid not in _run_registry:
            _run_registry[rid] = entry
            added += 1
    if added:
        _save_registry()
    return added


def checkpoint_thread_ids(db_path: str) -> list[str]:
    """Distinct ``thread_id``s (= run ids) present in the LangGraph SQLite DB.

    Read with a throwaway connection so we never interfere with the live
    AsyncSqliteSaver. Returns [] if the DB is missing or unreadable.
    """
    import sqlite3

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


def update_run_status(run_id: str, status: str):
    if run_id in _run_registry:
        _run_registry[run_id]["status"] = status
        _save_registry()
