"""Track request authorization without importing Desktop OAuth dependencies."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

BINDING = "openai_chatgpt_plan"
request_allowed: ContextVar[bool] = ContextVar("chatgpt_plan_request_allowed", default=False)
request_account_id: ContextVar[str | None] = ContextVar(
    "chatgpt_plan_request_account", default=None
)


class PlanError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@contextmanager
def request_scope(allowed: bool, *, account_id: str | None = None) -> Iterator[None]:
    allowed_token = request_allowed.set(allowed)
    account_token = request_account_id.set(account_id if allowed else None)
    try:
        yield
    finally:
        request_account_id.reset(account_token)
        request_allowed.reset(allowed_token)
