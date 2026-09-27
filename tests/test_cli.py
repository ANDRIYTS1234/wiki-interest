from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FakeSession, make_response
from wiki_interest import __version__
from wiki_interest.cli import main

SRC = Path(__file__).resolve().parents[1] / "src"


def run_main(capsys, argv, **kw):
    code = main(argv, **kw)
    out, err = capsys.readouterr()
    lines = out.strip().splitlines()
    assert len(lines) == 1, f"stdout must be exactly one JSON line, got: {out!r}"
    return code, json.loads(lines[0]), err


def test_doctor_offline(capsys, isolated_env):
    code, out, err = run_main(capsys, ["doctor", "--offline"])
    assert code == 0
    assert out["ok"] is True
    assert out["tool_version"] == __version__
    assert len(out["data_as_of"]) == 7
    by_name = {c["name"]: c for c in out["checks"]}
    for name in ("python", "dependencies", "font", "cache"):
        assert by_name[name]["status"] == "ok", by_name[name]
    assert by_name["user_agent_contact"]["status"] == "warn"
    assert by_name["network:wikidata.org"]["status"] == "skipped"
    assert out["healthy"] is True
    assert "WIKI_INTEREST_CONTACT" in err  # warning goes to stderr, not stdout
    assert (isolated_env / "cache" / "cache.sqlite").is_file()


def test_doctor_network_checks_use_session(capsys, monkeypatch):
    monkeypatch.setenv("WIKI_INTEREST_CONTACT", "me@example.org")
    session = FakeSession(lambda url, params: make_response(200, {"ok": True}))
    code, out, _ = run_main(capsys, ["doctor"], session=session)
    assert code == 0 and out["healthy"] is True and out["warnings"] == []
    hosts = sorted(url.split("/")[2] for url, _ in session.calls)
    assert hosts == ["en.wikipedia.org", "wikimedia.org", "www.wikidata.org"]
    assert session.headers["User-Agent"].count("me@example.org") == 1


def test_doctor_reports_unreachable_domain(capsys):
    import requests

    def responder(url, params):
        if "wikidata" in url:
            raise requests.exceptions.ConnectionError("blocked")
        return make_response(200, {})

    code, out, _ = run_main(capsys, ["doctor"], session=FakeSession(responder))
    assert code == 1
    assert out["ok"] is False
    assert out["error"]["code"] == "doctor_failed"
    assert "network:wikidata.org" in out["error"]["hint"]
    assert out["healthy"] is False
    assert out["failed"] == ["network:wikidata.org"]
    assert out["warnings"] == ["user_agent_contact"]
    check = next(c for c in out["checks"] if c["name"] == "network:wikidata.org")
    assert "www.wikidata.org" in check["detail"] and check["hint"]


def test_pageviews_probe_spans_full_month():
    from wiki_interest.doctor import domain_probes

    assert domain_probes("2026-02")["wikimedia.org"].endswith("/monthly/2026020100/2026022800")
    assert domain_probes("2024-02")["wikimedia.org"].endswith("/monthly/2024020100/2024022900")


def test_doctor_cache_dir_option_after_command(capsys, tmp_path):
    code, out, _ = run_main(capsys, ["doctor", "--offline", "--cache-dir", str(tmp_path / "other")])
    assert code == 0
    assert (tmp_path / "other" / "cache.sqlite").is_file()


def test_invalid_arguments_exit_2_with_json(capsys):
    code, out, _ = run_main(capsys, ["resolve"])
    assert code == 2
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_input"
    assert "--input" in out["error"]["message"]
    assert out["tool_version"] == __version__


def test_unknown_command_exit_2(capsys):
    code, out, _ = run_main(capsys, ["frobnicate"])
    assert code == 2 and out["ok"] is False


@pytest.mark.parametrize("argv", [["analyze", "--spec", "x.json"]])
def test_not_implemented_commands(capsys, argv):
    code, out, _ = run_main(capsys, argv)
    assert code == 1 and out["error"]["code"] == "not_implemented"


def test_internal_error_traceback_to_stderr(capsys, monkeypatch):
    from wiki_interest import cli

    def boom(args, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli.COMMANDS, "doctor", boom)
    code, out, err = run_main(capsys, ["doctor"])
    assert code == 1
    assert out["error"]["code"] == "internal"
    assert "Traceback (most recent call last)" in err and "RuntimeError: kaboom" in err
    assert "Logging error" not in err
    assert "most recent call last" not in json.dumps(out)


def test_subprocess_stdout_is_utf8_json(tmp_path):
    """Real process, cp1251-hostile environment: stdout must still be UTF-8 JSON."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "cp1251"
    env["WIKI_INTEREST_CACHE"] = str(tmp_path / "Кеш з апострофом '")
    proc = subprocess.run(
        [sys.executable, "-m", "wiki_interest", "doctor", "--offline"],
        cwd=tmp_path,
        capture_output=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    out = json.loads(proc.stdout.decode("utf-8"))
    assert out["ok"] is True
    cache_check = next(c for c in out["checks"] if c["name"] == "cache")
    assert "Кеш з апострофом '" in cache_check["detail"]


def test_doctor_contact_messages(settings):
    from wiki_interest.config import Contact
    from wiki_interest.doctor import check_contact

    settings.contact = Contact(None, "none")
    status, detail, hint = check_contact(settings)
    assert status == "fail" and "4x slower" in detail and "WIKI_INTEREST_CONTACT" in hint
    settings.contact = Contact("https://github.com/ANDRIYTS1234/wiki-interest", "project_url")
    status, detail, _ = check_contact(settings)
    assert status == "warn" and "same as with an email" in detail
    settings.contact = Contact("me@example.org", "env")
    assert check_contact(settings)[0] == "ok"
