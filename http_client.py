"""HTTP helpers shared by the Spotify, MusicBrainz and ListenBrainz clients.

Moved out of mix.py unchanged; mix.py re-exports every name here.
"""

from __future__ import annotations

import email.utils
import time
from datetime import datetime, timezone
from typing import Any

import requests

UA = "spotify-discovery-mix/1.0 (personal discovery mixer)"


def retry_after_seconds(raw: str | None) -> float | None:
    """Seconds to wait from a Retry-After header, or None if it is unusable.

    The header is either delta-seconds or an HTTP-date (RFC 9110). A plain
    float() crashed the whole run on the date form.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


class SpotifyRateLimited(RuntimeError):
    """Spotify answered 429 and the wait was too long (or too often) to sit out.

    A RuntimeError, so existing `except RuntimeError` callers keep working; the
    message keeps "429" for watch_plays' quota back-off.
    """

    def __init__(self, what: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        hint = f" (Retry-After {retry_after:.0f}s)" if retry_after is not None else ""
        super().__init__(f"{what} -> 429 rate limited{hint}")


class Http:
    def __init__(self, user_agent: str = UA, min_interval: float = 0.0) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent
        self.min_interval = min_interval
        self._last = 0.0

    def _pace(self) -> None:
        gap = self.min_interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)

    @staticmethod
    def _short_429_wait(resp: requests.Response, attempt: int) -> float | None:
        """Seconds to sit out a 429, or None when the wait is too long to sit out.

        Spotify Dev Mode can return Retry-After of many hours for
        QUOTA_EXCEEDED. Sleeping that long wedges watch_plays; the caller
        returns the 429 so callers can degrade (e.g. skip recently-played).
        """
        wait_s = retry_after_seconds(resp.headers.get("Retry-After"))
        if wait_s is None:
            wait_s = min(16.0, 1.0 * 2**attempt)
        return None if wait_s > 60 else wait_s

    def request(
        self,
        method: str,
        url: str,
        *,
        retries: int = 5,
        **kwargs: Any,
    ) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        last_exc: Exception | None = None
        last_429: requests.Response | None = None
        for attempt in range(retries):
            self._pace()
            try:
                resp = self.s.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(min(8.0, 0.5 * 2**attempt))
                continue
            self._last = time.monotonic()
            if resp.status_code == 429:
                wait_s = self._short_429_wait(resp, attempt)
                if wait_s is None:
                    return resp
                last_429 = resp
                time.sleep(wait_s)
                continue
            if resp.status_code in {500, 502, 503, 504}:
                time.sleep(min(8.0, 0.5 * 2**attempt))
                continue
            return resp
        if last_429 is not None:
            # Still limited after every short wait: hand back the 429 itself so
            # callers see a rate limit, not a generic "failed after retries".
            return last_429
        if last_exc:
            raise last_exc
        raise RuntimeError(f"HTTP {method} {url} failed after retries")
