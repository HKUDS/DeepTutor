"""Background compilation must not inherit a request's scoped LLM config.

`asyncio.create_task` copies the context it is created in. The book worker is
created inside whichever request first enqueued a page, so a per-run model pick
made by that one request would otherwise pin every chapter the worker compiles
for the rest of its life — invisibly, since generated prose does not say which
model wrote it.
"""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.services.llm.config import (
    _SCOPED_LLM_CONFIG,
    set_scoped_llm_config,
)


@pytest.mark.asyncio
async def test_a_task_inherits_its_creators_scope() -> None:
    """The hazard itself — asserted so the fix below has a stated premise."""

    async def observe() -> object:
        await asyncio.sleep(0)
        return _SCOPED_LLM_CONFIG.get()

    token = set_scoped_llm_config("request-scoped")  # type: ignore[arg-type]
    task = asyncio.create_task(observe())
    _SCOPED_LLM_CONFIG.reset(token)

    assert _SCOPED_LLM_CONFIG.get() is None, "the request's scope has ended"
    assert await task == "request-scoped", (
        "a task created inside that request still sees it — this is why the "
        "worker clears the scope explicitly"
    )


@pytest.mark.asyncio
async def test_clearing_the_scope_inside_the_task_restores_the_default() -> None:
    """What `_worker_loop` does on entry."""

    async def worker_entry() -> object:
        set_scoped_llm_config(None)
        await asyncio.sleep(0)
        return _SCOPED_LLM_CONFIG.get()

    token = set_scoped_llm_config("request-scoped")  # type: ignore[arg-type]
    task = asyncio.create_task(worker_entry())
    _SCOPED_LLM_CONFIG.reset(token)

    assert await task is None, "the worker must fall back to the user's config"


def test_the_worker_actually_clears_it() -> None:
    """Guards the call site, not just the mechanism."""
    import inspect

    from deeptutor.book.engine import BookEngine

    source = inspect.getsource(BookEngine._worker_loop)
    assert "set_scoped_llm_config(None)" in source
