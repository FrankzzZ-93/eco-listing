"""Low-level async wrapper around the ``browser-act`` CLI.

``browser-act`` (https://www.browseract.com) is a browser-automation CLI for AI
agents. A "browser" in browser-act is a *persistent, isolated environment* — its
own cookies, login state and fingerprint — that survives across invocations
until explicitly deleted. That persistence is exactly how we "remember login
state": we create one named browser once and reuse it for every scrape.

All page-interaction commands take a ``--session <name>`` (a window on the
browser). The interaction loop is: ``browser open`` -> ``state`` -> ``input`` /
``click`` -> ``get markdown`` / ``eval`` -> ``session close``.

This module only exposes thin primitives (run a command, parse output). The
Amazon-specific orchestration (login, review extraction, captcha detection)
lives in :mod:`app.tools.browser_act_scraper`.

Install: ``uv tool install browser-act-cli --python 3.12`` (installs the
``browser-act`` executable, usually into ``~/.local/bin``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _discover_binary() -> str:
    """Locate the ``browser-act`` executable.

    uv installs tools into ``~/.local/bin`` which is frequently absent from a
    service's ``PATH``; probe the common locations so the backend works without
    the operator exporting PATH.
    """
    found = shutil.which("browser-act")
    if found:
        return found
    for candidate in (
        os.path.expanduser("~/.local/bin/browser-act"),
        "/opt/homebrew/bin/browser-act",
        "/usr/local/bin/browser-act",
    ):
        if os.path.exists(candidate):
            return candidate
    return "browser-act"


BROWSER_ACT_BIN = _discover_binary()

# browser-act commands (especially the first one in a process, and anything that
# spins up a Chromium) can be slow. Keep a generous default.
_DEFAULT_TIMEOUT = 180


class BrowserActError(RuntimeError):
    """A ``browser-act`` invocation failed (non-zero exit or missing binary)."""


class BrowserActTimeout(BrowserActError):
    """A ``browser-act`` invocation exceeded its timeout."""


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def json(self) -> Any:
        """Best-effort parse of stdout as JSON. Returns ``None`` on failure."""
        text = self.stdout.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Some commands print a human line before/after the JSON blob; try to
            # recover the largest JSON object/array substring.
            for opener, closer in (("{", "}"), ("[", "]")):
                start = text.find(opener)
                end = text.rfind(closer)
                if start != -1 and end > start:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        continue
            return None


def _kill_tree(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def browser_act_available() -> bool:
    """True when the ``browser-act`` executable is resolvable."""
    return shutil.which(BROWSER_ACT_BIN) is not None or os.path.exists(BROWSER_ACT_BIN)


class BrowserActClient:
    """Stateful client bound to a single persistent browser + session name.

    The client is intentionally cheap to construct and lazily resolves the
    backing browser id on first use, caching it for subsequent calls.
    """

    def __init__(
        self,
        *,
        browser_name: str = "eco_listing",
        browser_desc: str = "Eco Listing — Amazon competitor review scraping (persistent login)",
        session_name: str = "eco_listing",
        browser_type: str = "stealth",
        dynamic_proxy: str = "",
        headed: bool = False,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.browser_name = browser_name
        self.browser_desc = browser_desc
        self.session_name = session_name
        self.browser_type = browser_type
        self.dynamic_proxy = (dynamic_proxy or "").strip()
        self.headed = headed
        self.timeout = timeout
        self._browser_id: Optional[str] = None
        self._opened = False
        # Serialize commands: a single session is one window; concurrent
        # commands against it race on shared page state.
        self._lock = asyncio.Lock()

    # --- low-level command runner ---

    async def _exec(self, args: list[str], *, timeout: Optional[int] = None) -> CmdResult:
        """Run ``browser-act <args>`` and capture stdout/stderr.

        IMPORTANT: stdout/stderr are redirected to temp files rather than pipes.
        browser-act spawns a long-lived background daemon that inherits the
        child's stdio; with ``PIPE`` + ``communicate()`` the read would block on
        EOF forever because the detached daemon keeps the write-end open (this is
        what made the CLI appear to "hang"). We instead wait on ``proc.wait()``
        — which returns as soon as the direct CLI process exits, regardless of
        the daemon — then read the captured files.
        """
        cmd = [BROWSER_ACT_BIN, *args]
        effective_timeout = timeout if timeout is not None else self.timeout
        started = time.monotonic()
        logger.info("browser-act exec: %s", " ".join(args[:6]))

        out_f = tempfile.TemporaryFile()
        err_f = tempfile.TemporaryFile()
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=err_f,
                    env=None,
                    start_new_session=True,
                )
            except FileNotFoundError as e:
                raise BrowserActError(
                    "browser-act CLI not found. Install with: "
                    "uv tool install browser-act-cli --python 3.12"
                ) from e

            try:
                await asyncio.wait_for(proc.wait(), timeout=effective_timeout)
            except asyncio.TimeoutError as e:
                _kill_tree(proc.pid)
                try:
                    await proc.wait()
                except Exception:
                    pass
                raise BrowserActTimeout(
                    f"browser-act timed out after {effective_timeout}s: {' '.join(args[:4])}"
                ) from e

            out_f.seek(0)
            err_f.seek(0)
            stdout_b = out_f.read()
            stderr_b = err_f.read()
        finally:
            out_f.close()
            err_f.close()

        elapsed = time.monotonic() - started
        result = CmdResult(
            returncode=proc.returncode or 0,
            stdout=(stdout_b or b"").decode(errors="replace").strip(),
            stderr=(stderr_b or b"").decode(errors="replace").strip(),
        )
        logger.info(
            "browser-act done rc=%s in %.1fs (%s)",
            result.returncode,
            elapsed,
            args[0] if args else "",
        )
        return result

    async def _session(self, args: list[str], *, timeout: Optional[int] = None) -> CmdResult:
        """Run a session-scoped command, prefixing ``--session`` and JSON format."""
        return await self._exec(
            ["--session", self.session_name, "--format", "json", *args],
            timeout=timeout,
        )

    # --- browser lifecycle ---

    async def list_browsers(self) -> list[dict]:
        res = await self._exec(["--format", "json", "browser", "list"])
        data = res.json()
        if isinstance(data, dict):
            data = data.get("browsers") or data.get("data") or []
        return data if isinstance(data, list) else []

    async def ensure_browser(self) -> str:
        """Return the id of our persistent browser, creating it if missing.

        Creates a managed ``stealth`` browser (anti-detection, captcha-aware)
        rather than driving the operator's local Chrome — so we never close /
        restart their running Chrome. Login is performed fresh through our own
        flow and persists on the browser profile across runs.
        """
        if self._browser_id:
            return self._browser_id

        async with self._lock:
            if self._browser_id:
                return self._browser_id
            for b in await self.list_browsers():
                name = b.get("name") or b.get("browser_name")
                if name == self.browser_name:
                    bid = b.get("id") or b.get("browser_id")
                    if bid:
                        self._browser_id = str(bid)
                        logger.info("browser-act: reusing browser %s (%s)", self.browser_name, bid)
                        return self._browser_id

            create_args = [
                "--format", "json",
                "browser", "create",
                "--name", self.browser_name,
                "--type", self.browser_type,
                "--desc", self.browser_desc,
            ]
            # A dynamic proxy region (e.g. "US") makes the stealth browser exit
            # from that country, so geo-redirects land on the right marketplace
            # and the account's home site is reachable.
            if self.dynamic_proxy:
                create_args += ["--dynamic-proxy", self.dynamic_proxy]
            res = await self._exec(create_args)
            if not res.ok:
                raise BrowserActError(f"browser create failed: {res.stderr or res.stdout}")
            data = res.json() or {}
            bid = (
                data.get("id")
                or data.get("browser_id")
                or (data.get("browser") or {}).get("id")
            )
            if not bid:
                # Fall back to re-listing to find the freshly created browser.
                for b in await self.list_browsers():
                    if (b.get("name") or b.get("browser_name")) == self.browser_name:
                        bid = b.get("id") or b.get("browser_id")
                        break
            if not bid:
                raise BrowserActError(f"could not determine new browser id: {res.stdout}")
            self._browser_id = str(bid)
            logger.info("browser-act: created browser %s (%s)", self.browser_name, bid)
            return self._browser_id

    async def open(self, url: str) -> CmdResult:
        """Open ``url`` in our browser/session (idempotent: navigates if already open)."""
        # Resolve the browser id BEFORE taking the lock: ``ensure_browser`` does
        # its own locking and ``asyncio.Lock`` is not reentrant, so calling it
        # while holding ``self._lock`` would deadlock.
        bid = await self.ensure_browser()
        async with self._lock:
            if self._opened:
                return await self._session(["navigate", url])
            args = ["browser", "open", bid, url]
            if self.headed:
                args.append("--headed")
            res = await self._exec(
                ["--session", self.session_name, "--format", "json", *args],
                timeout=self.timeout,
            )
            if res.ok:
                self._opened = True
            return res

    async def navigate(self, url: str) -> CmdResult:
        # See ``open``: resolve the browser id outside the lock to avoid a
        # re-entrant deadlock on ``self._lock``.
        await self.ensure_browser()
        if not self._opened:
            return await self.open(url)
        async with self._lock:
            return await self._session(["navigate", url])

    async def wait_stable(self, timeout_ms: int = 30000) -> CmdResult:
        async with self._lock:
            return await self._session(["wait", "stable", "--timeout", str(timeout_ms)])

    async def state(self) -> list[dict]:
        """Return interactive elements as a list of dicts (best-effort schema).

        Each element is normalized to ``{"index", "tag", "text"}`` so callers can
        match by tag/text without depending on browser-act's exact JSON keys.
        """
        async with self._lock:
            res = await self._session(["state"])
        return _normalize_elements(res)

    async def screenshot(self, path: str, *, full: bool = False) -> CmdResult:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        async with self._lock:
            args = ["screenshot", path]
            if full:
                args.append("--full")
            return await self._session(args)

    async def get_markdown(self) -> str:
        async with self._lock:
            res = await self._session(["get", "markdown"])
        return _extract_text_payload(res)

    async def get_html(self, selector: Optional[str] = None) -> str:
        async with self._lock:
            args = ["get", "html"]
            if selector:
                args += ["--selector", selector]
            res = await self._session(args)
        return _extract_text_payload(res)

    async def get_title(self) -> str:
        async with self._lock:
            res = await self._session(["get", "title"])
        return _extract_text_payload(res)

    async def eval_js(self, js: str, *, timeout: Optional[int] = None) -> Any:
        """Execute JavaScript in the page; return the parsed result value."""
        async with self._lock:
            res = await self._session(["eval", js], timeout=timeout)
        data = res.json()
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data if data is not None else res.stdout

    async def input(self, index: int, text: str) -> CmdResult:
        async with self._lock:
            return await self._session(["input", str(index), text])

    async def click(self, index: int) -> CmdResult:
        async with self._lock:
            return await self._session(["click", str(index)])

    async def keys(self, combo: str) -> CmdResult:
        async with self._lock:
            return await self._session(["keys", combo])

    async def solve_captcha(self) -> CmdResult:
        """Attempt browser-act's automated captcha solver (needs an API key)."""
        async with self._lock:
            return await self._session(["solve-captcha"])

    async def close_session(self) -> None:
        async with self._lock:
            if not self._opened:
                return
            try:
                await self._exec(["session", "close", self.session_name])
            except BrowserActError:
                logger.warning("browser-act session close failed", exc_info=True)
            finally:
                self._opened = False


