from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from myskin.settings_loader import cfg_bool, cfg_get, cfg_optional_float, ensure_config_loaded


def _mapping_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _mapping_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    if key not in data or data[key] is None or data[key] == "":
        return default
    return data[key]


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


class SchedulerSettings:
    def __init__(
        self,
        *,
        enabled: bool,
        cron: str,
        interval_hours: float | None,
        interval_minutes: float | None,
        run_on_startup: bool,
        timezone: str,
    ) -> None:
        self.enabled = enabled
        self.cron = cron
        self.interval_hours = interval_hours
        self.interval_minutes = interval_minutes
        self.run_on_startup = run_on_startup
        self.timezone = timezone

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> SchedulerSettings:
        return cls(
            enabled=_mapping_bool(data, "enabled", True),
            cron=str(_mapping_get(data, "cron", "0 2 * * 0")).strip(),
            interval_hours=_optional_float(_mapping_get(data, "interval_hours")),
            interval_minutes=_optional_float(_mapping_get(data, "interval_minutes")),
            run_on_startup=_mapping_bool(data, "run_on_startup", False),
            timezone=str(_mapping_get(data, "timezone", "UTC")),
        )

    @classmethod
    def load_global(cls) -> SchedulerSettings:
        ensure_config_loaded()
        mapping: dict[str, Any] = {}
        for key in (
            "enabled",
            "cron",
            "interval_hours",
            "interval_minutes",
            "run_on_startup",
            "timezone",
        ):
            value = cfg_get(f"scheduler.{key}", default=None)
            if value is not None and value != "":
                mapping[key] = value
        if "enabled" not in mapping:
            mapping["enabled"] = cfg_bool("scheduler.enabled", True)
        return cls.from_mapping(mapping)

    @property
    def mode(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.interval_hours is not None or self.interval_minutes is not None:
            return "interval"
        return "cron"

    @property
    def schedule_description(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.mode == "interval":
            if self.interval_hours is not None:
                return f"every {self.interval_hours}h"
            return f"every {self.interval_minutes}m"
        return f"cron ({self.cron} {self.timezone})"

    @property
    def interval_seconds(self) -> float | None:
        if self.interval_hours is not None:
            return self.interval_hours * 3600
        if self.interval_minutes is not None:
            return self.interval_minutes * 60
        return None

    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {self.timezone}") from exc


scheduler_settings = SchedulerSettings.load_global()
