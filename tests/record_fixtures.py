"""Record real API responses as test fixtures. Not run in CI.

    uv run python tests/record_fixtures.py            # all cases
    uv run python tests/record_fixtures.py mars_uk    # selected cases

Each case runs the real `resolve` code against the live APIs with an empty cache and a
recording session. Every request/response pair is stored in tests/fixtures/resolve/<case>.json,
keyed by the canonical URL. Tests replay them; a request missing from a fixture fails the test,
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
from wiki_interest.config import load_settings  # noqa: E402
from wiki_interest.http import HttpClient, canonical_url  # noqa: E402
from wiki_interest.resolve import Resolver  # noqa: E402
from wiki_interest.schemas import parse_resolve_request  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "resolve"

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


class RecordingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
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
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"{name}.json"
    payload = {
        "case": name,
        "input": spec,
        "recorded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user_agent": settings.user_agent,
        "error": error,
        "responses": dict(sorted(session.recorded.items())),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: {len(session.recorded)} responses -> {path.relative_to(ROOT)}", file=sys.stderr)
    return path


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    names = argv or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print(f"unknown cases: {unknown}; known: {list(CASES)}", file=sys.stderr)
        return 2
    for name in names:
        record(name, CASES[name])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
