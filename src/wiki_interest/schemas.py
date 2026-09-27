"""Loading and validation of input JSON files. Errors are InputError (exit code 2) with a hint."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import InputError
from .mediawiki import validate_lang

QID_RE = re.compile(r"Q[1-9][0-9]*")


def load_json_file(path: str | Path, what: str) -> Any:
    """Read UTF-8 JSON (a BOM from Windows editors is tolerated)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError(f"{what} file not found: {p}", hint="Check the path; relative paths are from the current folder")
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {what} file {p}: {exc}", hint="Save the file as UTF-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{what} file {p} is not valid JSON: {exc}", hint="Validate the JSON syntax")


def validate_qid(value: Any, where: str) -> str:
    if not isinstance(value, str) or not QID_RE.fullmatch(value):
        raise InputError(f"{where}: invalid qid {value!r}", hint='A Wikidata item id looks like "Q1666254"')
    return value


def _nonempty_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{where}: expected a non-empty string, got {value!r}")
    return value.strip()


@dataclass(frozen=True)
class ResolveItem:
    kind: str  # "query" | "qid" | "title"
    query: str | None = None
    query_lang: str | None = None
    qid: str | None = None
    lang: str | None = None
    title: str | None = None

    @property
    def id(self) -> str:
        if self.kind == "qid":
            return self.qid  # type: ignore[return-value]
        if self.kind == "title":
            return f"{self.lang}:{self.title}"
        return f"query:{self.query_lang}:{self.query}"

    def as_input(self) -> dict[str, str]:
        if self.kind == "qid":
            return {"qid": self.qid}  # type: ignore[dict-item]
        if self.kind == "title":
            return {"lang": self.lang, "title": self.title}  # type: ignore[dict-item]
        return {"query": self.query, "query_lang": self.query_lang}  # type: ignore[dict-item]


@dataclass(frozen=True)
class ResolveRequest:
    items: list[ResolveItem]
    langs: list[str]


ITEM_FORMS = '{"query": "...", "query_lang": "uk"} | {"qid": "Q..."} | {"lang": "es", "title": "..."}'


def parse_resolve_item(raw: Any, where: str) -> ResolveItem:
    if not isinstance(raw, dict):
        raise InputError(f"{where}: expected an object", hint=f"Each item is one of {ITEM_FORMS}")
    keys = set(raw)
    if keys in ({"query"}, {"query", "query_lang"}):
        return ResolveItem(
            "query",
            query=_nonempty_str(raw["query"], f"{where}.query"),
            query_lang=validate_lang(raw.get("query_lang", "en")),
        )
    if keys == {"qid"}:
        return ResolveItem("qid", qid=validate_qid(raw["qid"], f"{where}.qid"))
    if keys == {"lang", "title"}:
        return ResolveItem("title", lang=validate_lang(raw["lang"]), title=_nonempty_str(raw["title"], f"{where}.title"))
    raise InputError(f"{where}: unexpected keys {sorted(keys)}", hint=f"Each item is exactly one of {ITEM_FORMS}")


def parse_resolve_request(data: Any) -> ResolveRequest:
    if not isinstance(data, dict):
        raise InputError("resolve input must be a JSON object", hint='{"items": [...], "langs": ["pl", "cs"]}')
    unknown = set(data) - {"items", "langs"}
    if unknown:
        raise InputError(f"resolve input: unexpected keys {sorted(unknown)}", hint='Allowed keys: "items", "langs"')
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise InputError("resolve input: \"items\" must be a non-empty list", hint=f"Each item is one of {ITEM_FORMS}")
    langs_raw = data.get("langs", [])
    if not isinstance(langs_raw, list):
        raise InputError('resolve input: "langs" must be a list of language codes')
    items = [parse_resolve_item(x, f"items[{i}]") for i, x in enumerate(items_raw)]
    langs = list(dict.fromkeys(validate_lang(l) for l in langs_raw))
    if not langs and any(i.kind != "title" for i in items):
        raise InputError('resolve input: "langs" is empty', hint='List the Wikipedia languages, e.g. "langs": ["pl", "cs"]')
    return ResolveRequest(items, langs)


# -- analysis.json (fetch and analyze) -------------------------------------------------

