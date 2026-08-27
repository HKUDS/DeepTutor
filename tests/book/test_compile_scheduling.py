"""Scheduling guarantees for book compilation.

Covers the two failure modes that were previously untested and invisible in
production: the same page being compiled twice concurrently (paid for twice,
one result silently discarded) and a book grinding on through a provider
outage until every chapter is half-generated.
"""

import asyncio

import pytest

from deeptutor.book.compiler import systemic_failure_reason
from deeptutor.book.engine import (
    CONSECUTIVE_PAGE_FAILURE_LIMIT,
    BookEngine,
    _BookRuntime,
)
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookStatus,
    Page,
    PageStatus,
)


def _engine() -> BookEngine:
    """A BookEngine with no storage/compiler wiring — scheduling only."""
    engine = BookEngine.__new__(BookEngine)
    engine._global_lock = asyncio.Lock()
    engine._runtimes = {}
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# In-flight coalescing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_requests_for_a_page_share_one_run() -> None:
    engine = _engine()
    started = 0
    release = asyncio.Event()

    async def fake_compile(*, book_id, page_id, stream=None, force=False):
        nonlocal started
        started += 1
        await release.wait()
        return Page(id=page_id, book_id=book_id)

    engine._compile_page_now = fake_compile

    waiters = [
        asyncio.create_task(engine.compile_page(book_id="bk", page_id="pg_1")) for _ in range(4)
    ]
    await asyncio.sleep(0)  # let them all reach the in-flight table
    release.set()
    pages = await asyncio.gather(*waiters)

    assert started == 1, "four readers opening the same page must not trigger four runs"
    assert {p.id for p in pages} == {"pg_1"}


@pytest.mark.asyncio
async def test_distinct_pages_do_not_block_each_other() -> None:
    engine = _engine()
    started: list[str] = []

    async def fake_compile(*, book_id, page_id, stream=None, force=False):
        started.append(page_id)
        return Page(id=page_id, book_id=book_id)

    engine._compile_page_now = fake_compile

    await asyncio.gather(
        engine.compile_page(book_id="bk", page_id="pg_1"),
        engine.compile_page(book_id="bk", page_id="pg_2"),
    )

    assert sorted(started) == ["pg_1", "pg_2"]


@pytest.mark.asyncio
async def test_force_waits_for_the_run_in_flight_then_starts_a_fresh_one() -> None:
    engine = _engine()
    calls: list[bool] = []
    release = asyncio.Event()

    async def fake_compile(*, book_id, page_id, stream=None, force=False):
        calls.append(force)
        if not force:
            await release.wait()
        return Page(id=page_id, book_id=book_id)

    engine._compile_page_now = fake_compile

    plain = asyncio.create_task(engine.compile_page(book_id="bk", page_id="pg_1"))
    await asyncio.sleep(0)
    forced = asyncio.create_task(engine.compile_page(book_id="bk", page_id="pg_1", force=True))
    await asyncio.sleep(0)

    assert calls == [False], "the forced pass must not interleave with the one in flight"
    release.set()
    await asyncio.gather(plain, forced)
    assert calls == [False, True]


@pytest.mark.asyncio
async def test_in_flight_entry_is_released_even_when_compilation_fails() -> None:
    engine = _engine()

    async def boom(*, book_id, page_id, stream=None, force=False):
        raise RuntimeError("provider exploded")

    engine._compile_page_now = boom

    with pytest.raises(RuntimeError):
        await engine.compile_page(book_id="bk", page_id="pg_1")

    runtime = engine._runtimes["bk"]
    await asyncio.sleep(0)  # let the done-callback run
    assert runtime.in_flight == {}, "a failed run must not wedge the page forever"


# ─────────────────────────────────────────────────────────────────────────────
# Breaker
# ─────────────────────────────────────────────────────────────────────────────


def _page_with_failures(*kinds: str) -> Page:
    return Page(
        id="pg_1",
        book_id="bk",
        status=PageStatus.ERROR,
        blocks=[
            Block(
                type=BlockType.TEXT,
                status=BlockStatus.ERROR,
                metadata={"failure": {"kind": kind, "message": f"{kind} happened"}},
            )
            for kind in kinds
        ],
    )


def test_provider_failures_are_systemic() -> None:
    assert systemic_failure_reason(_page_with_failures("rate_limit", "provider_error"))
    assert systemic_failure_reason(_page_with_failures("timeout", "timeout"))


def test_the_reason_names_the_failure_so_the_reader_can_act_on_it() -> None:
    reason = systemic_failure_reason(_page_with_failures("rate_limit", "rate_limit"))
    assert reason.startswith("rate_limit:")
    assert "happened" in reason


def test_content_failures_are_not_systemic() -> None:
    assert not systemic_failure_reason(_page_with_failures("json_parse", "empty_response"))
    assert not systemic_failure_reason(
        _page_with_failures("json_parse", "rate_limit", "json_parse")
    )
    assert not systemic_failure_reason(Page(id="pg_1", book_id="bk"))


@pytest.mark.asyncio
async def test_breaker_pauses_the_book_after_repeated_provider_failures(tmp_path) -> None:
    engine = _engine()
    runtime = _BookRuntime()
    engine._runtimes["bk"] = runtime

    saved: dict[str, Book] = {}
    logged: list[str] = []

    class _Storage:
        def load_book(self, book_id):
            return saved.get(book_id, Book(id="bk", status=BookStatus.COMPILING))

        def save_book(self, book):
            saved[book.id] = book

        def append_log(self, book_id, message, op="info"):
            logged.append(op)

    engine.storage = _Storage()

    page = _page_with_failures("rate_limit", "provider_error")
    tripped = False
    for _ in range(CONSECUTIVE_PAGE_FAILURE_LIMIT):
        tripped = await engine._record_page_outcome(runtime, "bk", page)

    assert tripped is True
    assert saved["bk"].status == BookStatus.PAUSED
    assert saved["bk"].metadata.get("pause_reason")
    assert "paused" in logged


@pytest.mark.asyncio
async def test_a_page_that_produced_something_resets_the_breaker() -> None:
    engine = _engine()
    runtime = _BookRuntime()
    runtime.consecutive_page_failures = CONSECUTIVE_PAGE_FAILURE_LIMIT - 1

    ok = Page(id="pg_2", book_id="bk", status=PageStatus.PARTIAL)
    tripped = await engine._record_page_outcome(runtime, "bk", ok)

    assert tripped is False
    assert runtime.consecutive_page_failures == 0


# ─────────────────────────────────────────────────────────────────────────────
# Path containment
# ─────────────────────────────────────────────────────────────────────────────


def test_book_ids_cannot_escape_the_workspace() -> None:
    """Ids arrive in request bodies and become directory names."""
    from deeptutor.book.storage import _safe_book_id

    assert _safe_book_id("bk_7c5634d091") == "bk_7c5634d091"

    for rejected in ("", "   ", "..", "///", "../../etc/passwd", "bk_1/../../x"):
        with pytest.raises(ValueError):
            _safe_book_id(rejected)
