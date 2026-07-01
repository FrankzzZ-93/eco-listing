"""Unit tests for the image-generation tool's pure helpers.

The codex-driven generation path needs a live codex CLI, so it's exercised by a
manual spike rather than here; these cover the deterministic logic only.
"""
import json
import os

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


def test_build_prompt_white_bg_uses_vendored_script_and_no_bash_expansion():
    """Regression (Windows): the chroma-key step must reference the repo-vendored
    script by absolute path + the backend's own Python, with NO bash-only
    ``${CODEX_HOME:-$HOME/.codex}`` expansion that breaks on a Windows shell."""
    p = ig._build_prompt(
        "a mug",
        target_paths=["/tmp/1.png"],
        size="auto",
        quality="high",
        reference_paths=[],
        white_bg=True,
    )
    assert ig.REMOVE_CHROMA_KEY_SCRIPT in p  # absolute, vendored path
    assert ig._PYTHON in p  # backend interpreter (has Pillow)
    assert "${CODEX_HOME" not in p and "$HOME/.codex" not in p


@pytest.mark.asyncio
async def test_generate_images_raises_with_downloadable_log_when_no_files(tmp_path, monkeypatch):
    """When codex exits cleanly but produces no image, fail with ImageGenError
    carrying a log_url, and physically write the full report (prompt + codex
    output) so the failure is diagnosable on another machine."""
    monkeypatch.setattr(ig.settings, "artifacts_dir", str(tmp_path))

    async def _fake_codex_exec(_prompt, **_kw):
        return "no json here\nstill nothing"

    monkeypatch.setattr(ig, "codex_exec", _fake_codex_exec)

    with pytest.raises(ig.ImageGenError) as ei:
        await ig.generate_images("run1", "a red mug", n=1, white_bg=False, job_id="job123")

    assert ei.value.log_url  # a downloadable detail log
    log_file = tmp_path / "run1" / "generated" / "imagegen_job123.log"
    assert log_file.is_file()
    body = log_file.read_text(encoding="utf-8")
    assert "CODEX FULL OUTPUT" in body and "a red mug" in body


@pytest.mark.asyncio
async def test_generate_images_uses_workspace_write_sandbox(tmp_path, monkeypatch):
    """Codex's default read-only sandbox blocks the shell step from saving the
    image (observed 'Read-only file system'). Generation must request
    ``workspace-write`` and hand codex the output dir as a writable root."""
    monkeypatch.setattr(ig.settings, "artifacts_dir", str(tmp_path))
    captured: dict = {}

    async def _fake_codex_exec(_prompt, **kw):
        captured.update(kw)
        return "no files produced"

    monkeypatch.setattr(ig, "codex_exec", _fake_codex_exec)

    with pytest.raises(ig.ImageGenError):
        await ig.generate_images("run1", "a mug", white_bg=False, job_id="j")

    assert captured.get("sandbox") == "workspace-write"
    roots = captured.get("writable_roots") or []
    assert roots and all(os.path.isabs(r) for r in roots)
    assert os.path.abspath(str(tmp_path)) in roots[0]  # the run's output dir


@pytest.mark.asyncio
async def test_generate_images_white_bg_missing_script_fails_fast(tmp_path, monkeypatch):
    """White-bg with the vendored helper missing must fail fast with a clear,
    logged ImageGenError rather than silently calling codex and getting nothing."""
    monkeypatch.setattr(ig.settings, "artifacts_dir", str(tmp_path))
    monkeypatch.setattr(ig, "REMOVE_CHROMA_KEY_SCRIPT", str(tmp_path / "nonexistent.py"))

    called = {"codex": False}

    async def _fake_codex_exec(_prompt, **_kw):
        called["codex"] = True
        return ""

    monkeypatch.setattr(ig, "codex_exec", _fake_codex_exec)

    with pytest.raises(ig.ImageGenError) as ei:
        await ig.generate_images("run1", "a mug", white_bg=True, job_id="jobwb")

    assert "脚本缺失" in str(ei.value)
    assert called["codex"] is False  # never reached codex
    assert ei.value.log_url


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
