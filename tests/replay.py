"""Replay recorded API fixtures (see record_fixtures.py) through a FakeSession."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import FakeSession, make_response
from wiki_interest.http import canonical_url

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(group: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / group / f"{name}.json").read_text(encoding="utf-8"))


def replay_session(*fixtures: dict[str, Any]) -> FakeSession:
    responses: dict[str, dict[str, Any]] = {}
    for fx in fixtures:
        responses.update(fx["responses"])

    def responder(url: str, params: Any) -> Any:
        key = canonical_url(url, dict(params or {}))
        if key not in responses:
            raise AssertionError(
                f"request not in fixtures: {key}\nRe-record with `uv run python tests/record_fixtures.py`"
            )
        r = responses[key]
        if "json" in r:
            return make_response(r["status"], r["json"], url=key)
        return make_response(r["status"], text=r["text"], url=key)

    return FakeSession(responder)
