"""Error hierarchy. Each class maps to one CLI exit code (SPEC §4)."""

from __future__ import annotations

from typing import Any


class WikiInterestError(Exception):
    exit_code = 1
    code = "error"

    def __init__(
        self,
        message: str,
        hint: str = "",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if code:
            self.code = code
        self.details = details or {}
        # Top-level fields added next to "error" in the CLI output (e.g. doctor's checks).
        self.extra = extra or {}

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message, "hint": self.hint}
        if self.details:
            out["details"] = self.details
        return out


class InputError(WikiInterestError):
    exit_code = 2
    code = "invalid_input"


class NetworkError(WikiInterestError):
    """Network or domain unavailable, access denied, persistent 5xx, broken response."""

    exit_code = 3
    code = "network"


class RateLimitError(WikiInterestError):
    exit_code = 4
    code = "rate_limited"


class IncompleteDataError(WikiInterestError):
    exit_code = 5
    code = "incomplete_data"


class CacheError(WikiInterestError):
    code = "cache_unavailable"


class HttpStatusError(WikiInterestError):
    """Unexpected non-retryable HTTP status (e.g. 400, 404 where not allowed)."""

    code = "http_status"

    def __init__(self, message: str, hint: str = "", *, status: int, **kw: Any) -> None:
        super().__init__(message, hint, **kw)
        self.status = status


class NotImplementedCommand(WikiInterestError):
    code = "not_implemented"
