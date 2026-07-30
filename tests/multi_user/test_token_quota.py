"""Token quota reservations and client-level enforcement."""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.multi_user.token_quota import (
    QuotaExceeded,
    ResourceQuotaLedger,
    ResourceQuotaPolicy,
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


def test_resource_ledger_keeps_embedding_and_mineru_budgets_separate(tmp_path) -> None:
    ledger = ResourceQuotaLedger(tmp_path / "usage.sqlite3")
    embedding = ResourceQuotaPolicy(
        resource="embedding",
        unit="tokens",
        daily_limit=100,
        monthly_limit=1000,
    )
    mineru = ResourceQuotaPolicy(
        resource="mineru",
        unit="pages",
        daily_limit=2,
        monthly_limit=10,
        per_request_limit=2,
    )

    embedding_lease = ledger.reserve("u_alice", 100, embedding)
    assert embedding_lease is not None
    embedding_lease.finalize(40)

    mineru_lease = ledger.reserve("u_alice", 2, mineru)
    assert mineru_lease is not None
    mineru_lease.finalize(2)

    with pytest.raises(QuotaExceeded, match="Mineru quota exceeded"):
        ledger.reserve("u_alice", 1, mineru)


def test_resource_ledger_enforces_per_request_limit(tmp_path) -> None:
    ledger = ResourceQuotaLedger(tmp_path / "usage.sqlite3")
    policy = ResourceQuotaPolicy(
        resource="mineru",
        unit="pages",
        daily_limit=0,
        monthly_limit=0,
        per_request_limit=5,
    )
    with pytest.raises(QuotaExceeded, match="per_request"):
        ledger.reserve("u_alice", 6, policy)


def test_embedding_client_reserves_embedding_tokens_before_provider_call(
    as_user, tmp_path, monkeypatch
) -> None:
    from deeptutor.multi_user import grants, token_quota
    from deeptutor.services.embedding.adapters.base import EmbeddingResponse
    from deeptutor.services.embedding.client import EmbeddingClient
    from deeptutor.services.embedding.config import EmbeddingConfig

    monkeypatch.setattr(token_quota, "quota_db_path", lambda: tmp_path / "usage.sqlite3")
    monkeypatch.setattr(
        grants,
        "load_grant",
        lambda _user_id: {
            "quota": {
                "llm": {"daily_tokens": 100, "monthly_tokens": 1000},
                "embedding": {"daily_tokens": 5, "monthly_tokens": 100},
                "mineru": {
                    "daily_pages": 50,
                    "monthly_pages": 500,
                    "max_pages_per_file": 50,
                },
            }
        },
    )

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, _request):
            self.calls += 1
            return EmbeddingResponse(
                embeddings=[[0.1]],
                model="stub",
                dimensions=1,
                usage={"total_tokens": 4},
            )

    client = EmbeddingClient(
        EmbeddingConfig(
            model="stub",
            api_key="sk-test",
            base_url="https://example.invalid/v1/embeddings",
            effective_url="https://example.invalid/v1/embeddings",
            binding="openai",
        )
    )
    adapter = FakeAdapter()
    client.adapter = adapter

    with as_user("u_alice"):
        asyncio.run(client.embed(["x" * 14]))
        with pytest.raises(QuotaExceeded, match="Embedding quota exceeded"):
            asyncio.run(client.embed(["x" * 14]))

    assert adapter.calls == 1
    connection = sqlite3.connect(tmp_path / "usage.sqlite3")
    try:
        consumed = connection.execute(
            """
            SELECT consumed_units FROM resource_usage
            WHERE user_id = 'u_alice' AND resource = 'embedding'
            """
        ).fetchall()
    finally:
        connection.close()
    assert consumed and all(row[0] == 4 for row in consumed)


def test_mineru_reserves_pdf_pages_before_parse(as_user, tmp_path, monkeypatch) -> None:
    from pypdf import PdfWriter

    from deeptutor.multi_user import grants, token_quota
    from deeptutor.services.parsing.engines.mineru import backend
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError

    monkeypatch.setattr(token_quota, "quota_db_path", lambda: tmp_path / "usage.sqlite3")
    monkeypatch.setattr(
        grants,
        "load_grant",
        lambda _user_id: {
            "quota": {
                "llm": {"daily_tokens": 100, "monthly_tokens": 1000},
                "embedding": {"daily_tokens": 100, "monthly_tokens": 1000},
                "mineru": {
                    "daily_pages": 2,
                    "monthly_pages": 10,
                    "max_pages_per_file": 2,
                },
            }
        },
    )
    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    calls = 0

    def fake_parse_local(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return tmp_path / "parsed"

    monkeypatch.setattr(backend, "_parse_local", fake_parse_local)
    config = MinerUConfig(mode="local")

    with as_user("u_alice"):
        backend.parse_pdf_to_workdir(pdf_path, tmp_path / "output", config=config)
        with pytest.raises(MinerUError, match="Mineru quota exceeded"):
            backend.parse_pdf_to_workdir(pdf_path, tmp_path / "output-2", config=config)

    assert calls == 1
    connection = sqlite3.connect(tmp_path / "usage.sqlite3")
    try:
        consumed = connection.execute(
            """
            SELECT consumed_units FROM resource_usage
            WHERE user_id = 'u_alice' AND resource = 'mineru'
            """
        ).fetchall()
    finally:
        connection.close()
    assert consumed and all(row[0] == 2 for row in consumed)


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


def test_default_token_quota_reads_persisted_auth_setting(monkeypatch) -> None:
    from deeptutor.multi_user import token_quota
    from deeptutor.services import config as config_module

    monkeypatch.setattr(
        config_module,
        "load_auth_settings",
        lambda: {
            "default_token_quota": {
                "daily_tokens": 12_345,
                "monthly_tokens": 67_890,
            }
        },
    )

    assert token_quota.default_token_quota() == {
        "daily_tokens": 12_345,
        "monthly_tokens": 67_890,
    }
