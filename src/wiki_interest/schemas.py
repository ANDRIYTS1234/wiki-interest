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
