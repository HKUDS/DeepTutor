"""Lightweight public exceptions for the Book runtime."""


class BookPausedError(RuntimeError):
    """Raised when a paused book rejects compilation work."""


__all__ = ["BookPausedError"]
