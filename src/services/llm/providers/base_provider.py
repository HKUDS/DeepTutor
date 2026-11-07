"""Base LLM provider with unified configuration and retries."""

from abc import ABC
from collections.abc import Awaitable, Callable
import logging
from typing import TypeVar

import tenacity
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from src.utils.error_rate_tracker import record_provider_call
from src.utils.network.circuit_breaker import (
    is_call_allowed,
    record_call_failure,
    record_call_success,
)

from ..config import LLMConfig
from ..error_mapping import map_error
from ..exceptions import (
    LLMAPIError,
    LLMCircuitBreakerError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from ..traffic_control import TrafficController
from ..types import AsyncStreamGenerator, TutorResponse

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Cap retry delays to avoid excessive waits during outages.
MAX_RETRY_DELAY_SECONDS = 60.0
BASE_RETRY_DELAY_SECONDS = 1.0


class BaseLLMProvider(ABC):
    """Base class for all LLM providers with unified config and retries."""

    def __init__(self, config: LLMConfig) -> None:
        """Initialize provider with shared configuration and traffic control."""
        self.config = config
        self.provider_name = config.provider_name
        self.api_key = getattr(config, "get_api_key", lambda: config.api_key)()
        self.base_url = config.base_url or config.effective_url

        # Isolation: Each provider gets its own traffic controller instance
        self.traffic_controller: TrafficController
        traffic_controller = getattr(config, "traffic_controller", None)
        if isinstance(traffic_controller, TrafficController):
            self.traffic_controller = traffic_controller
        else:
            self.traffic_controller = TrafficController(
                provider_name=self.provider_name,
                max_concurrency=getattr(config, "max_concurrency", 20),
                requests_per_minute=getattr(config, "requests_per_minute", 600),
            )

    async def complete(self, prompt: str, **kwargs: object) -> TutorResponse:
        """Run a completion call for the provider."""
        raise NotImplementedError

    def stream(self, prompt: str, **kwargs: object) -> AsyncStreamGenerator:
        """Return an async generator for streaming completions."""
        raise NotImplementedError

    def _map_exception(self, e: Exception) -> LLMError:
        return map_error(e, provider=self.provider_name)

    def calculate_cost(self, usage: dict[str, object]) -> float:
        """Calculate cost estimate for a provider call."""
        return 0.0

    def _check_circuit_breaker(self) -> None:
        """Raise when the circuit breaker is open for this provider."""
        if not is_call_allowed(self.provider_name):
            record_provider_call(self.provider_name, success=False)
            error = LLMCircuitBreakerError(
                f"Circuit breaker open for provider {self.provider_name}",
                provider=self.provider_name,
            )
            setattr(error, "is_circuit_breaker", True)
            raise error

    def _should_record_failure(self, error: LLMError) -> bool:
        """Return True when failures should trip the circuit breaker."""
        if isinstance(error, (LLMRateLimitError, LLMTimeoutError)):
            return True
        if isinstance(error, LLMAPIError):
            status_code = error.status_code
            if status_code is None:
                return True
            return status_code >= 500
        return False

    def _should_retry_error(self, error: BaseException) -> bool:
        """Return True when an error should trigger a retry."""
        if isinstance(error, (LLMRateLimitError, LLMTimeoutError)):
            return True
        if isinstance(error, LLMAPIError):
            status_code = error.status_code
            if status_code is None:
                return True
            return status_code >= 500
        return False

    def _wait_strategy(self, retry_state: tenacity.RetryCallState) -> float:
        """Return the next retry delay based on error context."""
        outcome = retry_state.outcome
        if outcome is None:
            return BASE_RETRY_DELAY_SECONDS
        exc = outcome.exception()
        if exc is None:
            return BASE_RETRY_DELAY_SECONDS
        if isinstance(exc, LLMRateLimitError):
            retry_after = getattr(exc, "retry_after", None)
            retry_after_value: float | None = None
            if retry_after is not None:
                try:
                    retry_after_value = float(retry_after)
                except (TypeError, ValueError):
                    retry_after_value = None
            if retry_after_value is not None:
                return max(0.0, min(retry_after_value, MAX_RETRY_DELAY_SECONDS))

        wait_fn = tenacity.wait_exponential(
            multiplier=1.5,
            min=BASE_RETRY_DELAY_SECONDS,
            max=MAX_RETRY_DELAY_SECONDS,
        )
        return float(wait_fn(retry_state))

    async def _execute_core(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """
        Core execution pipeline:
        1) circuit breaker check
        2) traffic control context
        3) call execution
        4) mapping + metrics
        """
        self._check_circuit_breaker()

        try:
            async with self.traffic_controller:
                result = await func(*args, **kwargs)
                record_provider_call(self.provider_name, success=True)
                record_call_success(self.provider_name)
                return result
        except Exception as exc:
            mapped_exc = self._map_exception(exc)
            record_provider_call(self.provider_name, success=False)
            if isinstance(mapped_exc, LLMError):
                if self._should_record_failure(mapped_exc):
                    record_call_failure(self.provider_name)
                raise mapped_exc from exc
            # Internal/runtime errors should bubble up without being rewrapped.
            raise mapped_exc

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Execute a single attempt without retry."""
        return await self._execute_core(func, *args, **kwargs)

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[T]],
        *args: object,
        max_retries: int = 3,
        sleep: Callable[[int | float], Awaitable[None] | None] | None = None,
        **kwargs: object,
    ) -> T:
        """Execute with automatic retries using tenacity."""

        def _default_sleep(_delay: int | float) -> None:
            return None

        sleep_fn: Callable[[int | float], Awaitable[None] | None]
        sleep_fn = _default_sleep if sleep is None else sleep

        retrying = AsyncRetrying(
            stop=stop_after_attempt(max_retries + 1),
            wait=self._wait_strategy,
            retry=retry_if_exception(self._should_retry_error),
            reraise=True,
            before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
            sleep=sleep_fn,
        )

        async for attempt in retrying:
            with attempt:
                return await self._execute_core(func, *args, **kwargs)

        raise RuntimeError("Retry loop exited without returning")
