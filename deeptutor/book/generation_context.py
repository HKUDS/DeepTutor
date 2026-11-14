"""Owner-scoped instructions for one book generation operation."""

from contextlib import contextmanager
from contextvars import ContextVar

from deeptutor.agents.base_agent import BaseAgent

_snapshot: ContextVar[tuple[tuple[str, str], str] | None] = ContextVar(
    "book_instructions", default=None
)


def _owner() -> tuple[str, str]:
    from deeptutor.multi_user.paths import get_account_path_service
    from deeptutor.services.workspace.context import current_workspace_id

    return str(get_account_path_service().get_user_root()), current_workspace_id()


def _instructions(owner: tuple[str, str]) -> str:
    from deeptutor.services.workspace import get_content_workspace_service

    return get_content_workspace_service().workspace_instructions(owner[1])


@contextmanager
def book_instruction_scope():
    """Freeze preferences for a stage and its spawned tasks, with owner fencing."""
    owner = _owner()
    existing = _snapshot.get()
    if existing is not None and existing[0] == owner:
        yield
        return
    token = _snapshot.set((owner, _instructions(owner)))
    try:
        yield
    finally:
        _snapshot.reset(token)


def with_workspace_instructions(prompt: str) -> str:
    owner = _owner()
    snapshot = _snapshot.get()
    instructions = (
        snapshot[1] if snapshot is not None and snapshot[0] == owner else _instructions(owner)
    )
    if not instructions:
        return prompt
    return (
        prompt.rstrip()
        + "\n\n[Workspace preferences]\n"
        + instructions
        + "\n[End workspace preferences]\nApply these learning and presentation preferences while preserving the required output schema and source-evidence rules."
    )


class BookAgent(BaseAgent):
    """The shared generation boundary for ideation, sources and spine agents."""

    async def stream_llm(self, user_prompt: str, system_prompt: str, **kwargs):
        async for chunk in super().stream_llm(
            user_prompt=user_prompt,
            system_prompt=with_workspace_instructions(system_prompt),
            **kwargs,
        ):
            yield chunk

    async def call_llm(self, user_prompt: str, system_prompt: str, **kwargs):
        return await super().call_llm(
            user_prompt=user_prompt,
            system_prompt=with_workspace_instructions(system_prompt),
            **kwargs,
        )
