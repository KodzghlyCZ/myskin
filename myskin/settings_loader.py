from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from yayaya import contains, get, init

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOADED = False


def project_root() -> Path:
    return _PROJECT_ROOT


def _resolve_paths() -> list[str]:
    explicit = os.environ.get("MYSKIN_CONFIG_FILES", "").strip()
    if explicit:
        paths: list[Path] = []
        for raw in explicit.split(","):
            entry = raw.strip()
            if not entry:
                continue
            path = Path(entry)
            paths.append(path if path.is_absolute() else _PROJECT_ROOT / path)
        return [str(p) for p in paths]

    paths = [_PROJECT_ROOT / "config.yaml"]
    local_overlay = _PROJECT_ROOT / "config.local.yaml"
    if local_overlay.is_file():
        paths.append(local_overlay)
    return [str(p) for p in paths]


def ensure_config_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    paths = _resolve_paths()
    if not paths:
        raise FileNotFoundError("No myskin config files configured")
    if not Path(paths[0]).is_file():
        raise FileNotFoundError(f"myskin config not found: {paths[0]}")
    init(paths)
    _LOADED = True


class SecretSettings(BaseSettings):
    """Sensitive values only — loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_prefix="MYSKIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_token: str = ""
    ragflow_api_key: str = ""


@lru_cache
def secrets() -> SecretSettings:
    return SecretSettings()


def cfg_optional(path: str):
    """Return a config value when the key exists; None when absent or empty."""
    ensure_config_loaded()
    if not contains(path):
        return None
    value = get(path, default=None)
    if value is None or value == "":
        return None
    return value


def cfg_get(path: str, default=None, *, required: bool = False):
    ensure_config_loaded()
    return get(path, default=default, required=required)


def cfg_bool(path: str, default: bool) -> bool:
    value = cfg_get(path, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def cfg_optional_float(path: str) -> float | None:
    ensure_config_loaded()
    if not contains(path):
        return None
    value = get(path, default=None)
    if value is None or value == "":
        return None
    return float(value)


def cfg_path(path: str, default: str) -> Path:
    return Path(cfg_get(path, default=default))
