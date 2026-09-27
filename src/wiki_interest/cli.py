"""Entry point: argument parsing, one compact JSON object on stdout, exit codes (SPEC §4).

stdout carries only the final JSON; progress logs and tracebacks go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from typing import Any, Callable

import requests

from . import __version__
from .cache import Cache
from .config import ENV_CONTACT, Settings, latest_full_month, load_settings
from .errors import InputError, NotImplementedCommand, WikiInterestError
from .http import HttpClient

log = logging.getLogger("wiki_interest")


class Context:
    """Per-invocation state: settings plus lazily opened cache and HTTP client."""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session
        self._cache: Cache | None = None
        self._http: HttpClient | None = None

    @property
    def cache(self) -> Cache:
        if self._cache is None:
            self._cache = Cache(self.settings.cache_path)
        return self._cache

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            self._http = HttpClient(self.settings, self.session, self.cache)
        return self._http

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InputError(message, hint=f"Run `wiki-interest {self._subcommand_hint()}--help`")

    def _subcommand_hint(self) -> str:
        parts = self.prog.split()
        return (parts[-1] + " ") if len(parts) > 1 else ""


def _global_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--cache-dir", default=default, help="cache folder (default: $WIKI_INTEREST_CACHE or ./.wiki-interest-cache)")
    parser.add_argument("--workdir", default=default, help="artifact folder (default: ./wiki-interest-out)")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="wiki-interest", description="Wikipedia pageview analysis for product decisions.")
    parser.add_argument("--version", action="version", version=__version__)
    _global_options(parser, suppress=False)
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    sub.required = True

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        _global_options(p, suppress=True)  # global options accepted after the command too
        return p

    p = add("doctor", "check Python, dependencies, font, cache, network and User-Agent contact")
    p.add_argument("--offline", action="store_true", help="skip network checks")

    p = add("resolve", "find a topic's articles in the requested languages")
    p.add_argument("--input", required=True, help="resolve.json")

    p = add("fetch", "download daily pageviews for all baskets into the cache")
    p.add_argument("--spec", required=True, help="analysis.json")
    p.add_argument("--allow-partial", action="store_true", help="continue when some series fail; record them as missing")

    p = add("analyze", "compute metrics.json from cached pageviews")
    p.add_argument("--spec", required=True, help="analysis.json")

    p = add("report", "render the one-page PDF, charts and appendix")
    p.add_argument("--metrics", required=True)
    p.add_argument("--narrative", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report-lang", choices=("uk", "en"), default="uk")
    return parser


def cmd_doctor(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    from .doctor import run_doctor

    return run_doctor(ctx.settings, ctx.session, offline=args.offline)


def _not_implemented(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    raise NotImplementedCommand(f"`{args.command}` is not implemented yet", hint="Available now: doctor")


COMMANDS: dict[str, Callable[[argparse.Namespace, Context], dict[str, Any]]] = {
    "doctor": cmd_doctor,
    "resolve": _not_implemented,
    "fetch": _not_implemented,
    "analyze": _not_implemented,
    "report": _not_implemented,
}


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


class _StderrHandler(logging.StreamHandler):
    """Always writes to the current sys.stderr (it may be replaced after setup)."""

    @property  # type: ignore[override]
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


def _setup_logging() -> None:
    if not log.handlers:
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("wiki-interest: %(levelname)s: %(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None, *, session: requests.Session | None = None) -> int:
    _force_utf8()
    _setup_logging()
    ctx: Context | None = None
    result: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    code = 0
    try:
        args = build_parser().parse_args(argv)
        settings = load_settings(getattr(args, "cache_dir", None), getattr(args, "workdir", None))
        if settings.contact.source != "env":
            log.warning(
                "%s is not set; User-Agent uses %s. Set it to your email or URL.",
                ENV_CONTACT,
                settings.contact.value or "no contact",
            )
        ctx = Context(settings, session)
        result = COMMANDS[args.command](args, ctx)
    except WikiInterestError as exc:
        error, code = exc.to_json(), exc.exit_code
        result = dict(exc.extra)
    except KeyboardInterrupt:
        error, code = {"code": "interrupted", "message": "Interrupted by user", "hint": "Rerun; cached data is kept"}, 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        error = {"code": "internal", "message": f"{type(exc).__name__}: {exc}", "hint": "Traceback is in stderr"}
        code = 1
    finally:
        if ctx is not None:
            ctx.close()

    payload: dict[str, Any] = {
        "ok": error is None,
        "tool_version": __version__,
        "data_as_of": result.pop("data_as_of", None) or latest_full_month(),
    }
    if error is not None:
        payload["error"] = error
    payload.update(result)
    emit(payload)
    return code


def run() -> None:
    sys.exit(main())
