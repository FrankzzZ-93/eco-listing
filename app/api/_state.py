"""Runtime state holder — set during FastAPI lifespan, accessed by routes."""
from __future__ import annotations

from typing import Optional

from app.agents.base import ToolBox

_graph = None
_toolbox: Optional[ToolBox] = None


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
