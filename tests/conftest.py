"""Shared fixtures. HTTP is mocked at the session level: FakeSession replaces requests.Session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
import requests

from wiki_interest.config import load_settings


def make_response(
    status: int = 200,
    body: Any = None,
    *,
    text: str | None = None,
    headers: dict[str, str] | None = None,
    url: str = "https://example.invalid/",
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    if text is None:
        text = json.dumps(body if body is not None else {}, ensure_ascii=False)
    resp._content = text.encode("utf-8")
    resp.encoding = "utf-8"
    resp.headers.update(headers or {})
    resp.url = url
    return resp


class FakeSession:
    """Answers GETs from a handler or a queue; records every call."""

    def __init__(self, responder: Callable[[str, dict | None], Any] | list[Any]) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, Any]] = []
        self._responder = responder

    def get(self, url: str, params: Any = None, timeout: float | None = None) -> requests.Response:
        self.calls.append((url, params))
        if callable(self._responder):
            out = self._responder(url, params)
        else:
            out = self._responder.pop(0)
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, requests.Response) and out.url == "https://example.invalid/":
            out.url = url
        return out


class FakeClock:
    """Deterministic monotonic clock; sleep() advances it and records the delay."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test runs in its own folder with its own cache and no contact configured."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WIKI_INTEREST_CONTACT", raising=False)
    monkeypatch.delenv("WIKI_INTEREST_MIN_INTERVAL", raising=False)
    monkeypatch.setenv("WIKI_INTEREST_CACHE", str(tmp_path / "cache"))
    return tmp_path


@pytest.fixture
def settings(tmp_path: Path):
    return load_settings(cache_dir=tmp_path / "cache", workdir=tmp_path / "out")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
