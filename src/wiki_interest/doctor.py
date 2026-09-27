"""`doctor`: environment checks with a status and a hint for each."""

from __future__ import annotations

import calendar
import dataclasses
import importlib
import sys
from importlib import metadata
from typing import Any, Callable

import requests

from .cache import Cache
from .config import ENV_CONTACT, Settings, latest_full_month
from .errors import WikiInterestError
from .http import HttpClient, parse_json

MIN_PYTHON = (3, 10)
DEPENDENCIES = ("requests", "pandas", "numpy", "matplotlib", "reportlab")


def _check(name: str, fn: Callable[[], tuple[str, str, str]]) -> dict[str, Any]:
    try:
        status, detail, hint = fn()
    except Exception as exc:  # a failing check must not abort the others
        status, detail, hint = "fail", f"{type(exc).__name__}: {exc}", ""
    out = {"name": name, "status": status, "detail": detail}
    if hint:
        out["hint"] = hint
    return out


def check_python() -> tuple[str, str, str]:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        return "fail", detail, "Install Python 3.10 or newer"
    return "ok", detail, ""


def check_dependencies() -> tuple[str, str, str]:
    found, missing = [], []
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
            found.append(f"{name} {metadata.version(name)}")
        except Exception:
            missing.append(name)
    if missing:
        return "fail", "missing: " + ", ".join(missing), "Run `uv sync` (or `pip install -r requirements.txt`)"
    return "ok", "; ".join(found), ""


def check_font() -> tuple[str, str, str]:
    from .report import fonts

    paths = fonts.font_paths()
    absent = [str(p) for p in paths.values() if not p.is_file()]
    if absent:
        return "fail", "not found: " + ", ".join(absent), "Reinstall matplotlib"
    lacking = fonts.missing_glyphs()
    if lacking:
        return "fail", "no glyphs for: " + "".join(lacking), "Reinstall matplotlib"
    fonts.register_reportlab()
    return "ok", str(paths["regular"]), ""


def check_cache(settings: Settings) -> tuple[str, str, str]:
    try:
        with Cache(settings.cache_path) as cache:
            cache.http_put("doctor://write-test", "{}")
    except WikiInterestError as exc:
        return "fail", exc.message, exc.hint
    return "ok", str(settings.cache_path.resolve()), ""


def check_contact(settings: Settings) -> tuple[str, str, str]:
    c = settings.contact
    if c.source == "env":
        return "ok", settings.user_agent, ""
    hint = f"Set {ENV_CONTACT} to your email or a URL so Wikimedia can reach you"
    if c.source == "project_url":
        return "warn", f"{ENV_CONTACT} not set; using project URL: {settings.user_agent}", hint
    return "fail", f"{ENV_CONTACT} not set and no project URL found: {settings.user_agent}", hint


def domain_probes(month: str) -> dict[str, str]:
    # Monthly granularity needs the range to span the whole month ("no full months between dates"
    # otherwise); this also confirms that data for `month` is already published.
    year, mon = map(int, month.split("-"))
    ym, last = f"{year:04d}{mon:02d}", calendar.monthrange(year, mon)[1]
    return {
        "wikimedia.org": "https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/"
        f"en.wikipedia.org/all-access/user/monthly/{ym}0100/{ym}{last:02d}00",
        "wikipedia.org": "https://en.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json&formatversion=2",
        "wikidata.org": "https://www.wikidata.org/w/api.php?action=query&meta=siteinfo&format=json&formatversion=2",
    }


def check_domain(client: HttpClient, url: str) -> tuple[str, str, str]:
    try:
        parse_json(client.get(url))
    except WikiInterestError as exc:
        return "fail", exc.message, exc.hint
    return "ok", url, ""


def run_doctor(settings: Settings, session: requests.Session | None = None, *, offline: bool = False) -> dict[str, Any]:
    checks = [
        _check("python", check_python),
        _check("dependencies", check_dependencies),
        _check("font", check_font),
        _check("cache", lambda: check_cache(settings)),
        _check("user_agent_contact", lambda: check_contact(settings)),
    ]
    if offline:
        for domain in domain_probes(latest_full_month()):
            checks.append({"name": f"network:{domain}", "status": "skipped", "detail": "--offline"})
    else:
        # Doctor should answer quickly: fewer retries than the data commands.
        quick = dataclasses.replace(settings, max_attempts=2, backoff_base=0.5)
        client = HttpClient(quick, session)
        for domain, url in domain_probes(latest_full_month()).items():
            checks.append(_check(f"network:{domain}", lambda url=url: check_domain(client, url)))
    failed = [c["name"] for c in checks if c["status"] == "fail"]
    warnings = [c["name"] for c in checks if c["status"] == "warn"]
    return {"healthy": not failed, "failed": failed, "warnings": warnings, "checks": checks}
