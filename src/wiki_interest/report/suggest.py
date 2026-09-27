"""Ready-made fixes for narrative validation errors, so a weak model corrects them in one try.

In a Haiku run 12 of 14 `report` calls failed while the model guessed placeholder paths and
formats. Each error now names the placeholder to use and shows the corrected sentence:
- a typed number: the placeholders whose rendered value equals it (e.g. "24" -> spec.window.months);
- an unknown path: the closest existing numeric path, with the right format;
- a wrong format: the same path with the right format.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Iterator

from .fmt import FORMATTERS, fmt_ci

RATIO_KEYS = {"index", "index_norm", "ratio", "ratio_norm", "median_ratio", "spread"}  # 1 = no change
CHANGE_KEYS = {"change_abs", "change_norm", "share_change", "section_change"}  # 0 = no change
SKIP = {"articles", "excluded", "top_contributors", "spikes", "anomaly_months", "bot_months", "qids", "reasons", "blocks"}
NUMBER = re.compile(r"[−\-+]?\d+(?:[.,]\d+)?")


def format_for(path: str) -> str:
    key = path.rsplit(".", 1)[-1]
    if key.endswith("_ci"):
        return "ci"
    if ".variants." in f".{path}" or key in CHANGE_KEYS:
        return "pct"
    if key in RATIO_KEYS:
        return "x"
    return "int"


def numeric_leaves(metrics: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """(placeholder path, value) for every numeric leaf a narrative may cite."""

    def walk(node: Any, path: str) -> Iterator[tuple[str, Any]]:
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in SKIP:
                    yield from walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            yield path, node
        elif isinstance(node, list) and len(node) == 2 and all(isinstance(x, (int, float)) for x in node) and path.endswith("_ci"):
            yield path, node

    yield from walk(metrics.get("baskets", {}), "")  # basket paths are written without "baskets."
    yield from walk(metrics.get("compare", {}), "compare")
    yield from walk(metrics.get("spec", {}).get("window", {}), "spec.window")


def placeholder(path: str) -> str:
    return f"{{{path}:{format_for(path)}}}"


def render(path: str, value: Any, lang: str) -> str:
    kind = format_for(path)
    return fmt_ci(value, lang) if kind == "ci" else FORMATTERS[kind](value, lang)


def closest_path(metrics: dict[str, Any], path: str) -> str | None:
    paths = [p for p, _ in numeric_leaves(metrics)]
    match = difflib.get_close_matches(path, paths, n=1, cutoff=0.5)
    return match[0] if match else None


def _magnitude(s: str) -> float | None:
    m = NUMBER.search(s.replace("−", "-").replace(" ", "").replace(" ", ""))
    if not m:
        return None
    return abs(float(m.group().replace(",", ".")))


def placeholders_for_number(metrics: dict[str, Any], typed: str, after: str, lang: str, headline: set[str]) -> list[str]:
    """Placeholders whose rendered value shows the same number the agent typed."""
    want = _magnitude(typed)
    if want is None:
        return []
    wanted_kind = "pct" if after.startswith("%") else "x" if after[:1] in ("×", "x") else None
    found = []
    for path, value in numeric_leaves(metrics):
        kind = format_for(path)
        if kind == "ci" or (wanted_kind and kind != wanted_kind):
            continue
        got = _magnitude(render(path, value, lang))
        if got is not None and abs(got - want) < 1e-9:
            found.append(path)
    found.sort(key=lambda p: (p not in headline, ".baselines." in p, ".groups." in p, ".variants." in p, len(p), p))
    return [placeholder(p) for p in found[:3]]


def replace_span(text: str, start: int, end: int, new: str, limit: int = 220) -> str:
    fixed = text[:start] + new + text[end:]
    return fixed if len(fixed) <= limit else fixed[: limit - 1] + "…"
