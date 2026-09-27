"""narrative.json: validation and rendering of the agent's text against metrics.json.

Numbers reach the reader only through placeholders `{path.in.metrics:format}` (formats: pct,
int, x, ci). Any other digit is rejected, except a bare four-digit year (19xx/20xx) — SPEC §9:
"Кожне число у звіті походить із метрик" (SPEC §1.3), so nothing here can be typed by hand.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import InputError
from .fmt import FORMATTERS, fmt_ci
from .suggest import NUMBER, closest_path, numeric_leaves, placeholder, placeholders_for_number, replace_span

PLACEHOLDER = re.compile(r"\{([^{}]*)\}")  # any {...} span; contents validated in render_text
PATH_RE = re.compile(r"[A-Za-z0-9_.\-]+")
BARE_DIGITS = re.compile(r"\d+")
YEAR = re.compile(r"(19|20)\d\d$")

FIELDS = {
    "title": {"type": "str", "max_len": 200},
    "answer": {"type": "str", "max_len": 320},
    "findings": {"type": "list", "max_items": 4, "max_len": 300},
    "recommendation": {"type": "str", "max_len": 400},
    "next_steps": {"type": "list", "max_items": 6, "max_len": 200},
    "caveats": {"type": "list", "max_items": 6, "max_len": 250},
}
REQUIRED = ("title", "answer", "findings", "recommendation")


def get_path(metrics: dict[str, Any], path: str) -> Any:
    """Walk `metrics` by dotted path. Raises InputError with a hint listing the available keys.

    A path starting with a basket id (e.g. "target.uk.window.change_norm") is resolved through
    metrics["baskets"] transparently, matching the agreed placeholder grammar `basket.lang.block.
    metric` while the file itself keeps basket ids namespaced under "baskets" (so a basket id can
    never collide with a top-level key such as "compare" or "flags"). "compare.*" and any other
    top-level key are walked as written.
    """
    parts = path.split(".")
    baskets = metrics.get("baskets") if isinstance(metrics, dict) else None
    node: Any = baskets if isinstance(baskets, dict) and parts and parts[0] in baskets else metrics
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if not isinstance(node, dict) or part not in node:
            available = sorted(node.keys()) if isinstance(node, dict) else []
            hint = (
                f"No key {'.'.join(walked)!r} in metrics.json. Available here: {available[:20]}"
                if available
                else f"{'.'.join(walked[:-1]) or '(root)'} is not an object; check the analyze summary's placeholders[] field"
            )
            raise InputError(f"narrative placeholder path not found: {path!r}", hint=hint, code="unknown_placeholder")
        node = node[part]
    return node


def _format_value(path: str, kind: str, value: Any, lang: str) -> str:
    if value is None:
        raise InputError(
            f"narrative placeholder {{{path}:{kind}}} has no value in metrics.json (null)",
            hint="This claim likely has no estimate (check its 'status' field nearby); pick another path or drop this sentence",
            code="empty_placeholder",
        )
    if kind == "ci":
        if not (isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value)):
            raise InputError(
                f"narrative placeholder {{{path}:ci}} does not point to a 2-value interval (got {value!r})",
                hint="Use a *_ci field such as index_norm_ci or ratio_ci",
                code="bad_placeholder_type",
            )
        return fmt_ci(value, lang)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InputError(
            f"narrative placeholder {{{path}:{kind}}} does not point to a number (got {value!r})",
            hint="Point the placeholder at a numeric field, or use :ci for an interval",
            code="bad_placeholder_type",
        )
    return FORMATTERS[kind](value, lang)


RATIO_KEYS = {"index", "index_norm", "ratio", "ratio_norm", "median_ratio", "spread"}  # 1 = no change
CHANGE_KEYS = {"change_abs", "change_norm", "share_change", "section_change"}  # 0 = no change


def _check_kind(path: str, kind: str, where: str) -> None:
    """:pct on a ratio would print 0.85 as +85% (a 15% fall); :x on a change would print -0.15 as -0,15x.

    Every value under `variants` is a change (index_norm - 1), whatever its name says: e.g.
    variants.median_ratio is the median-based change, not a ratio.
    """
    key = path.rsplit(".", 1)[-1]
    if ".variants." in f".{path}":
        if kind == "x":
            raise InputError(
                f"{where}: {{{path}:x}} — robustness variants are changes (0 = no change), not multipliers",
                hint=f"Use {{{path}:pct}}",
                code="bad_placeholder_format",
            )
        return
    if key in RATIO_KEYS and kind == "pct":
        suggestion = path.rsplit(".", 1)[0] + (".change_norm:pct" if key == "index_norm" else f".{key}:x")
        raise InputError(
            f"{where}: {{{path}:pct}} formats a ratio (1 = no change) as a percent change",
            hint=f"Use {{{path}:x}}, or for a percent change {{{suggestion}}}",
            code="bad_placeholder_format",
        )
    if key in CHANGE_KEYS and kind == "x":
        raise InputError(
            f"{where}: {{{path}:x}} formats a change (0 = no change) as a multiplier",
            hint=f"Use {{{path}:pct}}",
            code="bad_placeholder_format",
        )


def _with_fix(exc: InputError, fix: str | None, text: str, start: int, end: int) -> InputError:
    """Put the placeholder to use and the corrected sentence first in the hint."""
    if fix:
        exc.hint = f"Use {fix}. Corrected: «{replace_span(text, start, end, fix)}»" + (f" ({exc.hint})" if exc.hint else "")
    return exc


def render_text(text: str, metrics: dict[str, Any], lang: str, where: str, headline: set[str] | None = None) -> str:
    headline = headline or set()
    out, pos = [], 0
    for m in PLACEHOLDER.finditer(text):
        out.append(text[pos : m.start()])
        inner = m.group(1)
        path, sep, kind = inner.rpartition(":")
        try:
            if not sep:
                raise InputError(
                    f"{where}: malformed placeholder {{{inner}}}",
                    hint="Expected {path.to.metric:format}, e.g. {target.uk.window.change_norm:pct}",
                    code="malformed_placeholder",
                )
            if kind not in FORMATTERS and kind != "ci":
                raise InputError(
                    f"{where}: unknown placeholder format {kind!r} in {{{inner}}}",
                    hint="Allowed formats: pct, int, x, ci",
                    code="unknown_format",
                )
            if not PATH_RE.fullmatch(path):
                raise InputError(f"{where}: invalid characters in placeholder path {path!r}", code="malformed_placeholder")
            _check_kind(path, kind, where)
            value = get_path(metrics, path)
            out.append(_format_value(path, kind, value, lang))
        except InputError as exc:
            candidate = path if sep else inner
            if exc.code in ("unknown_format", "bad_placeholder_format"):
                fix = placeholder(candidate) if any(p == candidate for p, _ in numeric_leaves(metrics)) else None
            elif exc.code in ("unknown_placeholder", "malformed_placeholder", "bad_placeholder_type"):
                best = closest_path(metrics, candidate)
                fix = placeholder(best) if best else None
            else:
                fix = None
            raise _with_fix(exc, fix, text, m.start(), m.end())
        pos = m.end()
    out.append(text[pos:])
    rendered = "".join(out)

    # Check for typed numbers in the ORIGINAL text with placeholders masked (positions kept).
    masked = PLACEHOLDER.sub(lambda m: " " * len(m.group()), text)
    for bad in NUMBER.finditer(masked):
        token = bad.group().lstrip("−-+")
        if YEAR.fullmatch(token):
            continue
        after = masked[bad.end() : bad.end() + 1]
        fixes = placeholders_for_number(metrics, bad.group(), after, lang, headline)
        end = bad.end() + (1 if fixes and after in ("%", "×", "x") else 0)
        snippet = text[max(0, bad.start() - 20) : bad.end() + 20]
        exc = InputError(
            f"{where}: number {bad.group()!r} is typed directly, not from a placeholder (near {snippet!r})",
            hint="Every number must come from metrics.json; a bare number is only allowed as a 4-digit year (19xx/20xx)."
            + ("" if fixes else " No metric has this value: rephrase without it (e.g. \"the last two years\") or use a "
               "placeholder from analyze's `placeholders`."),
            code="bare_number",
        )
        if len(fixes) > 1:
            exc.hint = f"Other matches: {', '.join(fixes[1:])}. " + exc.hint
        raise _with_fix(exc, fixes[0] if fixes else None, text, bad.start(), end)
    return rendered


def _check_str(value: Any, where: str, max_len: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"narrative.{where} must be a non-empty string")
    if len(value) > max_len:
        raise InputError(f"narrative.{where} is {len(value)} characters, longer than {max_len}", hint="Shorten it; the PDF is one page")


NARRATIVE_EXAMPLE = (
    'Minimal narrative.json: {"title": "...", "answer": "... {target.uk.window.change_norm:pct} ...", '
    '"findings": ["...", "..."], "recommendation": "...", "next_steps": ["..."], "caveats": ["..."]} '
    "— lists are plain strings, numbers only as placeholders."
)


def validate_narrative(raw: Any) -> dict[str, Any]:
    try:
        return _validate_narrative(raw)
    except InputError as exc:
        exc.hint = (exc.hint + " " if exc.hint else "") + NARRATIVE_EXAMPLE
        raise


def _validate_narrative(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InputError("narrative must be a JSON object", hint='{"title", "answer", "findings", "recommendation", "next_steps", "caveats"}')
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise InputError(f"narrative: unexpected keys {unknown}", hint=f"Allowed keys: {sorted(FIELDS)}")
    missing = [f for f in REQUIRED if f not in raw]
    if missing:
        raise InputError(f"narrative: missing required keys {missing}")
    out: dict[str, Any] = {}
    for name, spec in FIELDS.items():
        if name not in raw:
            out[name] = [] if spec["type"] == "list" else ""
            continue
        value = raw[name]
        if spec["type"] == "str":
            _check_str(value, name, spec["max_len"])
            out[name] = value
        else:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise InputError(
                    f"narrative.{name} must be a list of strings",
                    hint=f'Write "{name}": ["first sentence", "second sentence"] — no objects, no single string.',
                )
            if len(value) > spec["max_items"]:
                raise InputError(f"narrative.{name} has {len(value)} items, more than {spec['max_items']}", hint="Keep only the most important ones")
            for i, v in enumerate(value):
                _check_str(v, f"{name}[{i}]", spec["max_len"])
            out[name] = value
    return out


def render_narrative(narrative: dict[str, Any], metrics: dict[str, Any], lang: str) -> dict[str, Any]:
    """Validated narrative (see validate_narrative) with every field's placeholders rendered."""
    from ..analyze import build_placeholders  # the headline numbers analyze offered: preferred in hints

    headline = set(build_placeholders(metrics))
    out: dict[str, Any] = {}
    for name, value in narrative.items():
        if isinstance(value, list):
            out[name] = [render_text(v, metrics, lang, f"{name}[{i}]", headline) for i, v in enumerate(value)]
        else:
            out[name] = render_text(value, metrics, lang, name, headline)
    return out
