"""In-process failed-login rate limiter."""

from __future__ import annotations

from collections import deque
import threading
import time

MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


class LoginRateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Too many failed login attempts; retry after {retry_after}s")


class LoginRateLimiter:
    def __init__(
        self,
        max_attempts: int = MAX_FAILED_ATTEMPTS,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def ensure_allowed(self, key: str, now: float | None = None) -> None:
        current = time.time() if now is None else now
        with self._lock:
            attempts = self._failures.get(key)
            if not attempts:
                return
            cutoff = current - self.window_seconds
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.max_attempts:
                retry_after = max(1, int(attempts[0] + self.window_seconds - current) or 1)
                raise LoginRateLimited(retry_after)

    def register_failure(self, key: str, now: float | None = None) -> None:
        current = time.time() if now is None else now
        with self._lock:
            self._failures.setdefault(key, deque()).append(current)

    def register_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()
