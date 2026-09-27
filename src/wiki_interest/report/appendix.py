"""appendix.md: basket composition with exclusion reasons, methodology, all flags, robustness
table, sources, how to reproduce (SPEC §9). Written straight from metrics.json — never from
narrative.json, so nothing here can drift from the numbers."""

from __future__ import annotations

from typing import Any

from .. import __version__
from ..analyze.quality import CONFIDENCE_RULES
from ..dates import window_label, window_shift_years
from .fmt import fmt_ci, fmt_pct, fmt_x

KNOWN_LIMITATIONS_EN = """\
- **Seasonal false positives in summer.** The anomalous-month detector (see below) can still flag a summer
  month at the edge of its threshold in years with a sharp year-over-year decline, because the whole year's
  level (used to scale the expected share) is itself unusually low. Treat a borderline ANOMALY_MONTHS flag on
  a summer month with more skepticism than one on a month with a large, unambiguous jump.
- **Fast move-log mode.** By default `resolve` only checks the move log of a page's current redirects, not of
  its qualifier-stripped base title (`--moves full` checks both). A former title that is no longer a redirect
  to this page (reused by a different page after the move, e.g. uk «Марс» → «Марс (планета)») may then be
  missed: its views before the move are not counted for this article. This does not affect a former title that
  is still a current redirect (the common case), which is always found and summed.
"""
KNOWN_LIMITATIONS_UK = """\
- **Літні хибні аномалії.** Детектор аномальних місяців (опис нижче) може позначити літній місяць на межі
  порогу в роки різкого спаду рік до року, бо рівень усього року (яким масштабується очікувана частка) сам
  занижений. До прапорця ANOMALY_MONTHS на межі порогу влітку варто ставитися обережніше, ніж до явного стрибка.
- **Швидкий режим журналу перейменувань.** За замовчуванням `resolve` перевіряє журнал переміщень лише для
  поточних редиректів сторінки, не для назви без уточнення в дужках (`--moves full` перевіряє обидва варіанти).
  Колишню назву, яку тепер зайняла інша стаття (наприклад uk «Марс» → «Марс (планета)»), у цьому режимі можна
  не знайти: перегляди до перейменування тоді не додаються. Це не стосується колишньої назви, яка й зараз є
  редиректом (звичайний випадок) — її знаходять і підсумовують завжди.
"""

METHODOLOGY_EN = """\
## Methodology

- **Data:** Wikimedia Pageviews API, human (`user`) views, daily, from {history_start}; project totals for
  normalization. Redirect and former-title views are added to the main title (main-title series only for
  bot/device shares).
- **Window:** {window_label} (complete months; the base is {shift} whole year(s) back, so it never
  overlaps the window and the same calendar months are compared — no seasonality); baseline years
  compare the same months again in each listed year.
- **Panel:** articles created before the base period, with complete data and at least
  `min_monthly_views`={min_monthly_views} average monthly views in the base period.
- **index_norm:** geometric mean over panel articles of (current+1)/(base+1), divided by the same ratio of
  edition traffic. 95% bootstrap interval over articles ({bootstrap} resamples, seed {seed}; not computed
  with fewer than 3 panel articles).
- **share_change:** change of the panel's summed share of edition traffic (per {views_scale} views).
- **Robustness variants:** leave-one-out range, without the 3 largest articles, median of article ratios,
  without one-off spikes, without anomalous months (each shown in the table below when available).
- **Spikes:** a day above spike_k={spike_k}x the centred {spike_window}-day rolling median and at least
  spike_min_abs={spike_min_abs} views above it; classified by automated/desktop share of the main title.
- **Anomalous months:** a month whose views exceed anomaly_k={anomaly_k}x its typical calendar-month share
  (median over other complete years) times that year's median level; only years after every panel article
  existed count.
- **Confidence rules:**
{confidence_rules}
"""
METHODOLOGY_UK = """\
## Методика

- **Дані:** Wikimedia Pageviews API, перегляди людей (`user`), щодня, з {history_start}; агрегати розділу для
  нормалізації. Перегляди редиректів і колишніх назв додано до основної назви (для часток ботів/пристроїв —
  лише основна стаття).
- **Вікно:** {window_label} (повні місяці; база зсунута на {shift} ціл. р., тож не перекривається з вікном
  і порівнює ті самі календарні місяці — сезонність прибрано); бази з `baselines` порівнюють ті самі місяці
  в кожному вказаному році.
- **Панель:** статті, створені до початку базового періоду, з повними даними й не менш ніж
  `min_monthly_views`={min_monthly_views} переглядів на місяць у середньому за базовий період.
- **index_norm:** середнє геометричне по статтях панелі відношення (поточне+1)/(попереднє+1), поділене на
  таке саме відношення трафіку розділу. 95% bootstrap-інтервал по статтях ({bootstrap} перевибірок, seed
  {seed}; не рахується при менш ніж 3 статтях у панелі).
- **share_change:** зміна сумарної частки панелі в трафіку розділу (на {views_scale} переглядів).
- **Варіанти стійкості:** діапазон leave-one-out, без 3 найбільших статей, медіана відношень по статтях, без
  разових сплесків, без аномальних місяців (кожен — у таблиці нижче, якщо застосовний).
- **Сплески:** день понад spike_k={spike_k}× ковзної {spike_window}-денної медіани і не менш ніж
  spike_min_abs={spike_min_abs} переглядів понад неї; клас — за частками automated/desktop основної статті.
- **Аномальні місяці:** місяць, чиї перегляди перевищують anomaly_k={anomaly_k}× його типову частку календарного
  місяця (медіана за іншими повними роками), помножену на медіанний рівень того року; рахуються лише роки, коли
  вже існували всі статті панелі.
- **Правила довіри:**
{confidence_rules}
"""


