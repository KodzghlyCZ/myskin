from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    etag: str | None
    last_modified: str | None


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        delay_seconds: float,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.user_agent = user_agent
        self.delay_seconds = max(delay_seconds, 0.0)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _throttle(self) -> None:
        if self.delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def fetch(self, url: str) -> FetchResult:
        self._throttle()
        response = self._client.get(url)
        self._last_request_at = time.monotonic()
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content=response.content,
            content_type=content_type,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False

        base = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(base)
        if parser is None:
            parser = self._load_parser(f"{base}/robots.txt")
            self._parsers[base] = parser

        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _load_parser(self, robots_url: str) -> RobotFileParser:
        """Read robots.txt as the crawler, not as urllib's default agent.

        A missing file (404) allows the host. urllib's own agent is rejected
        with 403 by some of these sites, and RobotFileParser treats that 403
        as a ban on every URL.
        """
        parser = RobotFileParser()
        try:
            response = httpx.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=20.0,
                follow_redirects=True,
            )
        except Exception as exc:
            logger.warning("Could not read robots.txt for %s: %s", robots_url, exc)
            parser.allow_all = True
            return parser

        if response.status_code in (401, 403):
            parser.disallow_all = True
            return parser
        if response.status_code >= 400:
            parser.allow_all = True
            return parser
        parser.parse(response.text.splitlines())
        return parser
