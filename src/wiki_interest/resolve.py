"""`resolve`: find a topic's articles in the requested languages without silently losing anything.

Rules (SPEC §6):
- Search results are never auto-picked unless the choice is unambiguous (see `choose_candidate`).
- A missing article gives status "missing" and search hits marked not_equivalent; substitutes are
  chosen by the agent with the user, never here.
- Disambiguation pages are reported, with the articles they link to as candidates.
- Redirects to the article and its former titles (move log) are listed so fetch can sum their views.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import __version__
from .cache import Cache
from .errors import InputError
from .http import HttpClient
from .mediawiki import MediaWiki, chunks
from .schemas import ResolveItem, ResolveRequest, parse_resolve_item
from .wikidata import Wikidata

ARTICLE_OK = ("ok", "redirect_resolved")
MAX_CANDIDATES = 5
MAX_SEARCH_HITS = 5
MAX_DISAMBIG_CANDIDATES = 10
RESULT_FILE = "resolve_result.json"

_QUALIFIER = re.compile(r"\s*\([^()]*\)$")


def base_title(title: str) -> str:
    """"Марс (планета)" -> "Марс"."""
    return _QUALIFIER.sub("", title)


def choose_candidate(query: str, results: list[dict[str, Any]]) -> int | None:
    """Index of the candidate to auto-select, or None when the user must choose.

    Auto-select only if there is exactly one result, or the first result is the only one whose
    label or matched alias equals the query (case-insensitive).
    """
    if not results:
        return None
    if len(results) == 1:
        return 0
    q = query.strip().casefold()
    exact = [
        i
        for i, r in enumerate(results)
        if (r.get("label") or "").casefold() == q or (r.get("match") or "").casefold() == q
    ]
    return 0 if exact == [0] else None


def _empty_entry(requested_title: str | None) -> dict[str, Any]:
    return {
        "status": "missing",
        "title": None,
        "requested_title": requested_title,
        "qid": None,
        "pageid": None,
        "created": None,
        "length": None,
        "redirects": [],
        "former_titles": [],
        "search_hits": [],
        "candidates": [],
        "warnings": [],
    }


class Resolver:
    def __init__(self, http: HttpClient, cache: Cache | None = None) -> None:
        self.mw = MediaWiki(http)
        self.wd = Wikidata(http)
        self.cache = cache

    # -- articles ----------------------------------------------------------------------

    def articles(self, lang: str, titles: list[str]) -> dict[str, dict[str, Any]]:
        """Entry for each requested title in one language."""
        out: dict[str, dict[str, Any]] = {}
        for batch in chunks(sorted(set(titles))):
            info = self.mw.page_info(lang, batch)
            for requested in batch:
                norm = info["normalized"].get(requested, requested)
                target = info["redirects"].get(norm, norm)
                page = info["pages"].get(target)
                entry = _empty_entry(requested)
                if page is None or page.get("missing") or page.get("invalid") or page.get("ns", 0) != 0:
                    out[requested] = entry
                    continue
                props = page.get("pageprops", {})
                entry.update(
                    title=page["title"],
                    qid=props.get("wikibase_item"),
                    pageid=page["pageid"],
                    length=page.get("length"),
                    status="redirect_resolved" if target != norm else "ok",
                )
                if "disambiguation" in props:
                    entry["status"] = "disambiguation"
                    entry["candidates"] = self._disambiguation_candidates(lang, page)
                else:
                    entry["created"] = self.mw.first_revision(lang, page["pageid"])
                    entry["redirects"] = self.mw.redirects(lang, page["pageid"])
                    entry["former_titles"] = self._former_titles(lang, page, entry["redirects"])
                out[requested] = entry
        return out

    def _disambiguation_candidates(self, lang: str, page: dict[str, Any]) -> list[dict[str, Any]]:
        base = base_title(page["title"]).casefold()
        links = [
            p
            for p in self.mw.links_with_props(lang, page["pageid"])
            if not p.get("missing") and "disambiguation" not in p.get("pageprops", {})
        ]
        # Links come alphabetically; rank titles sharing the base name first, then by article length
        # (a proxy for prominence: «Марс (планета)» must not lose to ten small villages named Марс).
        links.sort(key=lambda p: (not p["title"].casefold().startswith(base), -(p.get("length") or 0), p["title"]))
        return [
            {
                "title": p["title"],
                "qid": p.get("pageprops", {}).get("wikibase_item"),
                "description": p.get("description"),
                "length": p.get("length"),
            }
            for p in links[:MAX_DISAMBIG_CANDIDATES]
        ]

    def _former_titles(self, lang: str, page: dict[str, Any], redirects: list[str]) -> list[dict[str, Any]]:
        """Titles this page was moved away from, with the latest move date.

        The move log can only be searched by source title, so we check every redirect to the page
        plus the base title without a "(qualifier)" (covers "Марс" -> "Марс (планета)", where the
        old title was later reused). A move belongs to this page when its `logpage` is this page id;
        very old entries have logpage 0 and are matched by target title instead.
        Limitation: a former title that is neither a redirect now nor the base title is not found.
        """
        pageid, title = page["pageid"], page["title"]
        candidates = list(redirects)
        base = base_title(title)
        if base != title and base not in candidates:
            candidates.append(base)
        events = {t: self.mw.move_log(lang, t) for t in candidates}
        found: dict[str, str] = {}
        known = {title}
        for _ in range(2):  # the second pass links logpage-0 moves through titles found in the first
            for source, evs in events.items():
                for ev in evs:
                    target = (ev.get("params") or {}).get("target_title")
                    logpage = ev.get("logpage")
                    if logpage == pageid or (not logpage and target in known):
                        ts = ev["timestamp"]
                        if ts > found.get(source, ""):
                            found[source] = ts
                        known.add(source)
        redirect_set = set(redirects)
        return [{"title": t, "moved_at": found[t], "is_redirect": t in redirect_set} for t in sorted(found)]

    def search_hits(self, lang: str, terms: list[str | None]) -> list[dict[str, Any]]:
        hits: dict[str, dict[str, Any]] = {}
        for term in dict.fromkeys(t for t in terms if t):
            for h in self.mw.search(lang, term, MAX_SEARCH_HITS):
                if h["title"] not in hits and len(hits) < MAX_SEARCH_HITS:
                    hits[h["title"]] = {**h, "search_term": term, "not_equivalent": True}
        return list(hits.values())

    # -- items -------------------------------------------------------------------------

    def run(self, request: ResolveRequest) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for item in request.items:
            rec: dict[str, Any] = {
                "id": item.id,
                "input": item.as_input(),
                "status": "resolved",
                "qid": item.qid,
                "label": None,
                "description": None,
                "langs": {},
            }
            records.append(rec)
            if item.kind == "query":
                self._resolve_query(item, rec)

        # Title items: resolve in their own language first; that gives the QID.
        by_lang: dict[str, list[tuple[ResolveItem, dict[str, Any]]]] = {}
        for item, rec in zip(request.items, records):
            if item.kind == "title":
                by_lang.setdefault(item.lang, []).append((item, rec))  # type: ignore[arg-type]
        for lang, pairs in by_lang.items():
            found = self.articles(lang, [i.title for i, _ in pairs])  # type: ignore[misc]
            for item, rec in pairs:
                entry = found[item.title]  # type: ignore[index]
                if entry["status"] == "missing":
                    entry["search_hits"] = self.search_hits(lang, [item.title])
                    rec["status"] = "not_found"
                elif entry["status"] == "disambiguation":
                    rec["status"] = "needs_choice"
                else:
                    rec["qid"] = entry["qid"]
                    if not entry["qid"]:
                        entry["warnings"].append("article has no Wikidata item; other languages cannot be matched")
                rec["langs"][lang] = entry

        # Wikidata: labels and sitelinks for every known QID.
        all_langs = list(dict.fromkeys(request.langs + [i.lang for i in request.items if i.kind == "title"]))
        qids = [r["qid"] for r in records if r["qid"] and r["status"] == "resolved"]
        entities = self.wd.entities(qids, all_langs) if qids else {}

        wanted: dict[str, set[str]] = {}
        for item, rec in zip(request.items, records):
            if not rec["qid"] or rec["status"] != "resolved":
                continue
            ent = entities.get(rec["qid"])
            if ent is None or ent["missing"]:
                rec["status"] = "not_found"
                rec["error"] = f"Wikidata item {rec['qid']} does not exist"
                continue
            if ent["redirected_to"]:
                rec["merged_into"] = ent["redirected_to"]
            ui = item.query_lang or item.lang or "en"
            rec["label"] = rec["label"] or ent["labels"].get(ui) or ent["labels"].get("en")
            rec["description"] = rec["description"] or ent["descriptions"].get(ui) or ent["descriptions"].get("en")
            rec["_entity"] = ent
            for lang in request.langs:
                if lang in rec["langs"]:
                    continue
                title = ent["sitelinks"].get(lang)
                if title:
                    wanted.setdefault(lang, set()).add(title)

        found_by_lang = {lang: self.articles(lang, sorted(titles)) for lang, titles in wanted.items()}

        for item, rec in zip(request.items, records):
            ent = rec.pop("_entity", None)
            if ent is None:
                continue
            for lang in request.langs:
                if lang in rec["langs"]:
                    continue
                title = ent["sitelinks"].get(lang)
                if title:
                    entry = json.loads(json.dumps(found_by_lang[lang][title]))  # own copy per item
                    if entry["qid"] and entry["qid"] != rec["qid"]:
                        entry["warnings"].append(f"sitelink target belongs to Wikidata item {entry['qid']}")
                else:
                    entry = _empty_entry(None)
                    terms = [ent["labels"].get(lang)]
                    if item.kind == "query" and item.query_lang == lang:
                        terms.append(item.query)
                    terms.append(ent["labels"].get("en"))
                    entry["search_hits"] = self.search_hits(lang, terms)
                    entry["qid"] = None
                rec["langs"][lang] = entry

        result = {"langs": all_langs, "items": records, "coverage": coverage_matrix(records, all_langs)}
        if self.cache is not None:
            self.cache.put_resolved(cache_entries(records))
        return result

    def _resolve_query(self, item: ResolveItem, rec: dict[str, Any]) -> None:
        results = self.wd.search(item.query, item.query_lang)  # type: ignore[arg-type]
        search_lang = item.query_lang
        if not results and item.query_lang != "en":
            results = self.wd.search(item.query, "en")  # type: ignore[arg-type]
            search_lang = "en"
        rec["search_lang"] = search_lang
        rec["candidates"] = [
            {"qid": r["qid"], "label": r["label"], "description": r["description"]} for r in results[:MAX_CANDIDATES]
        ]
        pick = choose_candidate(item.query, results)  # type: ignore[arg-type]
        if not results:
            rec["status"] = "not_found"
        elif pick is None:
            rec["status"] = "needs_choice"
            rec["needs_choice"] = True
        else:
            rec["qid"] = results[pick]["qid"]
            rec["label"] = results[pick]["label"]
            rec["description"] = results[pick]["description"]
            rec["auto_selected"] = True


def coverage_matrix(records: list[dict[str, Any]], langs: list[str]) -> dict[str, Any]:
    """item x language -> status (None where the language could not be checked)."""
    return {
        "langs": langs,
        "rows": [
            {"id": r["id"], "cells": [r["langs"][l]["status"] if l in r["langs"] else None for l in langs]}
            for r in records
        ],
    }


def cache_entries(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Keys "qid:<QID>:<lang>" and "title:<lang>:<title>" -> entry, for fetch/analyze lookups."""
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        for lang, entry in rec["langs"].items():
            payload = {**entry, "lang": lang, "item_qid": rec["qid"]}
            if rec["qid"] and rec["status"] == "resolved":
                out[f"qid:{rec['qid']}:{lang}"] = payload
            for t in (entry.get("requested_title"), entry.get("title")):
                if t:
                    out[f"title:{lang}:{t}"] = payload
    return out


