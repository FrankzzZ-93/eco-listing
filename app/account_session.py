"""Account login session manager for the browser-act review scraper.

Establishes and remembers an authenticated Amazon session, independent of any
run. Login runs as a background task; if it hits a captcha / OTP the manager
exposes a ``waiting_captcha`` state with a screenshot URL so the settings page
can pop the same captcha modal used by runs. On success the browser-act browser
profile persists the cookies, so subsequent scrape runs reuse the login.

Uses a dedicated browser-act session name (``eco_listing_login``) on the same
persistent browser as scraping (``eco_listing``); browser-act sessions on one
browser share login state, so logging in here authenticates the scrape session
too.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Optional

from app import app_settings
from app.config import settings
from app.errors import CaptchaRequiredError, LoginRequiredError
from app.tools.browser_act_scraper import LoginManager
from app.tools.file_store import to_artifact_url

logger = logging.getLogger(__name__)

# States: idle | logging_in | waiting_captcha | logged_in | failed | unavailable
_state: dict[str, Any] = {
    "state": "idle",
    "message": "",
    "image_url": "",
    "updated_at": "",
}

_manager: Optional[LoginManager] = None
_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()

_ACCOUNT_DIR_NAME = "_account"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _set(state: str, message: str = "", image_url: str = "") -> None:
    _state.update(
        {"state": state, "message": message, "image_url": image_url, "updated_at": _now()}
    )
    logger.info("account_session state -> %s (%s)", state, message)


def _get_manager() -> LoginManager:
    global _manager
    if _manager is None:
        headed = not app_settings.get_scrape_param("browser_headless", True)
        proxy_region = app_settings.get_account().get("proxy_region", "")
        _manager = LoginManager(headed=headed, proxy_region=proxy_region)
    return _manager


def _screenshot_dir() -> str:
    d = os.path.join(settings.artifacts_dir, _ACCOUNT_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def get_status() -> dict[str, Any]:
    return {
        "available": LoginManager.available(),
        "state": _state["state"],
        "message": _state["message"],
        "image_url": _state["image_url"],
        "updated_at": _state["updated_at"],
        "account_email": app_settings.get_account().get("email", ""),
    }


async def _do_login() -> None:
    account = app_settings.get_account()
    site = account.get("site") or "amazon.com"
    email = account.get("email") or ""
    password = account.get("password") or ""
    manager = _get_manager()
    try:
        _set("logging_in", "正在登录…")
        ok = await manager.login(
            site, email, password, screenshot_dir=_screenshot_dir()
        )
        if ok:
            _set("logged_in", "登录成功，已记住登录态")
        else:
            _set("failed", "登录未成功，请检查账号或重试")
    except CaptchaRequiredError as e:
        _set("waiting_captcha", str(e), to_artifact_url(e.image_path))
    except LoginRequiredError as e:
        _set("failed", str(e))
    except Exception as e:
        logger.warning("account login failed", exc_info=True)
        _set("failed", f"登录出错: {e}")


async def start_login() -> dict[str, Any]:
    if not LoginManager.available():
        _set("unavailable", "browser-act 未安装")
        return get_status()
    async with _lock:
        global _task
        if _task is not None and not _task.done():
            return get_status()
        _task = asyncio.create_task(_do_login())
    return get_status()


async def submit_captcha(answer: str) -> dict[str, Any]:
    if _state["state"] != "waiting_captcha":
        return get_status()
    manager = _get_manager()
    _set("logging_in", "正在校验…")
    try:
        cleared = await manager.submit_verification(answer)
        site = app_settings.get_account().get("site") or "amazon.com"
        logged_in = await manager.is_logged_in(site)
        if logged_in:
            _set("logged_in", "登录成功，已记住登录态")
        elif cleared:
            _set("failed", "验证已通过但登录未完成，请重试登录")
        else:
            # Challenge still present (e.g. wrong captcha) — capture again.
            img = os.path.join(_screenshot_dir(), "login_verify.png")
            await manager.capture_screenshot(img)
            _set("waiting_captcha", "验证未通过，请重新输入", to_artifact_url(img))
    except Exception as e:
        logger.warning("account captcha submit failed", exc_info=True)
        _set("failed", f"校验出错: {e}")
    return get_status()


async def refresh_status() -> dict[str, Any]:
    """Probe whether the persistent session is currently logged in."""
    if not LoginManager.available():
        _set("unavailable", "browser-act 未安装")
        return get_status()
    if _state["state"] in ("logging_in", "waiting_captcha"):
        return get_status()
    site = app_settings.get_account().get("site") or "amazon.com"
    try:
        if await _get_manager().is_logged_in(site):
            _set("logged_in", "已登录")
        else:
            _set("idle", "未登录")
    except Exception as e:
        logger.warning("refresh_status failed", exc_info=True)
        _set("idle", f"无法检测登录态: {e}")
    return get_status()


async def logout() -> dict[str, Any]:
    manager = _get_manager()
    try:
        await manager.close()
    except Exception:
        pass
    _set("idle", "已退出当前会话窗口")
    return get_status()
