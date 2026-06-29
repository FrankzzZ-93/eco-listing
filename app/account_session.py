"""Amazon account session manager — manual login in the real-Chrome window.

The optimized login flow (replaces the old scripted browser-act form-fill):
open the persistent real Chrome (headed) at Amazon and let the user sign in
*themselves* in that window. Amazon blocks scripted form-fills on the auth pages
(verified in a live spike: ``ERR_BLOCKED_BY_RESPONSE``), so scripting login is
both fragile and pointless — and doing it manually means the backend never
handles the password. We only *detect* success. The login persists in the Chrome
profile (``settings.chrome_profile_dir``) so every later scrape reuses it.

State machine: ``idle → opening → waiting_manual → logged_in`` (or ``failed`` /
``unavailable``). The frontend opens the window, the user logs in (incl. any
captcha/OTP, right there in the real browser), then clicks "我已登录" which
re-checks the session.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Optional

from app import app_settings
from app.config import settings
from app.errors import LoginRequiredError
from app.tools.chrome_session import LoginManager

logger = logging.getLogger(__name__)

# idle | opening | waiting_manual | logged_in | failed | unavailable
_state: dict[str, Any] = {
    "state": "idle",
    "message": "",
    "image_url": "",  # kept for response-shape compat; always "" (no captcha modal)
    "updated_at": "",
}

_manager: Optional[LoginManager] = None
_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()

# Persist the logged-in flag to disk so it survives backend restarts. The status
# poll never touches the browser (would pop Chrome), so without this the UI would
# forget the login on every reload. Lazily verified — a stale flag is corrected
# when a scrape hits the login wall.
_LOGIN_MARKER = os.path.join(settings.chrome_profile_dir, ".eco_logged_in")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _persist_logged_in(on: bool) -> None:
    try:
        if on:
            os.makedirs(settings.chrome_profile_dir, exist_ok=True)
            open(_LOGIN_MARKER, "w").close()
        elif os.path.exists(_LOGIN_MARKER):
            os.remove(_LOGIN_MARKER)
    except Exception:
        logger.debug("persist login marker failed", exc_info=True)


def _restore_marker() -> None:
    """If idle but a persisted login flag exists (e.g. after a restart), surface
    it as logged-in. Reconciles on each status read; once it flips to logged_in
    the state is no longer idle, so it won't re-fire (until an explicit logout)."""
    if _state["state"] == "idle" and os.path.exists(_LOGIN_MARKER):
        _set("logged_in", "已登录（已记住登录态）")


def _set(state: str, message: str = "") -> None:
    _state.update({"state": state, "message": message, "image_url": "", "updated_at": _now()})
    _persist_logged_in(state == "logged_in")
    logger.info("account_session state -> %s (%s)", state, message)


def _get_manager() -> LoginManager:
    global _manager
    if _manager is None:
        _manager = LoginManager()
    return _manager


def _site() -> str:
    return app_settings.get_account().get("site") or "amazon.com"


def get_status() -> dict[str, Any]:
    _restore_marker()
    return {
        "available": LoginManager.available(),
        "state": _state["state"],
        "message": _state["message"],
        "image_url": _state["image_url"],
        "updated_at": _state["updated_at"],
        "account_email": app_settings.get_account().get("email", ""),
    }


async def _do_open() -> None:
    """Open the headed Chrome at Amazon so the user can sign in manually."""
    try:
        _set("opening", "正在打开浏览器…")
        if await _get_manager().is_logged_in(_site()):
            _set("logged_in", "已登录，登录态有效")
            return
        await _get_manager().open_for_login(_site())
        _set(
            "waiting_manual",
            "已打开 Chrome 窗口，请在窗口中登录你的 Amazon 账号（含验证码/二次验证），"
            "完成后点「我已登录」",
        )
    except LoginRequiredError as e:
        _set("failed", str(e))
    except Exception as e:  # noqa: BLE001 — surface any launch error to the UI
        logger.warning("open login window failed", exc_info=True)
        _set("failed", f"打开登录窗口出错: {e}")


async def start_login() -> dict[str, Any]:
    if not LoginManager.available():
        _set("unavailable", "未找到本机 Google Chrome，无法打开登录窗口")
        return get_status()
    async with _lock:
        global _task
        if _task is not None and not _task.done():
            return get_status()
        _task = asyncio.create_task(_do_open())
    return get_status()


async def confirm_login() -> dict[str, Any]:
    """User clicked 我已登录 — verify the window is actually signed in."""
    if not LoginManager.available():
        _set("unavailable", "未找到本机 Google Chrome")
        return get_status()
    try:
        if await _get_manager().is_logged_in(_site()):
            _set("logged_in", "登录成功，已记住登录态")
        else:
            _set("waiting_manual", "还没检测到登录，请在窗口里完成登录后再点「我已登录」")
    except Exception as e:  # noqa: BLE001
        logger.warning("confirm_login failed", exc_info=True)
        _set("failed", f"检测登录态出错: {e}")
    return get_status()


# Back-compat: the ``/account/captcha`` endpoint historically submitted a captcha
# answer. With manual login there is nothing to type back — the user solves any
# challenge in the real window — so this just re-checks the session.
async def submit_captcha(answer: str = "") -> dict[str, Any]:  # noqa: ARG001
    return await confirm_login()


async def refresh_status() -> dict[str, Any]:
    """Report the cached login state — **never touches the browser**.

    The settings page polls this on every load/refresh, so launching *or even
    navigating/focusing* Chrome here would pop the window on each refresh. The
    real login check runs only on the explicit "打开浏览器登录" / "我已登录"
    actions (which the user takes deliberately, after the VPN reminder).
    """
    if not LoginManager.available():
        _set("unavailable", "未找到本机 Google Chrome")
    return get_status()


async def logout() -> dict[str, Any]:
    try:
        await _get_manager().close()
    except Exception:
        logger.debug("logout close failed", exc_info=True)
    _set("idle", "已关闭浏览器会话")
    return get_status()
