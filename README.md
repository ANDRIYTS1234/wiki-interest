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

## Install as an agent skill

The whole repository is the skill directory: `SKILL.md` at the root, the CLI in `src/`, the
agent's reference notes in `references/`. Tests, docs and evals are extras the agent never needs.

What the machine needs:
- an agent with a shell tool that supports [Agent Skills](https://agentskills.io) (Claude Code,
  or any agent loop that puts `SKILL.md` into the model's context — see `evals/run_agent.py`);
- Python 3.10+ and [uv](https://docs.astral.sh/uv/) (or plain `pip`, see below);
- outbound HTTPS to `wikimedia.org`, `*.wikipedia.org` and `www.wikidata.org`.

**Claude Code, for all your projects:**

```bash
git clone https://github.com/ANDRIYTS1234/wiki-interest ~/.claude/skills/wiki-interest
uv run --project ~/.claude/skills/wiki-interest wiki-interest doctor   # creates the venv once
```

**Claude Code, for one project** (the team gets it through the repository):

```bash
git clone https://github.com/ANDRIYTS1234/wiki-interest .claude/skills/wiki-interest
```

Restart the session; the skill is picked up by its description ("is interest in X growing in
Polish Wikipedia?") without naming it. Update with `git pull` in the skill folder.

**Without uv:** `python -m venv .venv && .venv/bin/pip install -e <skill folder>` (Windows:
`.venv\Scripts\pip`); SKILL.md explains the `python -m wiki_interest` form the agent then uses.

**Other agents:** give the model `SKILL.md` as instructions and the absolute path of the skill
folder as `SKILL_DIR`; everything else goes through the CLI.

Optional: `WIKI_INTEREST_CONTACT=<your email>` for the Wikimedia User-Agent. The cache is created
in the working folder (`./.wiki-interest-cache`), so repeated questions there are answered
without downloading again.

## Commands

Every command prints one JSON object to stdout (`"ok": true|false`), progress to stderr, and
writes artifacts to `--workdir` (default `./wiki-interest-out`). Titles are passed only in JSON
files, never as shell arguments.

| command | input | does |
|---|---|---|
| `resolve --input resolve.json` | queries or QIDs, languages | finds the article in each language; `ok` / `missing` / `disambiguation` / `redirect_resolved`, redirects, former titles; never picks a substitute |
| `fetch --spec analysis.json [--dry-run]` | baskets | daily views (user, automated, desktop) + edition totals into the SQLite cache; only missing ranges are requested |
| `analyze --spec analysis.json` | cached views | `metrics.json`: basket index (geometric mean, bootstrap CI), share change, leave-one-out / top-3 / median / spikes / anomalous months, alternative baselines, language comparisons, flags, separate direction and magnitude confidence |
| `report --narrative narrative.json [--metrics …] [--out …]` | metrics + agent text | one-page PDF at a stable path (`<workdir>/report.pdf`; a follow-up overwrites it), every quality flag and "do not compare" printed automatically, fails rather than truncates; chart PNG, `appendix.md` with methodology and all flags |
| `doctor` | — | environment check |

Exit codes: 0 ok, 2 invalid input, 3 network, 4 rate limit, 5 incomplete data, 1 other.

## Offline demo

`examples/B-fasting/` contains a cache snapshot (pl vs cs, intermittent fasting, 24-month window),
the spec, the agent's narrative and the resulting report in `out/`:

```bash
cp -r examples/B-fasting/cache demo-cache   # work on a copy: opening a cache writes to it
uv run wiki-interest --cache-dir demo-cache --workdir demo analyze --spec examples/B-fasting/analysis.json
uv run wiki-interest --cache-dir demo-cache --workdir demo report --narrative examples/B-fasting/narrative.json
```

`examples/A-astronomy/` is a larger spec (20 + 10 Wikidata items) with its narrative and the report from a
live run in `out/`; no cache snapshot (it needs a few minutes of live fetch).

## Tests

```bash
uv run pytest
```

HTTP is mocked at the session level with responses recorded from the real APIs
(`tests/record_fixtures.py`, not run in CI). `tests/test_e2e_offline.py` runs analyze → report on
the demo snapshot with every network call forbidden and checks the PDF has exactly one page.

## Evals

`evals/scenarios.yaml` lists scenarios A–E with checks (critical or not) and the result of a
baseline run without the skill; `evals/baseline/` has the protocols. `evals/run_agent.py` is a
minimal agent loop over OpenRouter with one `shell` tool, to run the same scenario with and
without the skill on a cheap model:

```bash
export OPENROUTER_API_KEY=...
uv run evals/run_agent.py --scenario B --mode skill    --model anthropic/claude-haiku-4.5
uv run evals/run_agent.py --scenario B --mode baseline --model anthropic/claude-haiku-4.5
```

Each run writes `evals/runs/<utc>_<scenario>_<mode>_<model>/`: `events.jsonl` (every model and
tool call with tokens and timing), `transcript.md`, `summary.json` (steps, tokens, cost, time,
final answer, checks to grade by hand) and `sandbox/` with the agent's files. The model executes
real shell commands: use a disposable machine or container.

## Layout

```
SKILL.md, references/      the skill: workflow and rules for the agent
src/wiki_interest/         CLI: resolve, fetch, analyze/, report/, cache, http
tests/                     unit, regression (resolve cases from the baselines), offline e2e
examples/                  demo specs, narrative, cache snapshot
docs/                      assignment, code contract (SPEC), development, roadmap
evals/                     baseline protocols, scenarios and trigger checks, agent runner
```

## Development and roadmap

- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — how the skill was built: baseline failures and what closes
  each, how the AI-written code was checked (with the per-stage log in
  [evals/verification-log.md](evals/verification-log.md)), runs on Haiku, results table.
- [docs/ROADMAP.md](docs/ROADMAP.md) — how to grow it: the iteration loop and the next stages
  (automatic basket suggestion, ranking many audiences, larger data volumes).
