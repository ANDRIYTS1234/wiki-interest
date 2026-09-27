from __future__ import annotations

import datetime as dt

import pytest
import requests

from conftest import FakeSession, make_response
from wiki_interest.cache import Cache
from wiki_interest.errors import HttpStatusError, NetworkError, RateLimitError
from wiki_interest.http import HttpClient, canonical_url, parse_retry_after

URL = "https://uk.wikipedia.org/w/api.php"


def client(settings, session, clock, cache=None) -> HttpClient:
    return HttpClient(settings, session, cache, sleep=clock.sleep, clock=clock)


def test_user_agent_is_set_on_session(settings, clock):
    s = FakeSession([make_response(200, {})])
    client(settings, s, clock)
    assert s.headers["User-Agent"].startswith("wiki-interest/")
    assert "python-requests/" in s.headers["User-Agent"]


def test_min_interval_between_requests(settings, clock):
    s = FakeSession(lambda url, params: make_response(200, {"x": 1}))
    c = client(settings, s, clock)
    for _ in range(3):
        c.get_json(URL)
    assert clock.sleeps == [pytest.approx(0.25), pytest.approx(0.25)]
    assert c.requests_made == 3


def test_429_honours_retry_after_then_succeeds(settings, clock):
    s = FakeSession([make_response(429, headers={"Retry-After": "7"}), make_response(200, {"ok": 1})])
    c = client(settings, s, clock)
    assert c.get_json(URL) == {"ok": 1}
    assert 7.0 in clock.sleeps
    assert len(s.calls) == 2


def test_persistent_429_gives_rate_limit_error_after_6_attempts(settings, clock):
    s = FakeSession(lambda url, params: make_response(429))
    with pytest.raises(RateLimitError) as ei:
        client(settings, s, clock).get(URL)
    assert ei.value.exit_code == 4
    assert len(s.calls) == 6
    backoffs = [d for d in clock.sleeps if d != pytest.approx(0.25)]
    assert backoffs == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_persistent_5xx_gives_network_error(settings, clock):
    s = FakeSession(lambda url, params: make_response(503))
    with pytest.raises(NetworkError) as ei:
        client(settings, s, clock).get(URL)
    assert ei.value.exit_code == 3
    assert "uk.wikipedia.org" in ei.value.message
    assert len(s.calls) == 6


def test_connection_error_names_domain_without_retry(settings, clock):
    s = FakeSession([requests.exceptions.ConnectionError("Name or service not known")])
    with pytest.raises(NetworkError) as ei:
        client(settings, s, clock).get(URL)
    assert ei.value.exit_code == 3
    assert "uk.wikipedia.org" in ei.value.message
    assert len(s.calls) == 1


def test_timeout_is_retried(settings, clock):
    s = FakeSession([requests.exceptions.ReadTimeout("slow"), make_response(200, [1])])
    assert client(settings, s, clock).get_json(URL) == [1]


def test_access_denied_is_network_error(settings, clock):
    s = FakeSession([make_response(403, text="Forbidden")])
    with pytest.raises(NetworkError) as ei:
        client(settings, s, clock).get(URL)
    assert ei.value.code == "access_denied"
    assert ei.value.exit_code == 3


def test_non_json_body_is_an_error_not_empty_result(settings, clock):
    s = FakeSession([make_response(200, text="<html>Too many requests</html>")])
    with pytest.raises(NetworkError) as ei:
        client(settings, s, clock).get_json(URL)
    assert ei.value.code == "bad_response"


def test_unexpected_status_and_allowed_status(settings, clock):
    s = FakeSession([make_response(404, {"type": "not found"}), make_response(404, {"type": "not found"})])
    c = client(settings, s, clock)
    with pytest.raises(HttpStatusError) as ei:
        c.get(URL)
    assert ei.value.status == 404
    assert c.get(URL, allow_statuses=(200, 404)).status_code == 404


def test_get_json_cached_hits_cache_second_time(settings, clock):
    s = FakeSession(lambda url, params: make_response(200, {"title": "Сузір'я"}))
    with Cache(settings.cache_path) as cache:
        c = client(settings, s, clock, cache)
        a = c.get_json_cached(URL, {"titles": "Сузір'я", "action": "query"})
        b = c.get_json_cached(URL, {"action": "query", "titles": "Сузір'я"})
    assert a == b == {"title": "Сузір'я"}
    assert len(s.calls) == 1
    assert c.cache_hits == 1


def test_canonical_url_sorts_params():
    assert canonical_url(URL, {"b": 1, "a": "x y"}) == canonical_url(URL, {"a": "x y", "b": 1})


def test_parse_retry_after_forms():
    now = dt.datetime(2026, 9, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("Tue, 01 Sep 2026 12:00:30 GMT", now) == 30.0
    assert parse_retry_after("garbage") is None
    assert parse_retry_after(None) is None
