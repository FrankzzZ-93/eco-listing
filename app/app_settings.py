"""Unified, UI-configurable application settings (the single config entry).

Consolidates the previously scattered configuration into one place that the
homepage config entry edits:

- **account**: the Amazon login used by the browser-act review scraper
  (``site`` / ``email`` / ``password``). Persisted locally so the login session
  can be (re)established and remembered.
- **scrape**: knobs that used to be ``.env``-only in :mod:`app.config`
  (``browser_headless``, ``scrape_max_review_pages``, ``research_concurrency``,
  ``codex_timeout``). Values here override the ``.env`` defaults at runtime.
- **review_engine**: which scraper handles competitor reviews
  (``browser_act`` = logged-in browser-act, ``builtin`` = Playwright+Codex).

Settings persist to ``app_settings.json`` (atomic write) and are read at runtime
so changes take effect without a server restart. Secrets are masked in
:func:`public_view` before being sent to the frontend.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.config import settings as env_settings

_SETTINGS_FILE = "app_settings.json"

ENGINE_BROWSER_ACT = "browser_act"
ENGINE_BUILTIN = "builtin"
VALID_ENGINES = (ENGINE_BROWSER_ACT, ENGINE_BUILTIN)


def _defaults() -> dict[str, Any]:
    return {
        "account": {
            "site": "amazon.com",
            "email": "",
            "password": "",
            # Optional stealth-browser exit region (e.g. "US"). Empty = no proxy
            # (use the host's own IP). Set this when the host IP geo-redirects to
            # the wrong marketplace for the account.
            "proxy_region": "",
        },
        "scrape": {
            "browser_headless": env_settings.browser_headless,
            "scrape_max_review_pages": env_settings.scrape_max_review_pages,
            "research_concurrency": env_settings.research_concurrency,
            "codex_timeout": env_settings.codex_timeout,
        },
        "review_engine": ENGINE_BROWSER_ACT,
    }


_config: dict[str, Any] | None = None


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = _defaults()
    if isinstance(raw, dict):
        acct = raw.get("account")
        if isinstance(acct, dict):
            for k in ("site", "email", "password", "proxy_region"):
                if isinstance(acct.get(k), str):
                    cfg["account"][k] = acct[k]
        scrape = raw.get("scrape")
        if isinstance(scrape, dict):
            if isinstance(scrape.get("browser_headless"), bool):
                cfg["scrape"]["browser_headless"] = scrape["browser_headless"]
            for k in ("scrape_max_review_pages", "research_concurrency", "codex_timeout"):
                v = scrape.get(k)
                if isinstance(v, int) and v > 0:
                    cfg["scrape"][k] = v
        engine = raw.get("review_engine")
        if engine in VALID_ENGINES:
            cfg["review_engine"] = engine
    if not cfg["account"]["site"]:
        cfg["account"]["site"] = "amazon.com"
    return cfg


def load_app_settings() -> dict[str, Any]:
    global _config
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                _config = _normalize(json.load(f))
        except (json.JSONDecodeError, OSError):
            _config = _defaults()
    else:
        _config = _defaults()
    return _config


def get_app_settings() -> dict[str, Any]:
    if _config is None:
        load_app_settings()
    return json.loads(json.dumps(_config))  # deep copy


def save_app_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    global _config
    normalized = _normalize(cfg)
    _atomic_write(normalized)
    _config = normalized
    return json.loads(json.dumps(normalized))


def _atomic_write(cfg: dict[str, Any]) -> None:
    dir_name = os.path.dirname(os.path.abspath(_SETTINGS_FILE))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _SETTINGS_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# --- convenience accessors (read at runtime by scrapers / research node) ---


def get_account() -> dict[str, str]:
    return get_app_settings()["account"]


def get_review_engine() -> str:
    return get_app_settings()["review_engine"]


def get_scrape_param(name: str, default: Any = None) -> Any:
    return get_app_settings()["scrape"].get(name, default)


def public_view(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mask the account password for safe transport to the frontend."""
    cfg = cfg or get_app_settings()
    pwd = cfg["account"].get("password") or ""
    return {
        "account": {
            "site": cfg["account"].get("site", "amazon.com"),
            "email": cfg["account"].get("email", ""),
            "password_set": bool(pwd),
            "proxy_region": cfg["account"].get("proxy_region", ""),
        },
        "scrape": dict(cfg["scrape"]),
        "review_engine": cfg.get("review_engine", ENGINE_BROWSER_ACT),
    }
