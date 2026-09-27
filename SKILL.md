---
name: wiki-interest
description: Wikipedia pageview analysis for product and market decisions. Use this skill, not memory or web search, whenever someone asks whether interest in a topic is growing or falling, especially when it will drive a decision — adding a course, topic or feature to an app; choosing which language, country or market to launch in or localize for; checking a claim like "interest in X exploded" before investing; comparing interest across Wikipedia language editions; or preparing a short one-page PDF report for investors, a cofounder or the team. Keywords — Wikipedia/Вікіпедія/вікі, pageviews/перегляди, interest/інтерес, trend/тренд, language editions/мовні розділи, localization/локалізація, market/ринок, курс, звіт. Not for explaining a topic, writing or translating Wikipedia articles, counting articles or dumps, or analyzing the user's own data (CSV, DAU, sales).
compatibility: Requires Python 3.10+ (uv recommended) and network access to wikimedia.org, wikipedia.org and wikidata.org.
license: MIT
---

# wiki-interest

**This skill does not run by itself: you must run the commands below yourself, in the shell, starting with `doctor`.**

Answers product questions ("should we add a course on X?", "which language market next?") with Wikipedia pageview data. The bundled CLI does all data work: finding articles across languages, downloading views, statistics, robustness checks, charts and the PDF. **You never download data or compute numbers yourself.** Your job: turn the request into an analysis spec, agree the article basket with the user, and write an honest conclusion from the CLI output.

## Setup (once per session)

`SKILL_DIR` = the directory containing this file. Run everything from the user's working folder:

```bash
W="uv run --project $SKILL_DIR wiki-interest"
$W doctor
```

If `uv` is missing: `python -m venv .venv && .venv/bin/pip install -e $SKILL_DIR` (Windows: `.venv/Scripts/pip`), then `W="python -m wiki_interest"` using that venv's python.
`doctor` must return `"ok": true`. If a network domain fails, tell the user — do not continue.
Every command prints one JSON object to stdout. Non-zero exit = stop and read `error.hint`.

## Workflow

1. **Clarify** topic, languages (Wikipedia language codes: uk, pl, cs, de…), and period. Default period: last 12 complete months vs the same months a year earlier, history from 2016. Ask only if the topic or languages are genuinely unclear.
2. **Resolve.** Write `resolve.json` (never pass titles as shell arguments):
   `{"items": [{"query": "<topic>", "query_lang": "<lang>"}], "langs": ["pl", "cs"]}`
   Run `$W resolve --input resolve.json`. Read `attention[]` first. Full details: `resolve_result.json` in the workdir.
   - status `needs_choice` → pick the right `qid` from `candidates` by description; if unsure, ask the user.
   - `disambiguation` in a language → use a `qid` from `candidates`, never the disambiguation page.
   - `missing` in a language → say so plainly. `search_hits` are **not equivalents**; use one as a proxy only if the user agrees.
3. **Build the basket.** One article is never enough to judge a topic. Propose 5–20 related Wikidata items (core article + subtopics), grouped if useful (e.g. `rules`, `players`). See `references/basket-building.md`. Resolve them, show the user the list with statuses, and confirm before fetching.
4. **Write `analysis.json`** (format in `references/basket-building.md`): baskets with roles `target` / `context` / `control`, `langs`, `window`, `baselines`.
5. **Fetch.** `$W fetch --spec analysis.json --dry-run` first. If `estimated_minutes` > 2, tell the user how long it will take. Then `$W fetch --spec analysis.json`. For a very large basket you may first run `--redirects none` (flag `REDIRECTS_SKIPPED`), but rerun without it before the final answer. Exit 5 = some series failed: report them; `--allow-partial` only if the user accepts `PARTIAL_DATA`.
6. **Analyze.** `$W analyze --spec analysis.json`. Read the stdout: `summary[]` (per basket × language: direction, `index_norm` with interval, `share_change`, direction/magnitude confidence, flag codes), `compare[]`, `placeholders`, and `attention[]` first: a line `DO NOT COMPARE DIRECTLY` means those two languages (or baskets) have no comparable articles — never compare them in the answer or report, say why. Open `metrics_file` only for details (flag details, reasons, panels, exclusions).
7. **Write `narrative.json`** — numbers ONLY as placeholders copied from `placeholders` in the analyze output, e.g. `{target.pl.window.change_norm:pct}` or `{target.pl.window.index_norm:x}`. Any other digit (except years) is rejected. See `references/interpreting.md`.
8. **Report.** `$W report --narrative narrative.json --report-lang uk` (`en` for English). It reads the workdir's `metrics.json` and writes `wiki-interest-out/report.pdf`; if the user wants another place, pass the same `--out` every time. Every flag and every "do not compare" is printed in the PDF automatically — put in `caveats` only what they do not cover. If the text does not fit, shorten findings or your own caveats.
9. **Answer in chat** in the user's language: the direct answer, confidence and why, what would change the conclusion, and the next cheap step to validate real demand. Link the PDF and `appendix.md`.

## Rules (each one fixes a real failure seen without this skill)

- **No numbers or conclusions without the CLI.** Every number, trend and recommendation must come from `resolve` → `fetch` → `analyze` → `report` that you actually ran in this conversation. Never write your own script to fetch data, compute metrics or build a report, and never estimate figures. If a command fails or cannot run, stop and tell the user what failed and why — do not produce a report or an answer without it.
- **Check the user's premise.** If they say "interest exploded", test it; do not echo it.
- **Missing article ≠ no demand.** It is a gap in that Wikipedia, and must be stated as such.
- **Flags:** the PDF lists all of them; in the chat answer mention those that change the conclusion (`references/interpreting.md` has wording).
- **Label hypotheses.** Causes (AI search, a TV series, school terms) are hypotheses unless you have a source. Write "[hypothesis]" or give the source.
- **Never compare raw totals of different-sized baskets or language editions.** Use `index_norm`, `share_change` and `compare.*` values.
- **Pageviews measure attention, not willingness to pay.** Always end with a direct demand test (search volume, landing page, survey).
- **Follow-up requests** ("add Latvian", "look at 3 years"): edit `analysis.json` and rerun fetch → analyze → report. The cache downloads only what is new, and the report overwrites the same PDF (`"replaced": true`) — never create a second report next to it. Explain what changed versus the previous answer.
- If a command fails with rate limit (exit 4) or network (exit 3), report it; never fill gaps with guesses.

## References (open only when needed)

- `references/basket-building.md` — choosing articles, groups, panels, exclusions, `analysis.json` format.
- `references/interpreting.md` — flags and confidence → wording for founders; narrative rules.
- `references/methodology.md` — what each metric means.
- `references/limits.md` — known limits of Wikimedia data.
