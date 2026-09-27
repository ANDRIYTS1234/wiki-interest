"""Paths, User-Agent and limits."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Mapping

import requests

from . import __version__
from .errors import InputError

DIST_NAME = "wiki-interest"

ENV_CONTACT = "WIKI_INTEREST_CONTACT"
ENV_CACHE = "WIKI_INTEREST_CACHE"
ENV_MIN_INTERVAL = "WIKI_INTEREST_MIN_INTERVAL"

DEFAULT_CACHE_DIR = Path(".wiki-interest-cache")
CACHE_FILENAME = "cache.sqlite"
DEFAULT_WORKDIR = Path("wiki-interest-out")

# Pageviews for month M are published a few days after M ends; before that
# the "last full month" is not safe to request.
DATA_LAG_DAYS = 3

# First day of the Pageviews API.
PAGEVIEWS_START = dt.date(2015, 7, 1)
# The `automated` agent class exists from 2020-04-29 (first day partial). Before that the
# per-article API answers with explicit zeros that are not real measurements, so earlier
# days are never requested and are recorded as "unavailable".
AUTOMATED_START = dt.date(2020, 5, 1)

# Rough wall time per request for --dry-run estimates: min_interval plus typical latency.
EST_SECONDS_PER_REQUEST = 0.6


@dataclass(frozen=True)
class Contact:
    value: str | None
    source: str  # "env" | "project_url" | "none"


def project_url() -> str | None:
    """First URL from [project.urls]: installed metadata, else pyproject.toml of a source checkout."""
    try:
        entries = metadata.metadata(DIST_NAME).get_all("Project-URL") or []
    except metadata.PackageNotFoundError:
        entries = []
    for entry in entries:
        url = entry.partition(",")[2].strip()
        if url:
            return url
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r"^\[project\.urls\]\s*\n\s*[\w\-\"' ]+\s*=\s*\"([^\"]+)\"", text, re.M)
        if m:
            return m.group(1)
    return None


def resolve_contact(environ: Mapping[str, str] | None = None) -> Contact:
    environ = os.environ if environ is None else environ
    value = (environ.get(ENV_CONTACT) or "").strip()
    if value:
        return Contact(value, "env")
    url = project_url()
    if url:
        return Contact(url, "project_url")
    return Contact(None, "none")


def user_agent(contact: Contact) -> str:
    ua = f"wiki-interest/{__version__}"
    if contact.value:
        ua += f" ({contact.value})"
    return f"{ua} python-requests/{requests.__version__}"


def latest_full_month(now: dt.datetime | None = None, lag_days: int = DATA_LAG_DAYS) -> str:
    """Last calendar month whose pageviews should already be published, as YYYY-MM (UTC)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ref = (now - dt.timedelta(days=lag_days)).date()
    first = ref.replace(day=1)
    prev = first - dt.timedelta(days=1)
    return f"{prev.year:04d}-{prev.month:02d}"


@dataclass
class Settings:
    cache_dir: Path
    workdir: Path
    contact: Contact
    min_interval: float = 0.25  # seconds between consecutive requests
    max_attempts: int = 6  # per request, including the first one
    backoff_base: float = 1.0  # seconds; doubles each retry
    backoff_cap: float = 60.0
    retry_after_cap: float = 120.0
    timeout: float = 30.0
    http_ttl_days: int = 7

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / CACHE_FILENAME

    @property
    def user_agent(self) -> str:
        return user_agent(self.contact)


def load_settings(
    cache_dir: str | Path | None = None,
    workdir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Precedence for the cache: --cache-dir, then $WIKI_INTEREST_CACHE, then ./.wiki-interest-cache."""
    environ = os.environ if environ is None else environ
    if cache_dir is None:
        cache_dir = environ.get(ENV_CACHE) or DEFAULT_CACHE_DIR
    settings = Settings(
        cache_dir=Path(cache_dir).expanduser(),
        workdir=Path(workdir or DEFAULT_WORKDIR).expanduser(),
        contact=resolve_contact(environ),
    )
    raw = environ.get(ENV_MIN_INTERVAL)
    if raw:
        try:
            settings.min_interval = float(raw)
        except ValueError:
            settings.min_interval = -1.0
        if settings.min_interval < 0:
            raise InputError(
                f"{ENV_MIN_INTERVAL}={raw!r} is not a non-negative number",
                hint=f"Unset {ENV_MIN_INTERVAL} or set it to seconds, e.g. 0.25",
            )
    return settings
