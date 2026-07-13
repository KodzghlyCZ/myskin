from __future__ import annotations

import os
import shutil
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from myskin.crawler.config import crawl_settings
from myskin.crawler.live import LiveQueueItem, crawl_live
from myskin.crawler.state import CrawlStats


@dataclass(frozen=True)
class CrawlEvent:
    kind: str
    outcome: str
    label: str


_OUTCOME_MARK = {
    "updated": "✓",
    "unchanged": "·",
    "failed": "✗",
    "blocked": "⊘",
    "skipped": "−",
}


def _progress_mode() -> str:
    raw = crawl_settings.progress.strip().lower()
    if raw in ("off", "false", "0", "no"):
        return "off"
    if raw in ("tty", "ui", "screen"):
        return "tty"
    if raw in ("log", "plain", "lines"):
        return "log"
    return "auto"


def _resolve_mode() -> str:
    mode = _progress_mode()
    if mode == "auto":
        return "log"
    return mode


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 1] + "…"


def _bar(ratio: float, width: int) -> str:
    width = max(10, width)
    filled = int(ratio * width)
    filled = min(width, max(0, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


@dataclass
class CrawlProgressDisplay:
    mode: str = field(default_factory=_resolve_mode)
    _started_at: datetime | None = None
    _run_id: int | None = None
    _seed_url: str = ""
    _max_pages: int = 0
    _queue_pending: int = 0
    _stats: CrawlStats = field(default_factory=CrawlStats)
    _events: deque[CrawlEvent] = field(default_factory=lambda: deque(maxlen=200))
    _active: bool = False
    _last_log_emit: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def uses_tty(self) -> bool:
        return self.mode == "tty"

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
        crawl_live.start(
            run_id=run_id,
            seed_url=seed_url,
            queue_size=queue_size,
            max_pages=max_pages,
            trigger=trigger,
            initial_stats=initial_stats,
        )
        if not self.enabled:
            return
        self._active = True
        self._started_at = datetime.now(timezone.utc)
        self._run_id = run_id
        self._seed_url = seed_url
        self._max_pages = max_pages
        self._queue_pending = queue_size
        self._stats = initial_stats if initial_stats is not None else CrawlStats()
        self._events.clear()
        if self.uses_tty:
            sys.stderr.write("\033[?25l")
            sys.stderr.flush()
        self._render(force=True)

    def set_queue_pending(
        self,
        pending: int,
        *,
        tail: list[LiveQueueItem] | None = None,
    ) -> None:
        crawl_live.set_queue_pending(pending, tail=tail)
        if not self._active:
            return
        self._queue_pending = pending

    def record(
        self,
        *,
        kind: str,
        outcome: str,
        label: str,
        url: str,
        stats: CrawlStats,
    ) -> None:
        crawl_live.record(kind=kind, outcome=outcome, label=label, url=url, stats=stats)
        if not self._active:
            return
        self._stats = stats
        self._events.append(CrawlEvent(kind=kind, outcome=outcome, label=label))
        self._render()

    def finish(self, stats: CrawlStats) -> None:
        crawl_live.finish(stats)
        if not self._active:
            return
        self._stats = stats
        self._queue_pending = 0
        if self.uses_tty:
            self._render(force=True)
            self._restore_tty()
        else:
            self._emit_log_summary(final=True)
        self._active = False

    def abort(self) -> None:
        crawl_live.abort()
        if not self._active:
            return
        if self.uses_tty:
            self._restore_tty()
        self._active = False

    def _restore_tty(self) -> None:
        sys.stderr.write("\033[?25h\n")
        sys.stderr.flush()

    def _render(self, *, force: bool = False) -> None:
        if self.uses_tty:
            self._render_tty()
            return
        now = time.monotonic()
        if force or (now - self._last_log_emit) >= 5.0:
            self._emit_log_summary(final=False)
            self._last_log_emit = now
        if self._events:
            event = self._events[-1]
            self._emit_log_event(event)

    def _processed_total(self) -> int:
        return self._stats.pages_fetched + self._stats.pdfs_fetched

    def _build_stats_lines(self, max_lines: int, cols: int) -> list[str]:
        elapsed = 0.0
        if self._started_at is not None:
            elapsed = (datetime.now(timezone.utc) - self._started_at).total_seconds()

        processed = self._processed_total()
        limit = self._max_pages or 1
        ratio = min(1.0, processed / limit)
        rate = processed / elapsed if elapsed > 0 else 0.0

        lines = [
            _truncate(f"myskin crawl  run #{self._run_id}", cols),
            _truncate(f"seed {self._seed_url}", cols),
            "",
            f"progress  {_bar(ratio, min(40, cols - 12))} {processed}/{self._max_pages}",
            f"elapsed   {_fmt_duration(elapsed)}   rate {rate:.1f}/s   queue {self._queue_pending}",
            "",
            (
                f"pages  fetched {self._stats.pages_fetched:4d}  "
                f"updated {self._stats.pages_updated:4d}  "
                f"same {self._stats.pages_unchanged:4d}  "
                f"failed {self._stats.pages_failed:4d}"
            ),
            (
                f"pdfs   fetched {self._stats.pdfs_fetched:4d}  "
                f"updated {self._stats.pdfs_updated:4d}  "
                f"same {self._stats.pdfs_unchanged:4d}  "
                f"failed {self._stats.pdfs_failed:4d}"
            ),
            f"links discovered this run: {self._stats.discovered}",
        ]
        return lines[:max_lines]

    def _build_event_lines(self, max_lines: int, cols: int) -> list[str]:
        if max_lines <= 0:
            return []
        recent = list(self._events)[-max_lines:]
        lines: list[str] = []
        for event in recent:
            mark = _OUTCOME_MARK.get(event.outcome, "?")
            prefix = f"[{event.kind:3}] {mark} {event.outcome:9}"
            width = max(1, cols - len(prefix) - 1)
            lines.append(prefix + " " + _truncate(event.label, width))
        if not lines:
            lines.append("waiting for pages…")
        return lines

    def _render_tty(self) -> None:
        rows, cols = shutil.get_terminal_size(fallback=(40, 100))
        split = max(10, rows // 2)
        top_budget = max(6, split - 2)
        bottom_budget = max(4, rows - split - 2)

        top = self._build_stats_lines(top_budget, cols)
        bottom = self._build_event_lines(bottom_budget, cols)

        while len(top) < top_budget:
            top.append("")
        while len(bottom) < bottom_budget:
            bottom.insert(0, "")

        divider = "─" * cols
        frame = ["\033[H\033[J", *top, divider, *bottom, "\033[J"]
        sys.stderr.write("\n".join(frame) + "\n")
        sys.stderr.flush()

    def _emit_log_summary(self, *, final: bool) -> None:
        processed = self._processed_total()
        tag = "crawl done" if final else "crawl"
        print(
            (
                f"[{tag}] run #{self._run_id}  {processed}/{self._max_pages}  "
                f"pages +{self._stats.pages_updated}/={self._stats.pages_unchanged}/"
                f"x{self._stats.pages_failed}  "
                f"pdfs +{self._stats.pdfs_updated}/={self._stats.pdfs_unchanged}/"
                f"x{self._stats.pdfs_failed}  "
                f"queue {self._queue_pending}  discovered {self._stats.discovered}"
            ),
            file=sys.stderr,
        )

    def _emit_log_event(self, event: CrawlEvent) -> None:
        mark = _OUTCOME_MARK.get(event.outcome, "?")
        print(
            f"  [{event.kind}] {mark} {event.outcome:9} {event.label}",
            file=sys.stderr,
        )
