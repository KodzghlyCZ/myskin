from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from myskin.crawler.state import CrawlStats


@dataclass(frozen=True)
class LiveSample:
    elapsed_s: float
    queue: int
    discovered: int
    processed: int


@dataclass(frozen=True)
class LiveEvent:
    at: datetime
    kind: str
    outcome: str
    label: str
    url: str


@dataclass
class CrawlLiveMonitor:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    active: bool = False
    run_id: int | None = None
    seed_url: str = ""
    trigger: str = ""
    max_pages: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_pending: int = 0
    stats: CrawlStats = field(default_factory=CrawlStats)
    samples: deque[LiveSample] = field(default_factory=lambda: deque(maxlen=5000))
    events: deque[LiveEvent] = field(default_factory=lambda: deque(maxlen=150))

    def start(
        self,
        *,
        run_id: int,
        seed_url: str,
        queue_size: int,
        max_pages: int,
        trigger: str = "",
        initial_stats: CrawlStats | None = None,
    ) -> None:
        with self._lock:
            self.active = True
            self.run_id = run_id
            self.seed_url = seed_url
            self.trigger = trigger
            self.max_pages = max_pages
            self.started_at = datetime.now(timezone.utc)
            self.finished_at = None
            self.queue_pending = queue_size
            self.stats = initial_stats if initial_stats is not None else CrawlStats()
            self.samples.clear()
            self.events.clear()
            self._append_sample_locked()

    def set_queue_pending(self, pending: int) -> None:
        with self._lock:
            if not self.active:
                return
            self.queue_pending = pending
            self._append_sample_locked()

    def record(
        self,
        *,
        kind: str,
        outcome: str,
        label: str,
        url: str,
        stats: CrawlStats,
    ) -> None:
        with self._lock:
            if not self.active:
                return
            self.stats = stats
            self.events.append(
                LiveEvent(
                    at=datetime.now(timezone.utc),
                    kind=kind,
                    outcome=outcome,
                    label=label,
                    url=url,
                )
            )
            self._append_sample_locked()

    def finish(self, stats: CrawlStats) -> None:
        with self._lock:
            if not self.active:
                return
            self.stats = stats
            self.queue_pending = 0
            self.finished_at = datetime.now(timezone.utc)
            self._append_sample_locked()
            self.active = False

    def abort(self) -> None:
        with self._lock:
            if not self.active:
                return
            self.finished_at = datetime.now(timezone.utc)
            self.active = False

    def attach_trigger(self, trigger: str) -> None:
        with self._lock:
            self.trigger = trigger

    def _elapsed_s_locked(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    def _processed_locked(self) -> int:
        return self.stats.pages_fetched + self.stats.pdfs_fetched

    def _append_sample_locked(self) -> None:
        self.samples.append(
            LiveSample(
                elapsed_s=round(self._elapsed_s_locked(), 1),
                queue=self.queue_pending,
                discovered=self.stats.discovered,
                processed=self._processed_locked(),
            )
        )

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "active": self.active,
                "run_id": self.run_id,
                "seed_url": self.seed_url,
                "trigger": self.trigger,
                "max_pages": self.max_pages,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "queue_pending": self.queue_pending,
                "stats": self.stats,
                "samples": list(self.samples),
                "events": list(self.events),
            }


crawl_live = CrawlLiveMonitor()