def lookup_article(
    resolver: Resolver, cache: Cache, lang: str, *, qid: str | None = None, title: str | None = None
) -> dict[str, Any]:
    """Resolved article for fetch/analyze: from the cache, else resolved now. Raises InputError when unusable."""
    if (qid is None) == (title is None):
        raise ValueError("pass exactly one of qid or title")
    key = f"qid:{qid}:{lang}" if qid else f"title:{lang}:{title}"
    entry = cache.get_resolved(key)
    if entry is None:
        raw = {"qid": qid} if qid else {"lang": lang, "title": title}
        item = parse_resolve_item(raw, "item")
        result = resolver.run(ResolveRequest([item], [lang]))
        rec = result["items"][0]
        if rec["status"] == "needs_choice" or lang not in rec["langs"]:
            raise InputError(
                f"{item.id}: cannot be resolved in {lang} ({rec['status']})",
                hint="Run `resolve` for this item and choose among its candidates",
            )
        entry = {**rec["langs"][lang], "lang": lang, "item_qid": rec["qid"]}
    label = qid or title
    if entry["status"] == "missing":
        raise InputError(
            f"{label}: no article in {lang}.wikipedia",
            hint="Pick a substitute with the user from resolve's search_hits and add it as"
            ' {"lang", "title", "proxy_for"} — it is not equivalent',
            code="article_missing",
        )
    if entry["status"] == "disambiguation":
        raise InputError(
            f"{label}: {lang}:{entry['title']} is a disambiguation page",
            hint="Choose one of resolve's candidates and use its qid or title",
            code="disambiguation",
        )
    return entry