def _shift(spec: dict[str, Any]) -> int:
    return spec["window"].get("base_shift_years") or window_shift_years(spec["window"]["months"])


def _confidence_rules_text(lang: str) -> str:
    lines = []
    for section, rules in CONFIDENCE_RULES.items():
        lines.append(f"  - *{section}*:")
        lines.extend(f"    - {r}" for r in rules)
    return "\n".join(lines)


def _basket_composition(lang: str, basket_info: dict[str, Any], baskets: dict[str, Any], report_lang: str) -> str:
    out = ["## " + ("Basket composition" if report_lang == "en" else "Склад кошиків"), ""]
    for bid, info in basket_info.items():
        out.append(f"### {info['label']} (`{bid}`, role: {info['role']})")
        by_lang: dict[str, list[dict[str, Any]]] = {}
        for item in info["items"]:
            by_lang.setdefault(item["lang"], []).append(item)
        for l, items in sorted(by_lang.items()):
            out.append(f"- **{l}**:")
            for it in sorted(items, key=lambda x: x["item"]):
                bits = [it["article"] or it["item"]]
                if it["group"]:
                    bits.append(f"group={it['group']}")
                if it["proxy_for"]:
                    bits.append(f"proxy_for={it['proxy_for']}")
                if it["status"] != "ok":
                    bits.append(f"**{it['status']}**" + (f": {it['reason']}" if it["reason"] else ""))
                out.append(f"  - {', '.join(bits)}")
            # Automatic panel exclusions (created after the base period, too little volume, or
            # a data gap) are decided per claim, not per item; the window claim is representative.
            window = baskets.get(bid, {}).get(l, {}).get("window", {})
            excluded = (window.get("panel") or {}).get("excluded") or []
            if excluded:
                out.append("  - " + ("Excluded from the window panel" if report_lang == "en" else "Виключено з панелі вікна") + ":")
                for e in excluded:
                    out.append(f"    - {e['title']}: {e['reason']}")
        out.append("")
    return "\n".join(out)


def _flags_table(flags: list[dict[str, Any]], report_lang: str) -> str:
    if not flags:
        return "*" + ("No flags." if report_lang == "en" else "Прапорців немає.") + "*"
    header = "| code | severity | scope | detail |\n|---|---|---|---|"
    rows = []
    for f in flags:
        scope = ".".join(str(f.get(k)) for k in ("basket", "lang", "group", "scope") if f.get(k))
        rows.append(f"| {f['code']} | {f['severity']} | {scope} | {f['detail']} |")
    return "\n".join([header, *rows])


