"""
Error Rate Tracker - Track error rates per provider with alerting.
"""

from collections import defaultdict, deque
import logging
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ErrorRateTracker:
    """
    Tracks error rates per provider with sliding window.
    """

    def __init__(
        self,
        window_size: int = 60,
        threshold: float = 0.5,
        alert_callback: Optional[Callable[[str, float], None]] = None,
    ):
        self.window_size = window_size  # seconds
        self.threshold = threshold  # failure rate threshold
        self.alert_callback = alert_callback
        self._lock = threading.RLock()  # Use RLock to allow reentrant locking
        self._errors: Dict[str, deque[float]] = defaultdict(deque)
        self._total_calls: Dict[str, deque[float]] = defaultdict(deque)
        self._alerted: Dict[str, bool] = defaultdict(bool)  # to avoid repeated alerts

    def record_call(self, provider: str, success: bool):
        """Record a call for the provider."""
        now = time.time()
        with self._lock:
            self._total_calls[provider].append(now)
            if not success:
                self._errors[provider].append(now)
            self._cleanup_old_entries(provider, now)
            self._check_alert(provider)

    def get_error_rate(self, provider: str) -> float:
        """Get current error rate for provider."""
        now = time.time()
        with self._lock:
            self._cleanup_old_entries(provider, now)
            total = len(self._total_calls[provider])
            errors = len(self._errors[provider])
            return errors / total if total > 0 else 0.0

    def check_threshold(self, provider: str) -> bool:
        """Check if error rate exceeds threshold."""
        rate = self.get_error_rate(provider)
        return rate > self.threshold

    def _check_alert(self, provider: str):
        """Check and trigger alert if needed."""
        rate = self.get_error_rate(provider)
        exceeds_threshold = rate > self.threshold
        if exceeds_threshold and not self._alerted[provider]:
            logger.warning(
                f"Provider {provider} error rate {rate:.2%} exceeds threshold {self.threshold:.2%}"
            )
            if self.alert_callback:
                self.alert_callback(provider, rate)
            self._alerted[provider] = True
        elif not exceeds_threshold:
            self._alerted[provider] = False  # reset when below threshold

    def _cleanup_old_entries(self, provider: str, now: float):
        """Remove entries older than window_size."""
        cutoff = now - self.window_size
        while self._total_calls[provider] and self._total_calls[provider][0] <= cutoff:
            self._total_calls[provider].popleft()
        while self._errors[provider] and self._errors[provider][0] <= cutoff:
            self._errors[provider].popleft()


# Global instance
tracker = ErrorRateTracker()

# Set alert callback to circuit breaker
try:
    from .network.circuit_breaker import alert_callback as cb

    tracker.alert_callback = cb
except ImportError as e:
    logging.getLogger(__name__).warning(
        f"Circuit breaker module not available: {e}. Error rate tracking will work but circuit breaker integration is disabled."
    )


def record_provider_call(provider: str, success: bool):
    """Global function to record a call."""
    tracker.record_call(provider, success)


def get_provider_error_rate(provider: str) -> float:
    """Get error rate for provider."""
    return tracker.get_error_rate(provider)


def check_provider_threshold(provider: str) -> bool:
    """Check if provider exceeds threshold."""
    return tracker.check_threshold(provider)


def set_alert_callback(callback: Callable[[str, float], None]):
    """Set the alert callback for the tracker."""
    tracker.alert_callback = callback
