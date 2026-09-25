"""The one HTTP client every source adapter goes through.

Keeping it in one place means politeness is not something each adapter has to
remember: a minimum gap between requests, a descriptive User-Agent, a timeout,
and a bounded retry that honours `Retry-After` on 429/5xx. Adapters only ever
read public program metadata with it — never a program's own assets.
"""

from __future__ import annotations

import time

import httpx

from .. import __version__

USER_AGENT = f"bug-spray/{__version__} (+https://github.com/wwds-dev/bug_spray)"
MIN_INTERVAL_SECONDS = 0.35
RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """A platform could not be read. The scan skips that platform, not the run."""


class PoliteClient:
    def __init__(self, min_interval: float = MIN_INTERVAL_SECONDS, timeout: float = 30.0):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._last = 0.0

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def get_json(self, url: str, **params):
        return self._request("GET", url, params=params or None)

    def post_json(self, url: str, payload: dict):
        return self._request("POST", url, json=payload)

    def _request(self, method: str, url: str, **kwargs):
        for attempt in range(RETRIES + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == RETRIES:
                    raise SourceError(f"{method} {url}: {exc}") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code in RETRY_STATUSES and attempt < RETRIES:
                time.sleep(_retry_after(response, default=2**attempt))
                continue
            if response.status_code >= 400:
                raise SourceError(f"{method} {url}: HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise SourceError(f"{method} {url}: response was not JSON") from exc
        raise SourceError(f"{method} {url}: gave up after {RETRIES} retries")


def _retry_after(response: httpx.Response, default: float) -> float:
    try:
        return min(float(response.headers.get("Retry-After", default)), 60.0)
    except ValueError:
        return default
