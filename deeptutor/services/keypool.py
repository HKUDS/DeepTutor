"""Thread-safe round-robin API key rotation with rate-limit cooldowns."""

from __future__ import annotations

from threading import Lock
from time import monotonic


class KeyPool:
    """Rotate keys and cool a key after two HTTP 429 responses."""

    def __init__(self, keys: list[str], cooldown_s: int = 60) -> None:
        self._keys = [str(key).strip() for key in keys if str(key).strip()]
        if not self._keys:
            raise ValueError("KeyPool requires at least one non-empty key")
        self._cooldown_s = max(0, cooldown_s)
        self._next_index = 0
        self._strikes = {key: 0 for key in self._keys}
        self._cooldown_until = {key: 0.0 for key in self._keys}
        self._lock = Lock()

    def next(self) -> str:
        """Return the next key, preferring one that is not cooling down.

        When every key is cooling we still return the one that recovers
        soonest instead of refusing to serve. The pool spreads load across
        keys; it is not a circuit breaker. Raising here would convert a
        retryable provider 429 into an unretryable application error for the
        whole cooldown window — and for the common single-key setup that means
        every LLM and embedding call failing for a full minute, which is
        strictly worse than letting the provider's own 429 surface and be
        retried. The caller (``_KeyRotatingCompletions.create``) already marks
        the strike and re-raises the real 429 on its second attempt.
        """
        with self._lock:
            now = monotonic()
            for offset in range(len(self._keys)):
                index = (self._next_index + offset) % len(self._keys)
                key = self._keys[index]
                if self._cooldown_until[key] > now:
                    continue
                if self._cooldown_until[key]:
                    self._cooldown_until[key] = 0.0
                    self._strikes[key] = 0
                self._next_index = (index + 1) % len(self._keys)
                return key
            return min(self._keys, key=lambda candidate: self._cooldown_until[candidate])

    def mark_429(self, key: str) -> None:
        """Record a rate limit; the second strike starts the cooldown."""
        with self._lock:
            if key not in self._strikes:
                return
            self._strikes[key] += 1
            if self._strikes[key] >= 2:
                self._cooldown_until[key] = monotonic() + self._cooldown_s


__all__ = ["KeyPool"]
