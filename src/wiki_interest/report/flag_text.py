"""Plain-language wording of quality flags and incomparable comparisons for the PDF.

The report prints every flag from metrics.json in its caveats block whatever the agent wrote:
a run on Haiku showed that a model following SKILL.md still leaves some flags out of the PDF.
The English wording is the "Say" column of references/interpreting.md (tests/test_skill_docs.py
keeps the two identical), so what the agent reads and what the reader sees cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from ..analyze.quality import SEVERITY

FLAG_TEXT: dict[str, dict[str, str]] = {
    "LOW_VOLUME": {
        "en": "Few views per month; small changes look large. Treat as a weak signal.",
        "uk": "Мало переглядів на місяць: невеликі зміни виглядають великими. Це слабкий сигнал.",
    },
    "SPIKE_DRIVEN": {
        "en": "The change depends on one-off spikes (news, a viral post); the appendix shows the result without them.",
        "uk": "Зміна залежить від разових сплесків (новини, вірусний допис); результат без них — у додатку.",
    },
    "ANOMALY_MONTHS": {
        "en": "Some months are abnormal (often unfiltered bots); the appendix shows the result without them.",
        "uk": "Окремі місяці аномальні (часто невідфільтровані боти); результат без них — у додатку.",
    },
    "BASKET_SENSITIVE": {
        "en": "The result depends on which articles are included; treat the magnitude as uncertain.",
        "uk": "Результат залежить від складу кошика статей; величину зміни вважайте невизначеною.",
    },
    "CONCENTRATION_DIVERGENCE": {
        "en": "A few big articles move differently from the rest of the topic.",
        "uk": "Кілька великих статей рухаються інакше, ніж решта теми.",
    },
    "BOT_SUSPECT": {
        "en": "Part of the traffic looks automated.",
        "uk": "Частина трафіку схожа на автоматичну (боти).",
    },
    "ARTICLE_MISSING": {
        "en": "No article in that language: a gap in Wikipedia, not proof of no demand.",
        "uk": "Статті цією мовою немає: це прогалина Вікіпедії, а не доказ відсутності попиту.",
    },
    "PROXY_USED": {
        "en": "A related but different article stands in; it is not compared directly with other languages.",
        "uk": "Замість відсутньої статті взято суміжну, але іншу; напряму з іншими мовами її не порівнюють.",
    },
    "NEW_ARTICLE": {
        "en": "An article was created during the period; early growth may just be the article being new.",
        "uk": "Статтю створено протягом періоду; ранній ріст може бути ефектом нової сторінки.",
    },
    "PRE_2020_BOT_CLASS": {
        "en": "Before May 2020 Wikimedia did not separate bots; the old baseline may be inflated.",
        "uk": "До травня 2020 Wikimedia не відокремлювала ботів; стара база може бути завищена.",
    },
    "BOT_RECLASSIFICATION_2025": {
        "en": "Wikimedia reclassified bot traffic in Mar–Aug 2025; year-over-year changes across that period may be overstated.",
        "uk": "У березні–серпні 2025 Wikimedia перекласифікувала бот-трафік; зміни рік до року через цей період можуть бути завищені.",
    },
    "PANEL_SMALL": {
        "en": "Few comparable articles in the panel; a weak basis for a conclusion.",
        "uk": "У панелі мало порівнянних статей; слабка основа для висновку.",
    },
    "REDIRECTS_SKIPPED": {
        "en": "Quick pass without redirects; the result is preliminary.",
        "uk": "Швидкий прохід без редиректів; результат попередній.",
    },
    "PARTIAL_DATA": {
        "en": "Some series failed to download; the result rests on incomplete data.",
        "uk": "Частину рядів не вдалося завантажити; результат спирається на неповні дані.",
    },
    "UNUSED_SERIES": {
        "en": "Some downloaded series are not used in any basket.",
        "uk": "Частина завантажених рядів не входить у жоден кошик.",
    },
}

SEVERITY_ORDER = {"high": 0, "warning": 1, "info": 2}

assert set(FLAG_TEXT) == set(SEVERITY), "every flag code needs report wording"


def _where(f: dict[str, Any]) -> str:
    parts = [f.get("basket"), f.get("lang")]
    base = "/".join(p for p in parts if p)
    return f"{base}/{f['group']}" if base and f.get("group") else base


def flag_lines(flags: list[dict[str, Any]], lang: str) -> list[str]:
    """One line per flag code (most severe first), with the basket/language places it applies to."""
    by_code: dict[str, set[str]] = {}
    for f in flags:
        by_code.setdefault(f["code"], set())
        w = _where(f)
        if w:
            by_code[f["code"]].add(w)
    codes = sorted(by_code, key=lambda c: (SEVERITY_ORDER.get(SEVERITY[c], 9), c))
    out = []
    for code in codes:
        where = sorted(by_code[code])
        suffix = f" ({', '.join(where)})" if where else ""
        out.append(f"{FLAG_TEXT[code][lang]}{suffix}")
    return out


def not_comparable_text(entry: dict[str, Any], lang: str) -> str:
    """Why two languages (or baskets) cannot be compared directly, from analyze's compare entry."""
    kind, a, b = entry["kind"], entry["a"], entry["b"]
    reason, d = entry["reason"], entry.get("detail", {})
    if kind == "languages":
        head = {"en": f"{a} and {b} are not compared directly", "uk": f"Мови {a} і {b} напряму не порівнюються"}[lang]
    else:
        head = {"en": f"Baskets {a} and {b} are not compared", "uk": f"Кошики {a} і {b} не порівнюються"}[lang]
    if reason == "no_common_articles":
        why = {"en": "no Wikidata item has an article in both panels", "uk": "жодна Wikidata-сутність не має статті в обох панелях"}[lang]
        extra = []
        for side in (a, b):
            if d.get("missing", {}).get(side):
                extra.append({"en": f"missing in {side}: {', '.join(d['missing'][side])}",
                              "uk": f"немає статті {side}: {', '.join(d['missing'][side])}"}[lang])
            if d.get("proxies", {}).get(side):
                extra.append({"en": f"{side} uses a stand-in article ({', '.join(d['proxies'][side])})",
                              "uk": f"{side} має лише замінник ({', '.join(d['proxies'][side])})"}[lang])
        if extra:
            why += "; " + "; ".join(extra)
    else:
        sides = ", ".join(f"{s}: {st}" for s, st in d.get("status", {}).items() if st != "ok")
        why = {"en": f"no estimate on one side ({sides})", "uk": f"з одного боку немає оцінки ({sides})"}[lang]
    return f"{head}: {why}."