_ELEMENT_TOKEN = re.compile(r"\[(\d+)\]<([^>]*?)/?>")


def _normalize_elements(res: CmdResult) -> list[dict]:
    """Normalize ``state`` output into ``[{index, tag, text, attrs}]``.

    browser-act returns ``{"ok","url","title","text"}`` where ``text`` is an
    indexed accessibility tree, e.g.::

        [4]<input type=email id=ap_email_login name=email aria-label=... />
        [5]<span id=continue />
        ...
            Continue

    Each interactive node is ``[N]<tag attr=val ... />`` followed by its visible
    label on the lines until the next ``[M]`` token. We parse the index, tag,
    the raw attribute string (so callers can match by ``id``/``type``/etc.) and
    the trailing label text.
    """
    data = res.json()
    tree: Optional[str] = None
    if isinstance(data, dict):
        for key in ("text", "elements", "snapshot", "tree"):
            val = data.get(key)
            if isinstance(val, str):
                tree = val
                break
    if tree is None:
        tree = res.stdout

    elements: list[dict] = []
    matches = list(_ELEMENT_TOKEN.finditer(tree))
    for i, m in enumerate(matches):
        inner = m.group(2).strip()
        if not inner:
            continue
        bits = inner.split(None, 1)
        tag = bits[0]
        attrs = bits[1].strip() if len(bits) > 1 else ""
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(tree)
        label = re.sub(r"\s+", " ", tree[start:end]).strip()
        try:
            elements.append(
                {"index": int(m.group(1)), "tag": tag, "text": label, "attrs": attrs}
            )
        except (TypeError, ValueError):
            continue
    return elements


def _extract_text_payload(res: CmdResult) -> str:
    """Pull the textual payload out of a JSON-or-text command result."""
    data = res.json()
    if isinstance(data, dict):
        for key in ("markdown", "html", "text", "title", "content", "result", "value"):
            if key in data and isinstance(data[key], str):
                return data[key]
    elif isinstance(data, str):
        return data
    return res.stdout
