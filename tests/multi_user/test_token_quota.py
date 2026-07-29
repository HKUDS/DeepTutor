"""Token quota reservations and client-level enforcement."""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.multi_user.token_quota import (
    TokenQuotaExceeded,
    TokenQuotaLedger,
    TokenQuotaPolicy,
)


def test_reservation_is_atomic_and_finalization_releases_estimate(tmp_path) -> None:
    ledger = TokenQuotaLedger(tmp_path / "usage.sqlite3")
    policy = TokenQuotaPolicy(daily_tokens=100, monthly_tokens=1000)

    lease = ledger.reserve("u_alice", 80, policy)
    assert lease is not None
    with pytest.raises(TokenQuotaExceeded):
        ledger.reserve("u_alice", 30, policy)

    lease.finalize(20)
    second = ledger.reserve("u_alice", 80, policy)
    assert second is not None
    second.release()


def test_users_have_independent_ledgers(tmp_path) -> None:
    ledger = TokenQuotaLedger(tmp_path / "usage.sqlite3")
    policy = TokenQuotaPolicy(daily_tokens=100, monthly_tokens=100)

    first = ledger.reserve("u_alice", 100, policy)
    second = ledger.reserve("u_bob", 100, policy)
    assert first is not None
    assert second is not None
    first.release()
    second.release()


def test_bounded_user_call_is_rejected_before_provider_call(as_user, tmp_path, monkeypatch) -> None:
    from deeptutor.core.agentic.client import _TokenQuotaCompletions
    from deeptutor.multi_user import token_quota

    monkeypatch.setattr(token_quota, "quota_db_path", lambda: tmp_path / "usage.sqlite3")
    calls: list[dict] = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=3, total_tokens=7)
            )

    with as_user("u_alice"):
        completions = _TokenQuotaCompletions(FakeCompletions())
        response = asyncio.run(
            completions.create(messages=[{"role": "user", "content": "hi"}], max_tokens=16)
        )
        assert response.usage.total_tokens == 7
        assert len(calls) == 1

        with pytest.raises(Exception, match="Token quota exceeded"):
            asyncio.run(
                completions.create(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=100_000,
                )
            )
        assert len(calls) == 1


def test_stream_reservation_is_finalized_after_iteration(as_user, tmp_path, monkeypatch) -> None:
    from deeptutor.core.agentic.client import _TokenQuotaCompletions
    from deeptutor.multi_user import token_quota

    monkeypatch.setattr(token_quota, "quota_db_path", lambda: tmp_path / "usage.sqlite3")

    class FakeStream:
        def __init__(self) -> None:
            self._chunks = iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="hello"),
                                finish_reason=None,
                            )
                        ],
                        usage=None,
                    ),
                    SimpleNamespace(
                        choices=[],
                        usage=SimpleNamespace(total_tokens=11),
                    ),
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeStream()

    async def run() -> None:
        with as_user("u_alice"):
            stream = await _TokenQuotaCompletions(FakeCompletions()).create(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=16,
                stream=True,
            )
            chunks = [chunk async for chunk in stream]
            assert len(chunks) == 2

    asyncio.run(run())
    connection = sqlite3.connect(tmp_path / "usage.sqlite3")
    try:
        consumed = connection.execute(
            "SELECT consumed_tokens FROM token_usage WHERE user_id = 'u_alice'"
        ).fetchall()
    finally:
        connection.close()
    assert consumed and all(row[0] == 11 for row in consumed)


def test_services_factory_path_is_quota_gated(as_user, tmp_path, monkeypatch) -> None:
    from deeptutor.multi_user import token_quota
    from deeptutor.services.llm import factory

    monkeypatch.setattr(token_quota, "quota_db_path", lambda: tmp_path / "usage.sqlite3")
    calls: list[dict] = []

    class FakeProvider:
        async def chat_with_retry(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content="ok",
                finish_reason="stop",
                usage={"total_tokens": 9},
            )

    monkeypatch.setattr(factory, "get_runtime_provider", lambda _config: FakeProvider())

    async def run() -> None:
        with as_user("u_alice"):
            result = await factory.complete(
                prompt="hello",
                model="gpt-4o-mini",
                api_key="sk-test",
                base_url="https://example.invalid/v1",
                binding="openai",
                max_tokens=16,
            )
            assert result == "ok"

    asyncio.run(run())
    assert len(calls) == 1
