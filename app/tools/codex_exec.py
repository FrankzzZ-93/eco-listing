"""Shared low-level Codex CLI runner.

Single source of truth for `codex exec` invocation across the codebase.
Both ``LLMTool`` (text generation) and ``CodexTool`` (browser automation) wrap
the same external binary, so they MUST share the same subprocess plumbing and
the same timeout knob — controlled exclusively via ``settings.codex_timeout``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from typing import Callable, Optional

from app.config import settings
from app.tools import codex_progress

logger = logging.getLogger(__name__)

CODEX_BIN = shutil.which("codex") or "codex"

# StreamReader buffer ceiling for stdout/stderr lines. The default is 64 KB,
# but codex CLI's `--json` mode emits one JSON event per line and a single
# event (e.g. a long agent_message or reasoning blob) can easily exceed that
# — keyword classification routinely produces ~10K-token (~40-80 KB) outputs.
# 10 MB is comfortable headroom; if a line still exceeds it we degrade
# gracefully via try/except in ``_drain``.
_STREAM_LIMIT = 10 * 1024 * 1024


class CodexExecError(RuntimeError):
    """Base error for any failure of a `codex exec` invocation."""


class CodexExecTimeout(CodexExecError):
    """Raised when `codex exec` exceeds the configured timeout."""


def _kill_process_tree(pid: int) -> None:
    """SIGKILL the entire POSIX process group rooted at ``pid``.

    The codex CLI shipped via npm is a node wrapper that fork-execs the real
    Rust binary as a grandchild. Killing the immediate child only kills node
    and orphans the Rust process (which keeps consuming the LLM API). We
    spawn the subprocess in a fresh session via ``start_new_session=True``,
    making ``pid`` the leader of its own process group; ``killpg`` then
    SIGKILLs every descendant in one shot.
    """
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        # Group already gone — nothing to do.
        pass
    except PermissionError:
        # Shouldn't happen for our own children, but degrade gracefully.
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def _drain(
    stream: asyncio.StreamReader,
    sink: list[bytes],
    on_line: Optional[Callable[[bytes], None]] = None,
) -> None:
    """Read ``stream`` line-by-line into ``sink`` until EOF.

    Running stdout and stderr drains concurrently is required so a chatty
    side can't fill its pipe and deadlock the subprocess.

    If a single line exceeds the StreamReader buffer limit, ``readline()``
    raises ``ValueError`` and discards that line's content, but the buffer
    is advanced past the separator — so we just log and keep reading the
    next line, never letting one giant blob kill the whole subprocess.
    """
    while True:
        try:
            line = await stream.readline()
        except ValueError as e:
            logger.warning(
                "codex_exec drain: oversized line dropped (limit=%d B): %s",
                _STREAM_LIMIT,
                e,
            )
            continue
        if not line:
            return
        sink.append(line)
        if on_line is not None:
            try:
                on_line(line)
            except Exception:
                # Never let progress instrumentation break the read loop.
                logger.debug("codex_exec on_line callback failed", exc_info=True)


def _make_progress_callback(run_id: Optional[str]) -> Optional[Callable[[bytes], None]]:
    """Build a per-line callback that updates the progress sidecar.

    Returns ``None`` when no ``run_id`` is in context (e.g. tests calling
    ``codex_exec`` directly), so the read loop skips the parse work entirely.
    """
    if run_id is None:
        return None

    def _on_line(raw: bytes) -> None:
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(obj, dict):
            return
        evt_type = obj.get("type")
        if evt_type == "item.started":
            item = obj.get("item") or {}
            item_type = item.get("type") or "unknown"
            codex_progress.set_event_type(run_id, item_type)
            logger.info("codex_exec[%s] item.started: %s", run_id, item_type)
        elif evt_type == "item.completed":
            codex_progress.inc_completed(run_id)

    return _on_line


async def codex_exec(prompt: str, *, timeout: int | None = None) -> str:
    """Run a single `codex exec --json --ephemeral --ignore-rules <prompt>`.

    Streams stdout line-by-line so the progress sidecar
    (``app.tools.codex_progress``) can publish per-event updates while the
    subprocess is still running. The full stdout is buffered and returned at
    the end so existing JSONL parsers in callers stay unchanged.

    Args:
        prompt: The prompt to send to Codex.
        timeout: Optional override (seconds). Defaults to ``settings.codex_timeout``.
            Callers should normally NOT pass this; the global setting is the
            single source of truth.

    Returns:
        The raw stdout (JSONL) from the subprocess, decoded as UTF-8.

    Raises:
        CodexExecTimeout: subprocess didn't finish in ``timeout`` seconds.
        CodexExecError: binary missing or subprocess returned a non-zero code.
    """
    effective_timeout = timeout if timeout is not None else settings.codex_timeout
    prompt_bytes = len(prompt.encode("utf-8"))

    cmd = [
        CODEX_BIN,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-rules",
        prompt,
    ]

    logger.info(
        "codex_exec start (timeout=%ss, prompt=%d bytes): %s...",
        effective_timeout,
        prompt_bytes,
        prompt[:120],
    )

    started = time.monotonic()
    run_id = codex_progress.current_run_id.get()
    if run_id is not None:
        codex_progress.start(run_id)

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=None,  # inherit; codex CLI uses its own auth in ~/.codex/
                start_new_session=True,  # detach so we can SIGKILL the whole group
                limit=_STREAM_LIMIT,  # codex JSONL events can far exceed the 64 KB default
            )
        except FileNotFoundError as e:
            raise CodexExecError(
                "Codex CLI binary not found. Install with: npm install -g @openai/codex"
            ) from e

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        on_stdout = _make_progress_callback(run_id)

        # Drain both pipes and wait for the process concurrently. If any
        # task raises, ``gather`` cancels the rest, so we wrap the whole
        # group in ``wait_for`` to enforce the hard timeout.
        gather = asyncio.gather(
            _drain(proc.stdout, stdout_chunks, on_stdout),
            _drain(proc.stderr, stderr_chunks),
            proc.wait(),
        )
        try:
            await asyncio.wait_for(gather, timeout=effective_timeout)
        except asyncio.TimeoutError as e:
            elapsed = time.monotonic() - started
            # Kill the whole process group: the codex npm shim is a node
            # wrapper that spawns the real Rust binary as a grandchild.
            # proc.kill() alone only kills node and orphans the Rust
            # process, which keeps running.
            _kill_process_tree(proc.pid)
            # Reap our immediate child so we don't leak a zombie. Also let
            # the cancelled drain tasks finish unwinding.
            try:
                await proc.wait()
            except Exception:
                pass
            try:
                await asyncio.gather(gather, return_exceptions=True)
            except Exception:
                pass
            logger.error(
                "codex_exec TIMEOUT after %.1fs (limit=%ss, prompt=%d bytes); "
                "consider raising CODEX_TIMEOUT or splitting the prompt.",
                elapsed,
                effective_timeout,
                prompt_bytes,
            )
            raise CodexExecTimeout(
                f"Codex exec timed out after {effective_timeout}s"
            ) from e

        elapsed = time.monotonic() - started
        stdout_bytes = b"".join(stdout_chunks)
        stderr_bytes = b"".join(stderr_chunks)

        if proc.returncode != 0:
            err_msg = stderr_bytes.decode(errors="replace").strip()
            logger.error(
                "codex_exec FAIL rc=%s after %.1fs: %s",
                proc.returncode,
                elapsed,
                err_msg[:300],
            )
            raise CodexExecError(
                f"Codex exec failed (rc={proc.returncode}): {err_msg}"
            )

        out = stdout_bytes.decode(errors="replace").strip()
        logger.info(
            "codex_exec done in %.1fs (prompt=%d B, stdout=%d B)",
            elapsed,
            prompt_bytes,
            len(out),
        )
        return out
    finally:
        if run_id is not None:
            codex_progress.clear(run_id)
