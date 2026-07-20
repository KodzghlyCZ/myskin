from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SiteRecord:
    site_id: str
    name: str
    enabled: bool
    public_base_url: str
    crawler: dict[str, Any] = field(default_factory=dict)
    scheduler: dict[str, Any] = field(default_factory=dict)
    ragflow: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def seed_url(self) -> str:
        return str(self.crawler.get("seed_url", "")).strip()
