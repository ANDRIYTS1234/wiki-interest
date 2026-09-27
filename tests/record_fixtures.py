"""Record real API responses as test fixtures. Not run in CI.

    uv run python tests/record_fixtures.py            # all cases
    uv run python tests/record_fixtures.py resolve/mars_uk fetch/neutron_uk   # selected cases

Each case runs the real code against the live APIs with an empty cache and a recording
session. Every request/response pair is stored in tests/fixtures/<group>/<case>.json, keyed by
the canonical URL. resolve cases run Resolver on one input; fetch cases run `wiki-interest fetch`
for a sequence of specs sharing one cache (so later steps record only the missing ranges). Tests replay them; a request missing from a fixture fails the test,
so after changing which requests resolve makes, re-record.

Set WIKI_INTEREST_CONTACT before recording so Wikimedia can reach you.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiki_interest.cache import Cache  # noqa: E402
from wiki_interest.cli import main as cli_main  # noqa: E402
from wiki_interest.config import load_settings  # noqa: E402
from wiki_interest.http import HttpClient, canonical_url  # noqa: E402
from wiki_interest.resolve import Resolver  # noqa: E402
from wiki_interest.schemas import parse_resolve_request  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

# Regression cases from SPEC §6 (baseline failures) plus the SPEC input example.
CASES: dict[str, dict[str, Any]] = {
    # uk «Марс» is a disambiguation page; the planet article was moved from «Марс» in 2015.
    "mars_uk": {
        "items": [{"lang": "uk", "title": "Марс"}, {"lang": "uk", "title": "Марс (планета)"}, {"query": "Марс", "query_lang": "uk"}],
        "langs": ["uk"],
    },
    # Intermittent fasting: no pl article (baseline B), cs exists; query from the SPEC example.
    "fasting_pl_cs": {
        "items": [{"qid": "Q1666254"}, {"query": "інтервальне голодування", "query_lang": "uk"}],
        "langs": ["pl", "cs"],
    },
    # es «Reglas del ajedrez» is a redirect to «Leyes del ajedrez» (baseline D); de had a 404 there.
    "chess_rules_es": {
        "items": [{"lang": "es", "title": "Reglas del ajedrez"}],
        "langs": ["es", "de", "pt"],
    },
    # uk «Нейтронна зірка» -> «Нейтронна зоря» (2021); «Сузір'я» has an apostrophe (broke bash in baseline A).
    "neutron_star_uk": {
        "items": [{"lang": "uk", "title": "Нейтронна зоря"}, {"lang": "uk", "title": "Сузір'я"}],
        "langs": ["uk"],
    },
    # A well-formed QID that does not exist must be reported, not dropped.
    "unknown_qid": {
        "items": [{"qid": "Q999999999999"}],
        "langs": ["uk"],
    },
}


def _fetch_spec(end: str, history_start: str, langs: list[str], items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    return {
        "question": "fixture",
        "langs": langs,
        "window": {"months": 1, "end": end},
        "history_start": history_start,
        "baskets": [{"id": "target", "role": "target", "label": label, "items": items}],
    }


# Explicit window ends keep fixtures stable over time. Short ranges keep them small.
FETCH_CASES: dict[str, list[dict[str, Any]]] = {
    # Step 2 extends the end by one month: only that month may be requested.
    "neutron_uk": [
        _fetch_spec("2026-07", "2025-08", ["uk"], [{"lang": "uk", "title": "Нейтронна зоря"}], "Нейтронна зоря"),
        _fetch_spec("2026-08", "2025-08", ["uk"], [{"lang": "uk", "title": "Нейтронна зоря"}], "Нейтронна зоря"),
    ],
    # No pl article for Q1666254 (missing_articles), explicit pl proxy, cs article.
    "fasting_pl_cs": [
        _fetch_spec(
            "2026-08", "2025-08", ["pl", "cs"],
            [{"qid": "Q1666254"}, {"lang": "pl", "title": "Głodówka lecznicza", "proxy_for": "Q1666254"}],
            "Intermittent fasting",
        ),
    ],
}


# Single raw requests for behaviours that full runs rarely hit.
RAW_CASES: dict[str, list[str]] = {
    # A redirect confirmed by resolve with no views on these days: the API answers 404.
    "pageviews_404": [
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/uk.wikipedia/all-access/user/"
        "%D0%9D%D0%B5%D0%B9%D1%82%D1%80%D0%BE%D0%BD%D0%BD%D1%96_%D0%B7%D0%BE%D1%80%D1%96/daily/20260803/20260804",
    ],
}


def record_raw(name: str, urls: list[str]) -> Path:
    session = RecordingSession()
    for url in urls:
        session.get(url, timeout=30)
    return save("raw", name, urls, session, session.headers.get("User-Agent", ""), None)


class RecordingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.headers["User-Agent"] = load_settings().user_agent
        self.recorded: dict[str, dict[str, Any]] = {}

    def get(self, url: str, params: Any = None, **kw: Any) -> requests.Response:  # type: ignore[override]
        resp = super().get(url, params=params, **kw)
        key = canonical_url(url, dict(params or {}))
        try:
            body: Any = resp.json()
            entry = {"status": resp.status_code, "json": body}
        except ValueError:
            entry = {"status": resp.status_code, "text": resp.text}
        self.recorded[key] = entry
        return resp


def record(name: str, spec: dict[str, Any]) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        settings = load_settings(cache_dir=Path(tmp) / "cache", workdir=Path(tmp) / "out")
        session = RecordingSession()
        error = None
        with Cache(settings.cache_path) as cache:
            http = HttpClient(settings, session, cache)
            try:
                Resolver(http, cache).run(parse_resolve_request(spec))
            except Exception as exc:  # keep the responses: a failing case is still a regression case
                error = f"{type(exc).__name__}: {exc}"
                print(f"{name}: resolve raised {error}", file=sys.stderr)
    return save("resolve", name, spec, session, settings.user_agent, error)


def save(group: str, name: str, spec: Any, session: "RecordingSession", user_agent: str, error: str | None) -> Path:
    folder = FIXTURES / group
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    payload = {
        "case": name,
        "input": spec,
        "recorded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user_agent": user_agent,
        "error": error,
        "responses": dict(sorted(session.recorded.items())),
    }
    # Pageviews bodies are long lists: one response per line keeps files reviewable and small.
    head = {k: v for k, v in payload.items() if k != "responses"}
    lines = [json.dumps(head, ensure_ascii=False)[:-1] + ', "responses": {']
    items = list(payload["responses"].items())
    for i, (url, resp) in enumerate(items):
        sep = "," if i < len(items) - 1 else ""
        lines.append(f"{json.dumps(url, ensure_ascii=False)}: {json.dumps(resp, ensure_ascii=False, separators=(',', ':'))}{sep}")
    lines.append("}}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(path.read_text(encoding="utf-8"))  # must stay valid JSON
    print(f"{group}/{name}: {len(session.recorded)} responses -> {path.relative_to(ROOT)}", file=sys.stderr)
    return path


def record_fetch(name: str, steps: list[dict[str, Any]]) -> Path:
    session = RecordingSession()
    error = None
    with tempfile.TemporaryDirectory() as tmp:
        for i, spec in enumerate(steps):
            spec_path = Path(tmp) / f"step{i}.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            code = cli_main(
                ["--cache-dir", str(Path(tmp) / "cache"), "--workdir", str(Path(tmp) / "out"), "fetch", "--spec", str(spec_path)],
                session=session,
            )
            if code != 0:
                error = f"step {i} exited with {code}"
                print(f"{name}: {error}", file=sys.stderr)
    return save("fetch", name, steps, session, session.headers.get("User-Agent", ""), error)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    known = [f"resolve/{n}" for n in CASES] + [f"fetch/{n}" for n in FETCH_CASES] + [f"raw/{n}" for n in RAW_CASES]
    names = argv or known
    unknown = [n for n in names if n not in known]
    if unknown:
        print(f"unknown cases: {unknown}; known: {known}", file=sys.stderr)
        return 2
    for name in names:
        group, case = name.split("/", 1)
        if group == "resolve":
            record(case, CASES[case])
        elif group == "fetch":
            record_fetch(case, FETCH_CASES[case])
        else:
            record_raw(case, RAW_CASES[case])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
