# wiki-interest

An [Agent Skill](https://agentskills.io) that helps B2C founders decide which topics to build and
which language markets to enter, using Wikipedia pageview data.

The agent reads [SKILL.md](SKILL.md) and drives a bundled Python CLI. The CLI does every step that
has one right answer: finding an article across languages via Wikidata (disambiguation pages,
redirects, renames, missing articles), downloading pageviews with a local cache, statistics and
robustness checks, charts and a one-page PDF. The agent only turns the request into a spec, agrees
the article basket with the user and writes the conclusion — and even there it can use numbers
only as placeholders filled from `metrics.json`.

Why the code does this and not the model: `evals/baseline/` records three runs of a strong model
without the skill. It got the direction right but shipped unsupported numbers (ratios of sums of
different-sized baskets, anomalous bot months left in, typed-in figures), silently skipped
redirects and missed articles. [docs/SPEC.md](docs/SPEC.md) turns each of those into a
requirement.

## Install

Python 3.10+; no system libraries (fonts come from matplotlib).

```bash
uv sync                      # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
uv run wiki-interest doctor  # Python, dependencies, font, cache, network, User-Agent contact
```

Set `WIKI_INTEREST_CONTACT` to your email or URL for the Wikimedia User-Agent (the project URL is
used otherwise). From another folder: `uv run --project <path-to-this-repo> wiki-interest doctor`.

## Commands

Every command prints one JSON object to stdout (`"ok": true|false`), progress to stderr, and
writes artifacts to `--workdir` (default `./wiki-interest-out`). Titles are passed only in JSON
files, never as shell arguments.

| command | input | does |
|---|---|---|
| `resolve --input resolve.json` | queries or QIDs, languages | finds the article in each language; `ok` / `missing` / `disambiguation` / `redirect_resolved`, redirects, former titles; never picks a substitute |
| `fetch --spec analysis.json [--dry-run]` | baskets | daily views (user, automated, desktop) + edition totals into the SQLite cache; only missing ranges are requested |
| `analyze --spec analysis.json` | cached views | `metrics.json`: basket index (geometric mean, bootstrap CI), share change, leave-one-out / top-3 / median / spikes / anomalous months, alternative baselines, language comparisons, flags, separate direction and magnitude confidence |
| `report --metrics … --narrative … --out report.pdf` | metrics + agent text | one-page PDF (fails rather than truncates), chart PNG, `appendix.md` with methodology and all flags |
| `doctor` | — | environment check |

Exit codes: 0 ok, 2 invalid input, 3 network, 4 rate limit, 5 incomplete data, 1 other.

## Offline demo

`examples/B-fasting/` contains a cache snapshot (pl vs cs, intermittent fasting, 24-month window),
the spec, the agent's narrative and the resulting report in `out/`:

```bash
uv run wiki-interest --cache-dir examples/B-fasting/cache --workdir demo analyze --spec examples/B-fasting/analysis.json
uv run wiki-interest --cache-dir examples/B-fasting/cache --workdir demo report \
  --metrics demo/metrics.json --narrative examples/B-fasting/narrative.json --out demo/report.pdf
```

`examples/A-astronomy/` is a larger spec (30 + 10 Wikidata items) that needs a live fetch.

## Tests

```bash
uv run pytest
```

HTTP is mocked at the session level with responses recorded from the real APIs
(`tests/record_fixtures.py`, not run in CI). `tests/test_e2e_offline.py` runs analyze → report on
the demo snapshot with every network call forbidden and checks the PDF has exactly one page.

## Layout

```
SKILL.md, references/      the skill: workflow and rules for the agent
src/wiki_interest/         CLI: resolve, fetch, analyze/, report/, cache, http
tests/                     unit, regression (resolve cases from the baselines), offline e2e
examples/                  demo specs, narrative, cache snapshot
docs/                      assignment and code contract (SPEC)
evals/                     baseline protocols, scenarios and trigger checks, agent runner
```

## Growing the skill

- **Larger studies.** Baskets from structured sources instead of the model's memory (Wikidata
  queries, "List of articles every Wikipedia should have", categories) behind the same `resolve`
  interface; parallel fetch with a shared rate limiter; monthly instead of daily series for
  long histories.
- **More questions.** Ranking many languages at once (index vs edition size, share of speakers),
  topic discovery (which subtopics grow fastest), alerts on a saved spec.
- **Verification loop.** Every new failure seen in an agent run becomes a check in
  `evals/scenarios.yaml` and, where it has one right answer, a CLI rule rather than an instruction.
