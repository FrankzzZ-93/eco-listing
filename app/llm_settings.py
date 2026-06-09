"""Global, UI-configurable LLM settings for listing copywriting.

The listing copywriter can run on two backends:

- ``codex-cli`` (default): the local Codex CLI, using the locally logged-in
  account (existing behavior, no config required).
- ``openai_compatible``: any OpenAI-compatible HTTP endpoint (e.g. a relay
  station / 中转站 serving Opus/Claude/other models), configured with a base
  URL ("request path"), API key, and model id.

Settings are persisted to ``llm_settings.json`` (atomic write) and read at
runtime so changes take effect without a server restart.
"""
from __future__ import annotations

import os
import json
import tempfile
from typing import Any

_SETTINGS_FILE = "llm_settings.json"

PROVIDER_CODEX = "codex-cli"
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
VALID_PROVIDERS = (PROVIDER_CODEX, PROVIDER_OPENAI_COMPATIBLE)

_DEFAULT_CONFIG: dict[str, Any] = {
    "provider": PROVIDER_CODEX,
    "base_url": "",
    "api_key": "",
    "model": "",
}

# In-memory cache of the persisted config.
_config: dict[str, Any] | None = None


def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    if isinstance(raw, dict):
        for key in _DEFAULT_CONFIG:
            if key in raw and raw[key] is not None:
                cfg[key] = raw[key]
    if cfg.get("provider") not in VALID_PROVIDERS:
        cfg["provider"] = PROVIDER_CODEX
    return cfg


def load_llm_settings() -> dict[str, Any]:
    """Load settings from disk into the in-memory cache. Idempotent."""
    global _config
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                _config = _normalize(json.load(f))
        except (json.JSONDecodeError, OSError):
            _config = dict(_DEFAULT_CONFIG)
    else:
        _config = dict(_DEFAULT_CONFIG)
    return _config


def get_listing_llm_config() -> dict[str, Any]:
    """Return the current listing copywriter LLM config (cached)."""
    if _config is None:
        load_llm_settings()
    return dict(_config)  # type: ignore[arg-type]


def save_llm_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate, persist (atomically) and cache the given config."""
    global _config
    normalized = _normalize(cfg)
    _atomic_write(normalized)
    _config = normalized
    return dict(normalized)


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


def is_configured(cfg: dict[str, Any]) -> bool:
    """True when the config is a usable OpenAI-compatible backend."""
    if cfg.get("provider") != PROVIDER_OPENAI_COMPATIBLE:
        return False
    return bool(cfg.get("base_url")) and bool(cfg.get("api_key")) and bool(cfg.get("model"))


def public_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """Mask the API key for safe transport to the frontend."""
    api_key = cfg.get("api_key") or ""
    return {
        "provider": cfg.get("provider", PROVIDER_CODEX),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "api_key_set": bool(api_key),
        "api_key_hint": (f"****{api_key[-4:]}" if len(api_key) >= 4 else ("****" if api_key else "")),
    }
