"""Optional parsing progress context, independent of knowledge storage."""

from __future__ import annotations

from contextvars import ContextVar
import re
from typing import Any, Protocol


class ParseProgress(Protocol):
    def phase(self, name: str, **kwargs: Any) -> None: ...
    def document(self, source: Any, status: str, **kwargs: Any) -> None: ...
    def check(self) -> None: ...


_CURRENT: ContextVar[ParseProgress | None] = ContextVar("indexing_run", default=None)


class IndexingCancelled(RuntimeError):
    pass


def current_run() -> ParseProgress | None:
    return _CURRENT.get()


def _redact(detail: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", str(detail))
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password|signature|authorization)\s*[=:]\s*)[^\s&]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r'(?i)(["\']?(?:api[_-]?key|token|secret|password|signature|authorization)["\']?\s*[:=]\s*)["\'][^"\']*["\']',
        r'\1"[redacted]"',
        text,
    )
    text = re.sub(r"(https?://)[^/\s@]+:[^/\s@]+@", r"\1[redacted]@", text)
    return text[-1600:]


def failure_code(exc: BaseException) -> str:
    text = str(exc).casefold()
    if isinstance(exc, (TimeoutError,)) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, MemoryError) or "out of memory" in text or "resource exhausted" in text:
        return "resource_exhaustion"
    if (
        isinstance(exc, (FileNotFoundError, ModuleNotFoundError))
        or "not installed" in text
        or "cli_missing" in text
    ):
        return "dependency_missing"
    if "unsupported" in text or "doesn't support" in text:
        return "unsupported_input"
    if "download" in text:
        return "model_download_failed"
    if "embedding" in text or "vector" in text:
        return "embedding_failed"
    if "no content" in text or "no output" in text or "invalid" in text:
        return "invalid_output"
    return "runtime_failure"