def _robustness_table(baskets: dict[str, Any], report_lang: str, lang_fmt: str) -> str:
    header = (
        "| basket | lang | window | loo_min | loo_max | no_top3 | median | no_spikes | no_anomalies |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    rows = []
    for bid, per_lang in baskets.items():
        for lang, block in per_lang.items():
            w = block["window"]
            if w.get("status") != "ok":
                rows.append(f"| {bid} | {lang} | {w.get('status')} | | | | | | |")
                continue
            v = w["variants"]

            def cell(key: str) -> str:
                x = v.get(key)
                return fmt_pct(x, lang_fmt) if x is not None else "—"

            rows.append(
                f"| {bid} | {lang} | {fmt_pct(w['change_norm'], lang_fmt)} "
                f"| {cell('loo_min')} | {cell('loo_max')} | {cell('no_top3')} | {cell('median_ratio')} "
                f"| {cell('no_spikes')} | {cell('no_anomalies')} |"
            )
    return "\n".join([header, *rows])


def _reproduce(metrics: dict[str, Any], report_lang: str) -> str:
    sp = metrics["spec"]
    lines = [
        "## " + ("How to reproduce" if report_lang == "en" else "Як відтворити"),
        "",
        "```bash",
        "wiki-interest fetch --spec analysis.json",
        "wiki-interest analyze --spec analysis.json",
        "wiki-interest report --metrics metrics.json --narrative narrative.json --out report.pdf"
        + (f" --report-lang {report_lang}" if report_lang != "uk" else ""),
        "```",
        "",
        f"- `tool_version`: {metrics['tool_version']}",
        f"- `data_as_of`: {metrics['data_as_of']}",
        f"- languages: {', '.join(sp['langs'])}; window: {sp['window']['months']} months ending {sp['window']['end']}",
        f"- history from {sp['history_start']}; baselines: {', '.join(str(b) for b in sp['baselines']) or '—'}",
        f"- date range fetched: {sp['range']['start']}..{sp['range']['end']}",
    ]
    return "\n".join(lines)


def build_appendix(metrics: dict[str, Any], report_lang: str) -> str:
    lang_fmt = report_lang
    sp = metrics["spec"]
    template = METHODOLOGY_UK if report_lang == "uk" else METHODOLOGY_EN
    methodology = template.format(
        history_start=sp["history_start"],
        months=sp["window"]["months"],
        shift=_shift(sp),
        window_label=window_label(sp["window"]["months"], _shift(sp), report_lang),
        min_monthly_views=metrics["params"]["min_monthly_views"]["value"],
        bootstrap=metrics["params"]["bootstrap"]["value"],
        seed=metrics["params"]["seed"]["value"],
        views_scale="1,000,000",
        spike_k=metrics["params"]["spike_k"]["value"],
        spike_window=metrics["params"]["spike_window"]["value"],
        spike_min_abs=metrics["params"]["spike_min_abs"]["value"],
        anomaly_k=metrics["params"]["anomaly_k"]["value"],
        confidence_rules=_confidence_rules_text(report_lang),
    )
    known = KNOWN_LIMITATIONS_UK if report_lang == "uk" else KNOWN_LIMITATIONS_EN

    parts = [
        f"# {metrics['question']}",
        "",
        _basket_composition(lang_fmt, metrics["basket_info"], metrics["baskets"], report_lang),
        methodology,
        "## " + ("Known limitations" if report_lang == "en" else "Відомі обмеження"),
        "",
        known,
        "## " + ("Quality flags" if report_lang == "en" else "Прапорці якості"),
        "",
        _flags_table(metrics["flags"], report_lang),
        "",
        "## " + ("Robustness (change_norm by variant)" if report_lang == "en" else "Стійкість (change_norm за варіантом)"),
        "",
        _robustness_table(metrics["baskets"], report_lang, lang_fmt),
        "",
        "## " + ("Sources" if report_lang == "en" else "Джерела"),
        "",
        "- Wikimedia Pageviews REST API (`wikimedia.org`), MediaWiki Action API, Wikidata API.",
        f"- wiki-interest {metrics['tool_version']}",
        "",
        _reproduce(metrics, report_lang),
        "",
    ]
    return "\n".join(parts)
