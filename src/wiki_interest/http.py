"""HTTP layer: one request at a time, minimum interval, retries on 429/5xx, error classification."""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import logging
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

import requests

from .cache import Cache
from .config import Settings
from .errors import HttpStatusError, NetworkError, RateLimitError

log = logging.getLogger(__name__)

ACCESS_DENIED_STATUSES = (401, 403, 407)


def parse_retry_after(value: str | None, now: dt.datetime | None = None) -> float | None:
    """Retry-After is either delta-seconds or an HTTP-date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(0.0, (when - now).total_seconds())


def canonical_url(url: str, params: Mapping[str, Any] | None = None) -> str:
    """Full URL with sorted query parameters: a stable cache key."""
    items = sorted((params or {}).items())
    return requests.Request("GET", url, params=items).prepare().url or url


def domain_of(url: str) -> str:
    return urlsplit(url).hostname or url


def parse_json(resp: requests.Response) -> Any:
    """Parse a body that must be JSON; anything else is an error, never an empty result."""
    try:
        return resp.json()
    except ValueError as exc:
        snippet = (resp.text or "")[:120].replace("\n", " ")
        raise NetworkError(
            f"{domain_of(resp.url or '')} returned non-JSON (HTTP {resp.status_code}): {snippet!r}",
            hint="Often a rate-limit or proxy page; wait a minute and retry",
            code="bad_response",
        ) from exc


class HttpClient:
    """Sequential client. Not thread-safe by design: SPEC §5 asks for one request at a time."""

    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        cache: Cache | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.session = session if session is not None else requests.Session()
        self.session.headers["User-Agent"] = settings.user_agent
        self.cache = cache
        # Looked up at call time so tests can patch time.sleep for CLI-level runs.
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self._clock = clock or (lambda: time.monotonic())
        self._last_start: float | None = None
        self.requests_made = 0
        self.cache_hits = 0

    def _throttle(self) -> None:
        if self._last_start is not None:
            wait = self._last_start + self.settings.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()

    def _backoff(self, attempt: int) -> float:
        return min(self.settings.backoff_cap, self.settings.backoff_base * 2 ** (attempt - 1))

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        allow_statuses: Iterable[int] = (200,),
    ) -> requests.Response:
        """GET with retries. Returns the response if its status is in `allow_statuses`."""
        allowed = set(allow_statuses)
        domain = domain_of(url)
        attempts = self.settings.max_attempts
        status: int | None = None
        for attempt in range(1, attempts + 1):
            self._throttle()
            self.requests_made += 1
            try:
                resp = self.session.get(url, params=params, timeout=self.settings.timeout)
            except requests.exceptions.Timeout as exc:
                status = None
                if attempt == attempts:
                    raise NetworkError(
                        f"{domain}: timed out {attempts} times",
                        hint="Check the connection or retry later",
                    ) from exc
                delay = self._backoff(attempt)
                log.warning("%s: timeout, retry %d/%d in %.1fs", domain, attempt, attempts - 1, delay)
                self._sleep(delay)
                continue
            except requests.exceptions.RequestException as exc:
                raise NetworkError(
                    f"{domain} is unreachable: {type(exc).__name__}: {exc}",
                    hint=f"Check DNS, proxy and firewall access to {domain}; run `wiki-interest doctor`",
                ) from exc

            status = resp.status_code
            if status in allowed:
                return resp
            if status == 429 or status >= 500:
                if attempt == attempts:
                    break
                delay = parse_retry_after(resp.headers.get("Retry-After"))
                if delay is None:
                    delay = self._backoff(attempt)
                delay = min(delay, self.settings.retry_after_cap)
                log.warning("%s: HTTP %d, retry %d/%d in %.1fs", domain, status, attempt, attempts - 1, delay)
                self._sleep(delay)
                continue
            if status in ACCESS_DENIED_STATUSES:
                raise NetworkError(
                    f"{domain}: access denied (HTTP {status})",
                    hint="A proxy or sandbox may block this domain, or the User-Agent was rejected;"
                    " set WIKI_INTEREST_CONTACT and run `wiki-interest doctor`",
                    code="access_denied",
                )
            raise HttpStatusError(
                f"{domain}: unexpected HTTP {status} for {resp.url}",
                status=status,
            )

        if status == 429:
            raise RateLimitError(
                f"{domain}: still rate-limited (HTTP 429) after {attempts} attempts",
                hint="Wait a few minutes, make sure no other job hits the same API, then rerun;"
                " cached data will not be downloaded again",
            )
        raise NetworkError(
            f"{domain}: server error HTTP {status} after {attempts} attempts",
            hint="Wikimedia may be degraded; retry later",
        )

    def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        return parse_json(self.get(url, params))

    def get_json_cached(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        validate: Callable[[Any], None] | None = None,
    ) -> Any:
        """For MediaWiki/Wikidata: served from http_cache within the TTL, otherwise fetched and stored.

        `validate` raises on API-level errors (HTTP 200 with an error body) so they are never cached.
        """
        key = canonical_url(url, params)
        if self.cache is not None:
            body = self.cache.http_get(key, self.settings.http_ttl_days)
            if body is not None:
                self.cache_hits += 1
                return json.loads(body)
        data = self.get_json(url, params)
        if validate is not None:
            validate(data)
        if self.cache is not None:
            self.cache.http_put(key, json.dumps(data, ensure_ascii=False, sort_keys=True))
        return data
