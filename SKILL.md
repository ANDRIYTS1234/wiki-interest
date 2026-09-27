---
name: wiki-interest
description: Analyzes Wikipedia pageview trends to help B2C founders decide which topics to build and which languages to launch in. Use when the user asks whether interest in a topic is growing, wants to compare interest across language editions or markets, wants to check a claim like "interest in X exploded", or asks for a short shareable report (one-page PDF) based on Wikipedia/Вікіпедія pageview data. Do not use for general questions about a topic, for writing Wikipedia articles, or for analyzing the user's own business data.
compatibility: Requires Python 3.10+ (uv recommended) and network access to wikimedia.org, wikipedia.org and wikidata.org.
license: MIT
---

# wiki-interest

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
   Run `$W resolve --input resolve.json`. Read `attention[]` first.
   - `needs_choice` → pick the right `qid` from `candidates` by description; if unsure, ask the user.
   - `missing` in a language → say so plainly. `search_hits` are **not equivalents**; use one as a proxy only if the user agrees.
3. **Build the basket.** One article is never enough to judge a topic. Propose 5–20 related Wikidata items (core article + subtopics), grouped if useful (e.g. `rules`, `players`). See `references/basket-building.md`. Resolve them, show the user the list with statuses, and confirm before fetching.
4. **Write `analysis.json`** (format in `references/basket-building.md`): baskets with roles `target` / `context` / `control`, `langs`, `window`, `baselines`.
5. **Fetch.** `$W fetch --spec analysis.json --dry-run` first. If `estimated_minutes` > 2, tell the user how long it will take. Then `$W fetch --spec analysis.json`.
6. **Analyze.** `$W analyze --spec analysis.json`. Read the stdout summary: direction, `index_norm` with interval, `share_change`, confidence, flags. Open `metrics.json` only for details you need.
7. **Write `narrative.json`** — numbers ONLY as placeholders copied from the analyze output, e.g. `{target.pl.window.index_norm:pct}`. Any other digit (except years) is rejected. See `references/interpreting.md`.
8. **Report.** `$W report --metrics <metrics.json> --narrative narrative.json --out out/report.pdf`. If it fails because text does not fit, shorten the text — do not drop caveats.
9. **Answer in chat** in the user's language: the direct answer, confidence and why, what would change the conclusion, and the next cheap step to validate real demand. Link the PDF and `appendix.md`.

## Rules (each one fixes a real failure seen without this skill)

- **Check the user's premise.** If they say "interest exploded", test it; do not echo it.
- **Missing article ≠ no demand.** It is a gap in that Wikipedia, and must be stated as such.
- **Every flag in the analyze output must appear** in the conclusion or caveats (`references/interpreting.md` has wording).
- **Label hypotheses.** Causes (AI search, a TV series, school terms) are hypotheses unless you have a source. Write "[hypothesis]" or give the source.
- **Never compare raw totals of different-sized baskets or language editions.** Use `index_norm`, `share_change` and `compare.*` values.
- **Pageviews measure attention, not willingness to pay.** Always end with a direct demand test (search volume, landing page, survey).
- **Follow-up requests** ("add Latvian", "look at 3 years"): edit `analysis.json` and rerun fetch → analyze → report. The cache downloads only what is new. Explain what changed versus the previous answer.
- If a command fails with rate limit (exit 4) or network (exit 3), report it; never fill gaps with guesses.

## References (open only when needed)

- `references/basket-building.md` — choosing articles, groups, panels, exclusions, `analysis.json` format.
- `references/interpreting.md` — flags and confidence → wording for founders; narrative rules.
- `references/methodology.md` — what each metric means.
- `references/limits.md` — known limits of Wikimedia data.
