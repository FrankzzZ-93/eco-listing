"""In-memory live progress sidecar for `codex exec` invocations.

Lives next to ``codex_exec.py`` to avoid a circular import: the upward chain
``app.api._state -> app.agents.base -> app.tools.llm_tool -> app.tools.codex_exec``
means ``codex_exec`` cannot import from ``app.api`` or ``app.agents``. This
module deliberately depends on nothing from the project, so both
``codex_exec`` (writer) and ``app.api.routes`` (reader) can safely import it.

Concurrency: writes happen from the asyncio loop driving ``codex_exec``;
reads happen from FastAPI request handlers on the same loop. We never
serialize across threads, so a plain dict + ContextVar is sufficient.
"""

from __future__ import annotations

import datetime
import time
from contextvars import ContextVar
from typing import Optional

# Set by ``app.api.routes`` whenever a graph is executed for a specific run.
# ``codex_exec`` reads it implicitly to attribute progress to the right run
# without changing any function signature in the call chain.
current_run_id: ContextVar[Optional[str]] = ContextVar(
    "current_run_id", default=None
)

# run_id -> internal progress record. Stored fields:
#   started_monotonic: float    — ``time.monotonic()`` at codex start, used
#                                  for accurate elapsed seconds.
#   started_at_iso: str         — wall-clock ISO timestamp for display.
#   current_event_type: str?    — latest ``item.started`` item.type; None
#                                  before the first item arrives.
#   items_completed: int        — count of ``item.completed`` events seen.
#   last_change_at_iso: str     — wall-clock ISO timestamp of the last
#                                  type change (or start).
_progress: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def start(run_id: str) -> None:
    """Begin tracking a fresh codex_exec call for ``run_id``."""
    now_iso = _now_iso()
    _progress[run_id] = {
        "started_monotonic": time.monotonic(),
        "started_at_iso": now_iso,
        "current_event_type": None,
        "items_completed": 0,
        "last_change_at_iso": now_iso,
    }


def set_event_type(run_id: str, event_type: str) -> None:
    """Record an ``item.started`` event type. No-op if no entry exists."""
    entry = _progress.get(run_id)
    if entry is None:
        return
    if entry["current_event_type"] != event_type:
        entry["current_event_type"] = event_type
        entry["last_change_at_iso"] = _now_iso()


def inc_completed(run_id: str) -> None:
    """Record an ``item.completed`` event. No-op if no entry exists."""
    entry = _progress.get(run_id)
    if entry is None:
        return
    entry["items_completed"] += 1


def clear(run_id: str) -> None:
    """Drop the entry for ``run_id``. Safe to call when nothing is tracked."""
    _progress.pop(run_id, None)


def snapshot(run_id: str) -> Optional[dict]:
    """Return a JSON-friendly snapshot, computing fresh ``elapsed_s``.

    Returns ``None`` if no codex_exec is currently tracked for ``run_id``.
    """
    entry = _progress.get(run_id)
    if entry is None:
        return None
    elapsed = max(0.0, time.monotonic() - entry["started_monotonic"])
    return {
        "started_at": entry["started_at_iso"],
        "elapsed_s": round(elapsed, 1),
        "current_event_type": entry["current_event_type"],
        "items_completed": entry["items_completed"],
        "last_change_at": entry["last_change_at_iso"],
    }