BASKET_ROLES = ("target", "context", "control")
BASKET_ID_RE = re.compile(r"[a-z][a-z0-9_]*")
# metrics.json top-level keys (see analyze/__init__.py's run_analysis): a basket id can never
# equal one of these, so a narrative placeholder like "compare.x.y" is unambiguous — report's
# get_path() resolves an unprefixed path through "baskets" only when its first segment is a
# known basket id, and otherwise walks the real top-level key.
RESERVED_BASKET_IDS = {
    "tool_version", "data_as_of", "question", "spec", "params", "confidence_rules",
    "basket_info", "baskets", "compare", "flags", "data_problems", "unused_series",
}
PAGEVIEWS_START = "2015-07"
BASKET_ITEM_FORMS = (
    '{"qid": "Q..."} | {"lang": "pl", "title": "...", "proxy_for": "Q..."(optional)}; '
    'both may add "group": "rules" and "exclude": "reason"'
)
GROUP_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class BasketItem:
    qid: str | None = None
    lang: str | None = None
    title: str | None = None
    proxy_for: str | None = None
    group: str | None = None  # metrics are also computed per group inside the basket
    exclude: str | None = None  # manual exclusion with a reason: not fetched, listed in the appendix

    @property
    def id(self) -> str:
        return self.qid if self.qid else f"{self.lang}:{self.title}"


@dataclass(frozen=True)
class Basket:
    id: str
    role: str
    label: str
    items: tuple[BasketItem, ...]


@dataclass(frozen=True)
class AnalysisSpec:
    question: str
    langs: tuple[str, ...]
    window_months: int
    window_end: str  # "latest" or "YYYY-MM"
    history_start: str  # "YYYY-MM"
    baselines: tuple[int, ...]
    baskets: tuple[Basket, ...]
    params: dict[str, Any]


def _month(value: Any, where: str) -> str:
    from .dates import MONTH_RE

    if not isinstance(value, str) or not MONTH_RE.fullmatch(value):
        raise InputError(f"{where}: expected a month \"YYYY-MM\", got {value!r}")
    return value


def _only_keys(raw: dict[str, Any], allowed: set[str], where: str, hint: str = "") -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise InputError(f"{where}: unexpected keys {sorted(unknown)}", hint=hint or f"Allowed keys: {sorted(allowed)}")


def parse_basket_item(raw: Any, langs: tuple[str, ...], where: str) -> BasketItem:
    if not isinstance(raw, dict):
        raise InputError(f"{where}: expected an object", hint=f"Each item is one of {BASKET_ITEM_FORMS}")
    optional = {"group", "exclude"}
    keys = set(raw) - optional
    group = raw.get("group")
    if group is not None and (not isinstance(group, str) or not GROUP_RE.fullmatch(group)):
        raise InputError(f"{where}.group must match [a-z][a-z0-9_]*, got {group!r}", hint="It is used in placeholders like {target.es.groups.rules.window.change_norm}")
    exclude = raw.get("exclude")
    if exclude is not None:
        exclude = _nonempty_str(exclude, f"{where}.exclude")
    if keys == {"qid"}:
        return BasketItem(qid=validate_qid(raw["qid"], f"{where}.qid"), group=group, exclude=exclude)
    if keys in ({"lang", "title"}, {"lang", "title", "proxy_for"}):
        lang = validate_lang(raw["lang"])
        if lang not in langs:
            raise InputError(f"{where}: lang {lang!r} is not in \"langs\" {list(langs)}", hint="Add the language to \"langs\"")
        proxy = raw.get("proxy_for")
        return BasketItem(
            lang=lang,
            title=_nonempty_str(raw["title"], f"{where}.title"),
            proxy_for=validate_qid(proxy, f"{where}.proxy_for") if proxy is not None else None,
            group=group,
            exclude=exclude,
        )
    raise InputError(f"{where}: unexpected keys {sorted(keys)}", hint=f"Each item is exactly one of {BASKET_ITEM_FORMS}")


ANALYSIS_EXAMPLE = (
    'Minimal analysis.json: {"question": "Is interest in X growing?", "langs": ["pl", "cs"], '
    '"window": {"months": 12, "end": "latest"}, "baselines": [2021], "baskets": [{"id": "target", '
    '"role": "target", "label": "X", "items": [{"qid": "Q..."}, {"qid": "Q...", "group": "basics"}]}, '
    '{"id": "control", "role": "control", "label": "A different topic", "items": [{"qid": "Q..."}]}]}'
)


