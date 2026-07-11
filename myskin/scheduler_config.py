from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from myskin.settings_loader import cfg_bool, cfg_get, cfg_optional_float, ensure_config_loaded


class SchedulerSettings:
    def __init__(self) -> None:
        ensure_config_loaded()
        self.enabled: bool = cfg_bool("scheduler.enabled", True)
        self.cron: str = str(cfg_get("scheduler.cron", default="0 2 * * 0")).strip()
        self.interval_hours: float | None = cfg_optional_float("scheduler.interval_hours")
        self.interval_minutes: float | None = cfg_optional_float("scheduler.interval_minutes")
        self.run_on_startup: bool = cfg_bool("scheduler.run_on_startup", False)
        self.timezone: str = str(cfg_get("scheduler.timezone", default="UTC"))

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


scheduler_settings = SchedulerSettings()
