"""Number formatting by report language (SPEC §9: uk uses a decimal comma, a space for
thousands, and a real minus sign "−"; en uses the usual decimal point, comma and hyphen)."""

from __future__ import annotations

import math
from typing import Any

MINUS = {"uk": "−", "en": "-"}
DECIMAL = {"uk": ",", "en": "."}
THOUSANDS = {"uk": " ", "en": ","}  # uk: a non-breaking space so it never wraps mid-number


def _sign_and_abs(value: float, lang: str) -> tuple[str, float]:
    if value < 0 or (value == 0 and math.copysign(1, value) < 0):
        return MINUS[lang], -value
    return "", value


def group_thousands(int_part: str, lang: str) -> str:
    sep = THOUSANDS[lang]
    rev = int_part[::-1]
    groups = [rev[i : i + 3] for i in range(0, len(rev), 3)]
    return sep.join(groups)[::-1]


def fmt_number(value: float, lang: str, sig_figs: int = 3, force_sign: bool = False) -> str:
    """Plain number, `sig_figs` significant digits, locale decimal/thousands separators."""
    if value == 0:
        return "0"
    sign, mag = _sign_and_abs(float(value), lang)
    text = f"{mag:.{sig_figs}g}"
    if "e" in text:  # ridiculously large/small: fall back to a plain fixed form
        text = f"{mag:.6f}".rstrip("0").rstrip(".")
    int_part, _, frac_part = text.partition(".")
    int_part = group_thousands(int_part, lang)
    out = int_part + (DECIMAL[lang] + frac_part if frac_part else "")
    prefix = sign or ("+" if force_sign else "")
    return prefix + out


def fmt_int(value: float, lang: str) -> str:
    sign, mag = _sign_and_abs(float(value), lang)
    return sign + group_thousands(str(round(mag)), lang)


def fmt_pct(value: float, lang: str, decimals: int = 0) -> str:
    """`value` is a fraction (0.24 -> "+24%"); always signed, since a % change without a sign
    ("24%" for a decline) misleads (baseline coaching note)."""
    sign, mag = _sign_and_abs(float(value) * 100, lang)
    text = f"{mag:.{decimals}f}"
    if decimals:
        text = text.replace(".", DECIMAL[lang])
    prefix = sign or "+"
    return f"{prefix}{text}%"


def fmt_x(value: float, lang: str, decimals: int = 2) -> str:
    sign, mag = _sign_and_abs(float(value), lang)
    text = f"{mag:.{decimals}f}".replace(".", DECIMAL[lang])
    return f"{sign}{text}×"


def fmt_ci(pair: Any, lang: str, sig_figs: int = 3) -> str:
    lo, hi = pair
    return f"[{fmt_number(lo, lang, sig_figs)}; {fmt_number(hi, lang, sig_figs)}]"


FORMATTERS = {"pct": fmt_pct, "int": fmt_int, "x": fmt_x}
