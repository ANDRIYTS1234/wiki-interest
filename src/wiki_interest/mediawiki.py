"""MediaWiki Action API client for <lang>.wikipedia.org (read-only queries, cached)."""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from .errors import InputError, RateLimitError, WikiInterestError
from .http import HttpClient

BATCH = 50  # titles/pageids per query for anonymous clients
_TAG = re.compile(r"<[^>]+>")


def api_url(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


def _check_api_error(data: Any) -> None:
    if not isinstance(data, dict):
        raise WikiInterestError("MediaWiki API returned an unexpected JSON shape", code="api_error")
    err = data.get("error")
    if not err:
        return
    code, info = err.get("code", "?"), err.get("info", "")
    if code in ("ratelimited", "maxlag"):
        raise RateLimitError(f"MediaWiki API: {code}: {info}", hint="Wait a few minutes and rerun")
    raise WikiInterestError(f"MediaWiki API error {code}: {info}", code="api_error")


def strip_html(s: str, limit: int = 160) -> str:
    text = " ".join(html.unescape(_TAG.sub("", s or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chunks(seq: list[Any], n: int = BATCH) -> Iterable[list[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class MediaWiki:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def query(self, lang: str, *, ttl_days: float | None = None, **params: Any) -> dict[str, Any]:
        full = {"action": "query", "format": "json", "formatversion": 2, **params}
        return self.http.get_json_cached(api_url(lang), full, validate=_check_api_error, ttl_days=ttl_days)

    def query_all(self, lang: str, *, ttl_days: float | None = None, **params: Any) -> list[dict[str, Any]]:
        """Follow `continue` until the result set is complete."""
        out, cont = [], {}
        while True:
            data = self.query(lang, ttl_days=ttl_days, **params, **cont)
            out.append(data)
            if "continue" not in data:
                return out
            cont = data["continue"]

    def page_info(self, lang: str, titles: list[str]) -> dict[str, Any]:
        """Normalisation, redirect targets and info/pageprops for up to 50 titles."""
        if len(titles) > BATCH:
            raise ValueError("page_info takes at most 50 titles")
        data = self.query(
            lang,
            titles="|".join(titles),
            redirects=1,
            prop="info|pageprops",
            ppprop="disambiguation|wikibase_item",
        )
        q = data.get("query", {})
        return {
            "normalized": {n["from"]: n["to"] for n in q.get("normalized", [])},
            "redirects": {r["from"]: r["to"] for r in q.get("redirects", [])},
            "pages": {p["title"]: p for p in q.get("pages", [])},
        }

    def first_revision(self, lang: str, pageid: int) -> str | None:
        data = self.query(lang, pageids=pageid, prop="revisions", rvlimit=1, rvdir="newer", rvprop="timestamp")
        pages = data.get("query", {}).get("pages", [])
        revs = pages[0].get("revisions", []) if pages else []
        return revs[0]["timestamp"] if revs else None

    def redirects(self, lang: str, pageid: int) -> list[str]:
        """All main-namespace redirects to the page (every continuation page)."""
        titles: list[str] = []
        for data in self.query_all(lang, pageids=pageid, prop="redirects", rdlimit="max", rdnamespace=0, rdprop="title"):
            for page in data.get("query", {}).get("pages", []):
                titles.extend(r["title"] for r in page.get("redirects", []))
        return sorted(set(titles))

    def move_log(self, lang: str, title: str, *, ttl_days: float) -> list[dict[str, Any]]:
        """Move log entries whose source title is `title`. Move logs change rarely: cached longer
        than other MediaWiki queries (see config.Settings.move_log_ttl_days)."""
        events: list[dict[str, Any]] = []
        for data in self.query_all(lang, list="logevents", letype="move", letitle=title, lelimit="max", ttl_days=ttl_days):
            events.extend(data.get("query", {}).get("logevents", []))
        return events

    def search(self, lang: str, text: str, limit: int = 5) -> list[dict[str, Any]]:
        data = self.query(lang, list="search", srsearch=text, srlimit=limit, srnamespace=0, srprop="snippet|wordcount")
        return [
            {"title": h["title"], "snippet": strip_html(h.get("snippet", "")), "wordcount": h.get("wordcount")}
            for h in data.get("query", {}).get("search", [])
        ]

    def links_with_props(self, lang: str, pageid: int) -> list[dict[str, Any]]:
        """Main-namespace pages linked from `pageid` (a disambiguation page), with QID, short description, length."""
        pages: list[dict[str, Any]] = []
        for data in self.query_all(
            lang,
            pageids=pageid,
            generator="links",
            gplnamespace=0,
            gpllimit="max",
            prop="pageprops|description|info",
            ppprop="wikibase_item|disambiguation",
        ):
            pages.extend(data.get("query", {}).get("pages", []))
        merged: dict[str, dict[str, Any]] = {}
        for p in pages:  # continuation may deliver props of one page in several parts
            m = merged.setdefault(p["title"], {"title": p["title"]})
            for k in ("missing", "pageprops", "description", "length"):
                if k in p:
                    m[k] = p[k]
        return list(merged.values())


def validate_lang(lang: Any) -> str:
    if not isinstance(lang, str) or not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", lang):
        raise InputError(f"invalid language code {lang!r}", hint='Use Wikipedia language codes such as "uk", "pl", "zh-min-nan"')
    return lang