# -- CLI -----------------------------------------------------------------------------------


def summarize(result: dict[str, Any], result_file: Path) -> dict[str, Any]:
    """Compact stdout view; the full result is in resolve_result.json."""
    items, attention = [], []
    for rec in result["items"]:
        s: dict[str, Any] = {"id": rec["id"], "status": rec["status"], "qid": rec["qid"], "label": rec["label"]}
        if rec.get("auto_selected"):
            s["auto_selected"] = True
        if rec.get("candidates"):
            s["candidates"] = rec["candidates"]
        if rec["status"] == "needs_choice" and rec.get("candidates"):
            attention.append(f"{rec['id']}: several Wikidata items match; pick a qid from candidates and rerun")
        if rec["status"] == "not_found":
            attention.append(f"{rec['id']}: not found" + (f" ({rec['error']})" if rec.get("error") else ""))
        langs = {}
        for lang, e in rec["langs"].items():
            le: dict[str, Any] = {"status": e["status"], "title": e["title"]}
            if e["status"] in ARTICLE_OK:
                le["redirects"] = len(e["redirects"])
                le["former_titles"] = [f"{f['title']} ({f['moved_at'][:10]})" for f in e["former_titles"]]
            if e["status"] == "redirect_resolved":
                le["requested_title"] = e["requested_title"]
            if e["status"] == "missing":
                le["search_hits_not_equivalent"] = [h["title"] for h in e["search_hits"]]
                attention.append(f"{rec['id']}/{lang}: no article; search hits are NOT equivalents — choose with the user")
            if e["status"] == "disambiguation":
                le["candidates"] = [{"title": c["title"], "qid": c["qid"]} for c in e["candidates"]]
                attention.append(f"{rec['id']}/{lang}: disambiguation page; choose a candidate")
            if e["warnings"]:
                le["warnings"] = e["warnings"]
            langs[lang] = le
        s["langs"] = langs
        items.append(s)
    return {
        "result_file": str(result_file),
        "langs": result["langs"],
        "coverage": result["coverage"],
        "items": items,
        "attention": attention,
    }


def cmd_resolve(args: Any, ctx: Any) -> dict[str, Any]:
    from .schemas import load_json_file, parse_resolve_request

    request = parse_resolve_request(load_json_file(args.input, "resolve input"))
    result = Resolver(ctx.http, ctx.cache).run(request)
    workdir: Path = ctx.settings.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    out_file = workdir / RESULT_FILE
    full = {"tool_version": __version__, **result}
    out_file.write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = summarize(result, out_file)
    summary["requests"] = ctx.http.requests_made
    summary["cache_hits"] = ctx.http.cache_hits
    return summary
