"""Wikidata API client: entity search and sitelinks (cached)."""

from __future__ import annotations

from typing import Any

from .errors import InputError, RateLimitError, WikiInterestError
from .http import HttpClient
from .mediawiki import chunks

API = "https://www.wikidata.org/w/api.php"


def site_id(lang: str) -> str:
    """Wikipedia sitelink key: "uk" -> "ukwiki", "zh-min-nan" -> "zh_min_nanwiki"."""
    return lang.replace("-", "_") + "wiki"


def _check_api_error(data: Any) -> None:
    if not isinstance(data, dict):
        raise WikiInterestError("Wikidata API returned an unexpected JSON shape", code="api_error")
    err = data.get("error")
    if not err:
        return
    if err.get("code") == "no-such-entity" and err.get("id"):
        return  # handled per id by Wikidata.entities()
    code, info = err.get("code", "?"), err.get("info", "")
    if code in ("ratelimited", "maxlag"):
        raise RateLimitError(f"Wikidata API: {code}: {info}", hint="Wait a few minutes and rerun")
    if code in ("unknown_language", "no-such-entity", "param-illegal", "badvalue", "invalid-entity-id"):
        raise InputError(f"Wikidata API rejected the request: {code}: {info}", hint="Check QIDs and language codes")
    raise WikiInterestError(f"Wikidata API error {code}: {info}", code="api_error")


class Wikidata:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def _get(self, **params: Any) -> dict[str, Any]:
        return self.http.get_json_cached(API, {"format": "json", **params}, validate=_check_api_error)

    def search(self, query: str, lang: str, limit: int = 10) -> list[dict[str, Any]]:
        data = self._get(action="wbsearchentities", search=query, language=lang, uselang=lang, type="item", limit=limit)
        return [
            {
                "qid": r["id"],
                "label": r.get("label") or r.get("display", {}).get("label", {}).get("value"),
                "description": r.get("description") or r.get("display", {}).get("description", {}).get("value"),
                "match": (r.get("match") or {}).get("text"),
            }
            for r in data.get("search", [])
        ]

    def entities(self, qids: list[str], langs: list[str]) -> dict[str, dict[str, Any]]:
        """{qid: {"labels": {lang: str}, "descriptions": {...}, "sitelinks": {lang: title}, "missing": bool,
        "redirected_to": qid|None}} for the requested Wikipedia languages."""
        out: dict[str, dict[str, Any]] = {}
        label_langs = sorted(set(langs) | {"en"})
        pending = [list(b) for b in chunks(sorted(set(qids)))]
        while pending:
            batch = pending.pop(0)
            data = self._get(
                action="wbgetentities",
                ids="|".join(batch),
                props="labels|descriptions|sitelinks",
                languages="|".join(label_langs),
                sitefilter="|".join(site_id(l) for l in sorted(set(langs))),
            )
            err = data.get("error")
            if err:
                # One unknown id fails the whole batch: mark it missing and retry the rest.
                bad = err["id"]
                if bad not in batch:
                    raise WikiInterestError(f"Wikidata API error no-such-entity for {bad}", code="api_error")
                out[bad] = {"missing": True, "redirected_to": None, "labels": {}, "descriptions": {}, "sitelinks": {}}
                rest = [q for q in batch if q != bad]
                if rest:
                    pending.insert(0, rest)
                continue
            for key, ent in data.get("entities", {}).items():
                sitelinks = ent.get("sitelinks", {})
                # A merged item comes back under its new id with {"redirects": {"from", "to"}}.
                requested = (ent.get("redirects") or {}).get("from", key)
                out[requested] = {
                    "missing": "missing" in ent,
                    "redirected_to": ent["id"] if ent.get("id") and ent["id"] != requested else None,
                    "labels": {k: v["value"] for k, v in ent.get("labels", {}).items()},
                    "descriptions": {k: v["value"] for k, v in ent.get("descriptions", {}).items()},
                    "sitelinks": {l: sitelinks[site_id(l)]["title"] for l in langs if site_id(l) in sitelinks},
                }
        return out
