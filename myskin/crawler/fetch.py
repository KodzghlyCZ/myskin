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
            parser = RobotFileParser()
            robots_url = f"{base}/robots.txt"
            try:
                parser.set_url(robots_url)
                parser.read()
            except Exception as exc:
                logger.warning("Could not read robots.txt for %s: %s", base, exc)
            self._parsers[base] = parser

        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True
