"""Unit tests for the image-generation tool's pure helpers.

The codex-driven generation path needs a live codex CLI, so it's exercised by a
manual spike rather than here; these cover the deterministic logic only.
"""
import json

import pytest

from app.tools import image_gen_tool as ig
from app.tools import file_store


def _agent_message_line(text: str) -> str:
    """Build one codex JSONL event carrying a final agent_message."""
    return json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": text},
    })


def test_build_prompt_locks_builtin_and_forbids_cli_and_key():
    p = ig._build_prompt(
        "a red mug",
        target_paths=["/tmp/a/1.png"],
        size="1024x1024",
        quality="high",
        reference_paths=[],
        white_bg=False,
    )
    assert "built-in `image_gen` tool" in p
    assert "Do NOT use the CLI fallback" in p
    assert "OPENAI_API_KEY" in p  # explicitly told NOT to use it
    assert "1024x1024" in p
    assert "Quality: high" in p
    assert "/tmp/a/1.png" in p
    assert "a red mug" in p


def test_build_prompt_includes_reference_and_white_bg_sections():
    p = ig._build_prompt(
        "a mug",
        target_paths=["/tmp/1.png", "/tmp/2.png"],
        size="auto",
        quality="high",
        reference_paths=["/data/ref1.jpg", "/data/ref2.jpg"],
        white_bg=True,
    )
    assert "view_image" in p
    assert "/data/ref1.jpg" in p and "/data/ref2.jpg" in p
    assert "same product identity" in p.lower()
    # white_bg uses the chroma-key workflow (open-source-identical), not a plain
    # "white background" instruction.
    assert "#FFFFFF" in p
    assert "#00ff00" in p
    assert "remove_chroma_key.py" in p


def test_parse_saved_paths_reads_last_agent_message_json():
    raw = "\n".join([
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "x"}}),
        _agent_message_line(json.dumps({"saved": ["/tmp/a.png", "/tmp/b.png"]})),
        json.dumps({"type": "turn.completed"}),
    ])
    assert ig._parse_saved_paths(raw) == ["/tmp/a.png", "/tmp/b.png"]


def test_parse_saved_paths_strips_code_fences():
    fenced = "```json\n" + json.dumps({"saved": ["/tmp/x.png"]}) + "\n```"
    raw = _agent_message_line(fenced)
    assert ig._parse_saved_paths(raw) == ["/tmp/x.png"]


def test_parse_saved_paths_returns_empty_on_garbage():
    assert ig._parse_saved_paths("not json\nstill not json") == []
    assert ig._parse_saved_paths(_agent_message_line("hi there")) == []


@pytest.mark.asyncio
async def test_generate_images_rejects_empty_prompt():
    with pytest.raises(ValueError):
        await ig.generate_images("run1", "   ")


def test_from_artifact_url_blocks_traversal_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(file_store.settings, "artifacts_dir", str(tmp_path))
    # traversal escapes the base -> None
    assert file_store.from_artifact_url("/artifacts/../../etc/passwd") is None
    # in-bounds but missing -> None
    assert file_store.from_artifact_url("/artifacts/run1/nope.png") is None
    # empty -> None
    assert file_store.from_artifact_url("") is None
    # in-bounds and existing -> resolved absolute path
    f = tmp_path / "run1" / "generated" / "img.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    assert file_store.from_artifact_url("/artifacts/run1/generated/img.png") == str(f)