def parse_analysis_spec(data: Any) -> AnalysisSpec:
    try:
        return _parse_analysis_spec(data)
    except InputError as exc:
        if not exc.hint:
            exc.hint = ANALYSIS_EXAMPLE
        raise


def _parse_analysis_spec(data: Any) -> AnalysisSpec:
    example = ANALYSIS_EXAMPLE
    if not isinstance(data, dict):
        raise InputError("analysis spec must be a JSON object", hint=example)
    _only_keys(data, {"question", "langs", "window", "history_start", "baselines", "baskets", "params"}, "analysis spec")
    question = _nonempty_str(data.get("question"), "question")

    langs_raw = data.get("langs")
    if not isinstance(langs_raw, list) or not langs_raw:
        raise InputError('"langs" must be a non-empty list', hint='e.g. "langs": ["pl", "cs"]')
    langs = tuple(dict.fromkeys(validate_lang(l) for l in langs_raw))

    window = data.get("window", {})
    if not isinstance(window, dict):
        raise InputError('"window" must be an object', hint='{"months": 12, "end": "latest"}')
    _only_keys(window, {"months", "end"}, "window")
    months = window.get("months", 12)
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 24:
        raise InputError(f"window.months must be an integer 1..24, got {months!r}")
    end = window.get("end", "latest")
    if end != "latest":
        end = _month(end, "window.end")

    history_start = _month(data.get("history_start", PAGEVIEWS_START), "history_start")
    if history_start < PAGEVIEWS_START:
        raise InputError(f"history_start {history_start} is before {PAGEVIEWS_START}", hint="Pageviews data starts in July 2015")

    baselines_raw = data.get("baselines", [])
    if not isinstance(baselines_raw, list) or not all(
        isinstance(y, int) and not isinstance(y, bool) and 2015 <= y <= 2100 for y in baselines_raw
    ):
        raise InputError('"baselines" must be a list of years, e.g. [2019, 2021]')

    baskets_raw = data.get("baskets")
    if not isinstance(baskets_raw, list) or not baskets_raw:
        raise InputError('"baskets" must be a non-empty list', hint=example)
    baskets: list[Basket] = []
    for i, b in enumerate(baskets_raw):
        where = f"baskets[{i}]"
        if not isinstance(b, dict):
            raise InputError(f"{where}: expected an object", hint=example)
        _only_keys(b, {"id", "role", "label", "items"}, where)
        bid = b.get("id")
        if not isinstance(bid, str) or not BASKET_ID_RE.fullmatch(bid):
            raise InputError(f"{where}.id must match [a-z][a-z0-9_]*, got {bid!r}", hint="It is used in placeholders like {target.uk.window.change}")
        if bid in RESERVED_BASKET_IDS:
            raise InputError(f"{where}.id {bid!r} is reserved", hint=f"Reserved ids: {sorted(RESERVED_BASKET_IDS)}")
        if bid in {x.id for x in baskets}:
            raise InputError(f"{where}.id {bid!r} is used twice")
        role = b.get("role")
        if role not in BASKET_ROLES:
            raise InputError(f"{where}.role must be one of {list(BASKET_ROLES)}, got {role!r}")
        items_raw = b.get("items")
        if not isinstance(items_raw, list) or not items_raw:
            raise InputError(f"{where}.items must be a non-empty list", hint=f"Each item is one of {BASKET_ITEM_FORMS}")
        items = tuple(parse_basket_item(x, langs, f"{where}.items[{j}]") for j, x in enumerate(items_raw))
        baskets.append(Basket(bid, role, _nonempty_str(b.get("label", bid), f"{where}.label"), items))
    if not any(b.role == "target" for b in baskets):
        raise InputError('no basket with role "target"', hint="The topic being evaluated needs role \"target\"")

    params = data.get("params", {})
    if not isinstance(params, dict):
        raise InputError('"params" must be an object')
    return AnalysisSpec(question, langs, months, end, history_start, tuple(baselines_raw), tuple(baskets), params)
