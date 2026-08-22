"""Unit tests for the LightRAG RAG pipeline + provider routing.

RAG-Anything / LightRAG is an optional dependency that is NOT installed in CI,
so these tests exercise everything that does not require the package (factory
routing, config bridge, storage, lifecycle gating, parse-layer consumption)
directly, and stub the thin ``engine`` adapter + the parse service to cover the
index/search orchestration without the heavy deps.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import logging
from pathlib import Path
import sys
import threading
import time
import types

import pytest

from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMConfigError,
    LLMParseError,
    LLMProviderTransportError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from deeptutor.services.rag.factory import (
    LIGHTRAG_PROVIDER,
    get_pipeline,
    list_pipelines,
    normalize_provider_name,
)
from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
from deeptutor.services.rag.pipelines.lightrag import config as lr_config
from deeptutor.services.rag.pipelines.lightrag import engine, storage
from deeptutor.services.rag.pipelines.lightrag.pipeline import LightRagPipeline
from deeptutor.services.rag.pipelines.lightrag.worker import run_in_worker_loop

# --------------------------------------------------------------------------- #
# factory routing + config
# --------------------------------------------------------------------------- #


def test_factory_dispatches_lightrag_lazily(tmp_path) -> None:
    pipe = get_pipeline("lightrag", kb_base_dir=str(tmp_path))
    assert type(pipe).__name__ == "LightRagPipeline"
    # Building the pipeline must NOT import the heavy optional dependency.
    assert "raganything" not in sys.modules


def test_list_pipelines_includes_lightrag(monkeypatch) -> None:
    monkeypatch.setattr(lr_config, "is_lightrag_available", lambda: False)
    entry = next(p for p in list_pipelines() if p["id"] == LIGHTRAG_PROVIDER)
    assert entry["requires_api_key"] is False
    assert entry["configured"] is False


def test_normalize_provider_keeps_lightrag() -> None:
    assert normalize_provider_name("lightrag") == "lightrag"
    assert normalize_provider_name("LightRAG") == "lightrag"


@pytest.mark.parametrize(
    "given,expected",
    [
        ("hybrid", "hybrid"),
        ("MIX", "mix"),
        ("naive", "naive"),
        ("local", "local"),
        ("global", "global"),
        ("", "hybrid"),
        (None, "hybrid"),
        ("bogus", "hybrid"),
    ],
)
def test_normalize_mode(given, expected) -> None:
    assert lr_config.normalize_mode(given) == expected


def test_is_lightrag_available_false_when_dependency_missing(monkeypatch) -> None:
    def fake_find_spec(name):
        return None if name == "raganything" else object()

    monkeypatch.setattr(lr_config.importlib.util, "find_spec", fake_find_spec)
    assert lr_config.is_lightrag_available() is False


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def test_storage_meta_and_has_output(tmp_path) -> None:
    root = tmp_path / "version-1"
    root.mkdir()
    assert storage.has_output(root) is False
    assert storage.has_output(None) is False

    (root / "vdb_chunks.json").write_text("{}", encoding="utf-8")
    assert storage.has_output(root) is False

    (root / "graph_chunk_entity_relation.graphml").write_text("<graph/>", encoding="utf-8")
    assert storage.has_output(root) is False

    (root / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "failed",
                    "file_path": "bad.docx",
                    "error_msg": "embedding failed",
                    "chunks_list": [],
                }
            }
        ),
        encoding="utf-8",
    )
    assert storage.has_output(root) is False
    assert storage.failure_summary(root) == "bad.docx: embedding failed"
    assert storage.document_error(root, "doc-1") == "embedding failed"

    (root / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "processed",
                    "file_path": "good.docx",
                    "chunks_list": ["chunk-1"],
                }
            }
        ),
        encoding="utf-8",
    )
    assert storage.has_output(root) is True

    storage.write_meta(root)
    meta = json.loads((root / storage.META_FILENAME).read_text())
    assert meta["signature"] == "lightrag"
    assert meta["provider"] == "lightrag"


class _FakeEmbeddingFunc:
    """Stands in for ``lightrag.utils.EmbeddingFunc``.

    Its signature is deliberately limited to the real dataclass's fields, so a
    constructor kwarg the pinned dependency does not accept fails here too.
    ``test_fake_embedding_func_matches_the_real_dataclass`` pins the two
    together whenever LightRAG is installed.
    """

    def __init__(
        self,
        *,
        embedding_dim,
        func,
        max_token_size=8192,
        send_dimensions=None,
        model_name=None,
    ) -> None:
        self.embedding_dim = embedding_dim
        self.func = func
        self.max_token_size = max_token_size
        self.send_dimensions = send_dimensions
        self.model_name = model_name


class _RecordingBridge:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, factory):
        self.calls += 1
        return await factory()


def _install_fake_lightrag(monkeypatch) -> None:
    fake_lightrag = types.ModuleType("lightrag")
    fake_utils = types.ModuleType("lightrag.utils")
    fake_utils.EmbeddingFunc = _FakeEmbeddingFunc
    monkeypatch.setitem(sys.modules, "lightrag", fake_lightrag)
    monkeypatch.setitem(sys.modules, "lightrag.utils", fake_utils)


def test_fake_embedding_func_matches_the_real_dataclass() -> None:
    """Guard against the stub drifting from the dependency it stands in for."""
    import dataclasses

    lightrag_utils = pytest.importorskip("lightrag.utils")

    real_fields = {field.name for field in dataclasses.fields(lightrag_utils.EmbeddingFunc)}
    stub_fields = set(inspect.signature(_FakeEmbeddingFunc.__init__).parameters.keys() - {"self"})
    assert stub_fields == real_fields


def test_embedding_func_returns_numpy_array(monkeypatch) -> None:
    _install_fake_lightrag(monkeypatch)

    class _Config:
        dim = 3
        max_tokens = 99

    class _Client:
        async def embed(self, texts, *, input_type=None):
            del input_type
            return [[1, 2, 3] for _ in texts]

    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_config", lambda: _Config())
    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_client", lambda: _Client())

    bridge = _RecordingBridge()
    embedding = lr_config.build_embedding_func(io_bridge=bridge)
    vectors = asyncio.run(embedding.func(["a", "b"]))
    assert embedding.embedding_dim == 3
    assert embedding.max_token_size == 99
    assert vectors.shape == (2, 3)
    assert hasattr(vectors, "size")
    assert bridge.calls == 1


def test_embedding_func_maps_lightrag_query_and_document_context(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None]] = []
    _install_fake_lightrag(monkeypatch)

    class _Config:
        dim = 3
        max_tokens = 99

    class _Client:
        async def embed(self, texts, *, input_type=None):
            calls.append((list(texts), input_type))
            return [[1, 2, 3] for _ in texts]

    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_config", lambda: _Config())
    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_client", lambda: _Client())

    embedding = lr_config.build_embedding_func()
    asyncio.run(embedding.func(["question"], context="query", _priority=1))
    asyncio.run(embedding.func(["passage"], context="document"))
    # The pinned LightRAG passes no context at all; that must mean "no role",
    # not "document", or every query would be embedded as a passage.
    asyncio.run(embedding.func(["unlabelled"]))

    assert calls == [
        (["question"], "search_query"),
        (["passage"], "search_document"),
        (["unlabelled"], None),
    ]


def test_lightrag_llm_adapter_preserves_messages_and_drops_extra_kwargs(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def get_model_func(self):
            async def model_func(prompt, **kwargs):
                captured["prompt"] = prompt
                captured.update(kwargs)
                return "ok"

            return model_func

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())

    bridge = _RecordingBridge()
    func = lr_config.build_llm_model_func(io_bridge=bridge)
    result = asyncio.run(
        func(
            "",
            system_prompt="sys",
            messages=[{"role": "user", "content": "from messages"}],
            response_format={"type": "json_object"},
            hashing_kv=object(),
            keyword_extraction=True,
        )
    )

    assert result == "ok"
    assert captured["prompt"] == ""
    assert captured["system_prompt"] == "sys"
    assert captured["history_messages"] == []
    assert captured["messages"] == [{"role": "user", "content": "from messages"}]
    assert captured["max_retries"] == 0
    assert captured["allow_image_fallback"] is False
    assert "response_format" not in captured
    assert "hashing_kv" not in captured
    assert "keyword_extraction" not in captured
    assert bridge.calls == 1


def test_lightrag_vision_adapter_preserves_messages(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def get_vision_model_func(self):
            async def model_func(prompt, **kwargs):
                captured["prompt"] = prompt
                captured.update(kwargs)
                return "ok"

            return model_func

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())

    bridge = _RecordingBridge()
    func = lr_config.build_vision_model_func(io_bridge=bridge)
    result = asyncio.run(
        func(
            "",
            image_data="abc123",
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        )
    )

    assert result == "ok"
    assert captured["prompt"] == ""
    assert captured["image_data"] == "abc123"
    assert captured["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    assert captured["max_retries"] == 0
    assert captured["allow_image_fallback"] is False
    assert bridge.calls == 1


def test_lightrag_llm_adapter_uses_three_total_attempts_and_disables_provider_retry(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    sleep_delays: list[float] = []
    failures = [
        LLMAPIError("temporary server error", status_code=503),
        LLMRateLimitError("rate limited"),
    ]

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **kwargs):
                calls.append(kwargs)
                if failures:
                    raise failures.pop(0)
                return "ok"

            return model_func

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)

    bridge = _RecordingBridge()
    func = lr_config.build_llm_model_func(io_bridge=bridge)

    assert asyncio.run(func("prompt")) == "ok"
    assert len(calls) == 3
    assert [call["max_retries"] for call in calls] == [0, 0, 0]
    assert sleep_delays == [1.0, 2.0]
    assert bridge.calls == 3


@pytest.mark.parametrize(
    "error",
    [
        LLMTimeoutError("timeout"),
        LLMProviderTransportError("provider transport failed"),
        TimeoutError("timeout"),
        ConnectionError("connection"),
        LLMRateLimitError("rate limited"),
        LLMAPIError("temporary server error", status_code=500),
        LLMAPIError("temporary overload", status_code=529),
        LLMAPIError("Error calling Codex: Codex returned HTTP 503."),
        LLMAPIError("Error code: 529 - overloaded_error"),
    ],
)
def test_lightrag_adapter_retries_classified_transient_errors(monkeypatch, error) -> None:
    calls = 0

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise error
                return "ok"

            return model_func

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)

    assert asyncio.run(lr_config.build_llm_model_func()("prompt")) == "ok"
    assert calls == 2


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthenticationError("unauthorized"),
        LLMAPIError("forbidden", status_code=403),
        LLMAPIError("not implemented", status_code=501),
        LLMConfigError("bad configuration"),
        LLMParseError("bad response"),
        ValueError("contract mismatch"),
    ],
)
def test_lightrag_adapter_does_not_retry_deterministic_errors(monkeypatch, error) -> None:
    calls = 0

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                raise error

            return model_func

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())

    with pytest.raises(type(error)) as captured:
        asyncio.run(lr_config.build_llm_model_func()("prompt"))

    assert captured.value is error
    assert calls == 1


def test_lightrag_adapter_exhaustion_reraises_original_final_exception(monkeypatch) -> None:
    failures = [
        LLMAPIError("first", status_code=502),
        LLMAPIError("second", status_code=503),
        LLMAPIError("final", status_code=504),
    ]
    final_error = failures[-1]
    calls = 0

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                raise failures.pop(0)

            return model_func

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)

    with pytest.raises(LLMAPIError) as captured:
        asyncio.run(lr_config.build_llm_model_func()("prompt"))

    assert captured.value is final_error
    assert calls == 3


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [(7.5, 7.5), (120.0, 60.0), (-1.0, 1.0), ("invalid", 1.0)],
)
def test_lightrag_adapter_honors_bounded_retry_after(
    monkeypatch,
    retry_after,
    expected_delay,
) -> None:
    calls = 0
    sleep_delays: list[float] = []

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise LLMRateLimitError("rate limited", retry_after=retry_after)
                return "ok"

            return model_func

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)

    assert asyncio.run(lr_config.build_llm_model_func()("prompt")) == "ok"
    assert sleep_delays == [expected_delay]


def test_lightrag_adapter_honors_retry_after_response_header(monkeypatch) -> None:
    calls = 0
    sleep_delays: list[float] = []

    class RetryableResponseError(Exception):
        status_code = 503
        response = types.SimpleNamespace(headers={"Retry-After": "4"})

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RetryableResponseError("temporary")
                return "ok"

            return model_func

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)

    assert asyncio.run(lr_config.build_llm_model_func()("prompt")) == "ok"
    assert sleep_delays == [4.0]


def test_lightrag_adapter_preserves_cancellation_without_retry(monkeypatch) -> None:
    calls = 0

    class _Client:
        def get_model_func(self):
            async def model_func(_prompt, **_kwargs):
                nonlocal calls
                calls += 1
                raise asyncio.CancelledError

            return model_func

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(lr_config.build_llm_model_func()("prompt"))

    assert calls == 1


@pytest.mark.asyncio
async def test_lightrag_vision_adapter_disables_provider_image_fallback(
    monkeypatch,
) -> None:
    from deeptutor.services.llm.client import LLMClient
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.multimodal import has_image_parts
    from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse

    class ScriptedProvider(LLMProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls_had_image: list[bool] = []

        async def chat(self, messages, **kwargs):
            del kwargs
            self.calls_had_image.append(has_image_parts(messages))
            if len(self.calls_had_image) == 1:
                return LLMResponse(
                    content="this model does not support images",
                    finish_reason="error",
                )
            return LLMResponse(content="text fallback should not run")

        def get_default_model(self) -> str:
            return "unknown-model"

    config = LLMConfig(
        model="unknown-model",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        binding="custom",
        provider_name="custom",
    )
    client = LLMClient(config)
    provider = ScriptedProvider()

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: client)
    monkeypatch.setattr("deeptutor.services.llm.factory.get_llm_config", lambda: config)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider",
        lambda _config: provider,
    )

    func = lr_config.build_vision_model_func()
    with pytest.raises(LLMAPIError, match="does not support images"):
        await func("prompt", image_data="QUJD")

    assert provider.calls_had_image == [True]


def test_lightrag_vision_adapter_preserves_payload_and_redacts_retry_log(
    monkeypatch,
    caplog,
) -> None:
    sensitive_message = "prompt-secret base64-secret token-secret account-secret"
    image_payload = "base64-secret-image-payload"
    image_calls: list[object] = []
    retry_settings: list[object] = []
    calls = 0

    class _Client:
        def get_vision_model_func(self):
            async def model_func(_prompt, **kwargs):
                nonlocal calls
                calls += 1
                image_calls.append(kwargs["image_data"])
                retry_settings.append(kwargs["max_retries"])
                if calls == 1:
                    raise ConnectionError(sensitive_message)
                return "ok"

            return model_func

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: _Client())
    monkeypatch.setattr(lr_config.asyncio, "sleep", fake_sleep)
    caplog.set_level(logging.WARNING, logger=lr_config.__name__)

    func = lr_config.build_vision_model_func()
    assert asyncio.run(func("prompt-secret", image_data=image_payload)) == "ok"

    assert calls == 2
    assert all(payload is image_payload for payload in image_calls)
    assert retry_settings == [0, 0]
    assert sensitive_message not in caplog.text
    assert "prompt-secret" not in caplog.text
    assert image_payload not in caplog.text
    assert (
        "LightRAG adapter retry attempt=1 exception=ConnectionError status=transport" in caplog.text
    )


def test_build_rag_skips_raganything_parser_install_check(monkeypatch) -> None:
    """Regression for issue #594.

    RAG-Anything validates its *default* parser (``mineru``) at LightRAG-init
    time, even though DeepTutor only ever inserts a pre-parsed ``content_list``
    and never uses RAG-Anything's parser. ``build_rag`` must pre-satisfy that
    check so indexing with a different parse engine (e.g. pymupdf4llm) doesn't
    hard-fail when MinerU is absent.
    """
    captured: dict[str, object] = {}

    class _FakeConfig:
        def __init__(self, *, working_dir) -> None:
            self.working_dir = working_dir
            self.parser = "mineru"  # RAG-Anything's default

    class _FakeRagAnything:
        def __init__(self, *, config, llm_model_func, vision_model_func, embedding_func) -> None:
            # Mirror the real constructor: the install check starts unsatisfied.
            self._parser_installation_checked = False
            captured["config"] = config

    fake_module = types.ModuleType("raganything")
    fake_module.RAGAnything = _FakeRagAnything
    fake_module.RAGAnythingConfig = _FakeConfig
    monkeypatch.setitem(sys.modules, "raganything", fake_module)
    monkeypatch.setattr(engine, "build_llm_model_func", lambda: "llm")
    monkeypatch.setattr(engine, "build_vision_model_func", lambda: "vision")
    monkeypatch.setattr(engine, "build_embedding_func", lambda: "embed")

    rag = engine.build_rag(Path("/tmp/kb-wd"))  # noqa: S108

    assert rag._parser_installation_checked is True
    assert captured["config"].working_dir == "/tmp/kb-wd"


def test_lightrag_query_initializes_raganything_before_aquery(monkeypatch) -> None:
    calls: list[str] = []

    class _Rag:
        lightrag = None

        async def _ensure_lightrag_initialized(self):
            calls.append("ensure")
            self.lightrag = object()
            return {"success": True}

        async def aquery(self, question, mode=None, **kwargs):
            calls.append("aquery")
            assert self.lightrag is not None
            assert question == "hello"
            assert mode == "hybrid"
            assert kwargs == {}
            return "answer"

    monkeypatch.setattr(engine, "query_kwargs_from_settings", lambda: {})

    result = asyncio.run(engine.query(_Rag(), "hello", "hybrid"))

    assert result == "answer"
    assert calls == ["ensure", "aquery"]


def test_lightrag_query_surfaces_raganything_initialization_failure() -> None:
    class _Rag:
        lightrag = None

        async def _ensure_lightrag_initialized(self):
            return {"success": False, "error": "storage failed"}

        async def aquery(self, question, mode=None, **kwargs):  # pragma: no cover
            raise AssertionError("aquery should not run")

    with pytest.raises(RuntimeError, match="storage failed"):
        asyncio.run(engine.query(_Rag(), "hello", "hybrid"))


# --------------------------------------------------------------------------- #
# pipeline lifecycle (engine + parse service stubbed)
# --------------------------------------------------------------------------- #


class _FakeRag:
    def __init__(self, working_dir) -> None:
        self.working_dir = Path(working_dir)


def _force_available(monkeypatch, available: bool = True) -> None:
    monkeypatch.setattr(lr_config, "is_lightrag_available", lambda: available)


def _stub_engine(monkeypatch, answer: str = "ANSWER") -> list[dict]:
    """Stub the engine so insert writes a readiness marker and query echoes."""
    inserts: list[dict] = []
    monkeypatch.setattr(engine, "build_rag", lambda wd, **_: _FakeRag(wd))

    async def fake_insert(rag, content_list, *, file_name, doc_id):
        inserts.append({"file": file_name, "doc_id": doc_id, "blocks": content_list})
        (rag.working_dir / "vdb_chunks.json").write_text(
            json.dumps({"vectors": [[1.0]]}), encoding="utf-8"
        )
        (rag.working_dir / "kv_store_doc_status.json").write_text(
            json.dumps(
                {
                    doc_id: {
                        "status": "processed",
                        "file_path": file_name,
                        "chunks_list": ["chunk-1"],
                    }
                }
            ),
            encoding="utf-8",
        )

    async def fake_query(rag, question, mode):
        return f"{answer}|{mode}"

    monkeypatch.setattr(engine, "insert", fake_insert)
    monkeypatch.setattr(engine, "query", fake_query)
    return inserts


def _stub_parse(monkeypatch, *, blocks=None, markdown: str = "# md") -> None:
    from deeptutor.services.parsing.types import ParsedDocument

    class _Service:
        def parse(self, path, **_):
            return ParsedDocument(
                markdown=markdown,
                blocks=blocks,
                source_hash="h_" + Path(path).stem,
                engine="fake",
            )

    monkeypatch.setattr("deeptutor.services.parsing.get_parse_service", lambda: _Service())


def test_indexing_isolated_from_owner_loop_with_context_and_progress(tmp_path, monkeypatch) -> None:
    """Regression for #761: local JSON work must not stall service I/O."""
    from deeptutor.services.parsing.types import ParsedDocument

    request_scope = contextvars.ContextVar("lightrag_test_scope", default="missing")
    captured: dict[str, object] = {"inserts": [], "progress": [], "parse_threads": []}

    class _ParseService:
        def parse(self, path, **_):
            captured["parse_threads"].append(threading.get_ident())
            source = Path(path)
            return ParsedDocument(
                markdown="",
                blocks=[{"type": "text", "text": source.stem, "page_idx": 0}],
                source_hash=f"hash-{source.stem}",
                engine="fake",
            )

    class _BlockingRag:
        def __init__(self, working_dir, io_bridge) -> None:
            self.working_dir = Path(working_dir)
            self.io_bridge = io_bridge

        async def insert_content_list(self, *, content_list, file_path, doc_id):
            captured["worker_thread"] = threading.get_ident()
            captured["worker_context"] = request_scope.get()
            captured["block_started_at"] = time.monotonic()
            time.sleep(0.15)

            async def fake_network_io():
                captured["io_thread"] = threading.get_ident()
                captured["io_context"] = request_scope.get()
                return "io-ok"

            captured["io_result"] = await self.io_bridge.run(fake_network_io)
            captured["inserts"].append(
                {"content_list": content_list, "file_path": file_path, "doc_id": doc_id}
            )
            self.working_dir.mkdir(parents=True, exist_ok=True)
            (self.working_dir / "kv_store_doc_status.json").write_text(
                json.dumps(
                    {
                        doc_id: {
                            "status": "processed",
                            "file_path": file_path,
                            "chunks_list": ["chunk-1"],
                        }
                    }
                ),
                encoding="utf-8",
            )

    def fake_build_rag(working_dir, *, io_bridge):
        captured["build_thread"] = threading.get_ident()
        return _BlockingRag(working_dir, io_bridge)

    monkeypatch.setattr("deeptutor.services.parsing.get_parse_service", lambda: _ParseService())
    monkeypatch.setattr(engine, "build_rag", fake_build_rag)
    _force_available(monkeypatch, True)

    docs = [tmp_path / "one.pdf", tmp_path / "two.pdf"]
    for doc in docs:
        doc.write_bytes(b"%PDF")

    async def scenario() -> bool:
        owner_thread = threading.get_ident()
        captured["owner_thread"] = owner_thread
        request_scope.set("user-761")

        async def on_progress(current: int, total: int) -> None:
            await asyncio.sleep(0)
            captured["progress"].append(
                (current, total, threading.get_ident(), request_scope.get())
            )

        async def heartbeat() -> None:
            while "block_started_at" not in captured:
                await asyncio.sleep(0)
            await asyncio.sleep(0.01)
            captured["heartbeat_at"] = time.monotonic()

        pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
        indexing = asyncio.create_task(
            pipe.initialize("kb", [str(doc) for doc in docs], progress_callback=on_progress)
        )
        pulse = asyncio.create_task(heartbeat())
        result = await indexing
        await pulse
        return result

    assert asyncio.run(scenario()) is True
    owner_thread = captured["owner_thread"]
    assert captured["build_thread"] != owner_thread
    assert captured["worker_thread"] != owner_thread
    assert set(captured["parse_threads"]) == {captured["worker_thread"]}
    assert captured["io_thread"] == owner_thread
    assert captured["worker_context"] == "user-761"
    assert captured["io_context"] == "user-761"
    assert captured["io_result"] == "io-ok"
    assert captured["heartbeat_at"] - captured["block_started_at"] < 0.1
    assert captured["progress"] == [
        (1, 2, owner_thread, "user-761"),
        (2, 2, owner_thread, "user-761"),
    ]
    assert captured["inserts"] == [
        {
            "content_list": [{"type": "text", "text": "one", "page_idx": 0}],
            "file_path": "one.pdf",
            "doc_id": "hash-one",
        },
        {
            "content_list": [{"type": "text", "text": "two", "page_idx": 0}],
            "file_path": "two.pdf",
            "doc_id": "hash-two",
        },
    ]


def test_indexing_worker_exception_propagates_unchanged(tmp_path, monkeypatch) -> None:
    class _IndexingFailure(RuntimeError):
        pass

    class _FailingRag:
        def __init__(self, working_dir) -> None:
            self.working_dir = Path(working_dir)

        async def insert_content_list(self, **_):
            raise _IndexingFailure("nano-vdb merge failed")

    monkeypatch.setattr(engine, "build_rag", lambda wd, **_: _FailingRag(wd))
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    _force_available(monkeypatch, True)
    document = tmp_path / "bad.pdf"
    document.write_bytes(b"%PDF")

    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    with pytest.raises(_IndexingFailure, match="nano-vdb merge failed"):
        asyncio.run(pipe.initialize("kb", [str(document)]))


def test_indexing_cancellation_waits_for_worker_loop_to_close() -> None:
    started = threading.Event()
    stopped = threading.Event()
    owner_callback_called = False
    worker_loop: asyncio.AbstractEventLoop | None = None

    async def scenario() -> None:
        async def job(io_bridge) -> None:
            nonlocal owner_callback_called, worker_loop
            worker_loop = asyncio.get_running_loop()
            started.set()
            try:
                # Stand in for an uninterruptible synchronous NanoVectorDB
                # flush. Cancellation is observed at the next bridge call.
                time.sleep(0.05)

                def owner_callback() -> None:
                    nonlocal owner_callback_called
                    owner_callback_called = True

                await io_bridge.call(owner_callback)
            finally:
                stopped.set()

        task = asyncio.create_task(run_in_worker_loop(job))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert stopped.is_set()
    assert worker_loop is not None
    assert worker_loop.is_closed()
    assert owner_callback_called is False


def test_indexing_cancellation_cancels_worker_main_task() -> None:
    started = threading.Event()
    stopped = threading.Event()
    worker_loop: asyncio.AbstractEventLoop | None = None

    async def scenario() -> None:
        async def job(_io_bridge) -> None:
            nonlocal worker_loop
            worker_loop = asyncio.get_running_loop()
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        task = asyncio.create_task(run_in_worker_loop(job))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)

    asyncio.run(scenario())

    assert stopped.is_set()
    assert worker_loop is not None
    assert worker_loop.is_closed()


def test_indexing_cancellation_escalates_when_worker_suppresses_first_cancel() -> None:
    started = threading.Event()
    first_cancel = threading.Event()
    stopped = threading.Event()
    worker_loop: asyncio.AbstractEventLoop | None = None

    async def scenario() -> None:
        async def job(_io_bridge) -> None:
            nonlocal worker_loop
            worker_loop = asyncio.get_running_loop()
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                first_cancel.set()
                await asyncio.Event().wait()
            finally:
                stopped.set()

        task = asyncio.create_task(run_in_worker_loop(job, cancel_grace_seconds=0.01))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)

    asyncio.run(scenario())

    assert first_cancel.is_set()
    assert stopped.is_set()
    assert worker_loop is not None
    assert worker_loop.is_closed()


def test_indexing_failure_forces_queue_shutdown_and_finalizes_storage(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class _QueueFunc:
        async def __call__(self, *_args, **_kwargs) -> None:
            return None

        async def shutdown(self, *, graceful: bool, timeout: float) -> None:
            calls.append(("shutdown", graceful, timeout))

    queue_func = _QueueFunc()

    class _FailingRag:
        def __init__(self, working_dir) -> None:
            self.working_dir = Path(working_dir)
            self.lightrag = types.SimpleNamespace(
                role_llm_funcs={"extract": queue_func},
                embedding_func=types.SimpleNamespace(func=queue_func),
                rerank_model_func=None,
            )

        async def insert_content_list(self, **_kwargs) -> None:
            raise RuntimeError("entity extraction failed")

        async def finalize_storages(self) -> None:
            calls.append(("finalize",))

    monkeypatch.setattr(engine, "build_rag", lambda wd, **_: _FailingRag(wd))
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    _force_available(monkeypatch, True)
    document = tmp_path / "bad.pdf"
    document.write_bytes(b"%PDF")

    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="entity extraction failed"):
        asyncio.run(pipe.initialize("kb", [str(document)]))

    assert calls == [("shutdown", False, 5.0), ("finalize",)]


def test_initialize_requires_lightrag(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, False)
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(lr_config.LightRagNotAvailableError):
        asyncio.run(pipe.initialize("kb", [str(pdf)]))


def test_initialize_orchestrates_index_and_uses_blocks(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    inserts = _stub_engine(monkeypatch)
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "hi", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF")

    ok = asyncio.run(pipe.initialize("kb", [str(pdf)]))
    assert ok is True
    assert len(inserts) == 1
    assert inserts[0]["file"] == "exam.pdf"
    # blocks from the parse layer are passed through verbatim (multimodal path).
    assert inserts[0]["blocks"] == [{"type": "text", "text": "hi", "page_idx": 0}]
    # version dir is marked ready.
    root = resolve_storage_dir_for_read(tmp_path / "kb", None)
    assert storage.has_output(root) is True


def test_ingest_falls_back_to_markdown_when_no_blocks(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    inserts = _stub_engine(monkeypatch)
    _stub_parse(monkeypatch, blocks=None, markdown="# only markdown")
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(b"%PDF")

    asyncio.run(pipe.initialize("kb", [str(pdf)]))
    assert inserts[0]["blocks"] == [{"type": "text", "text": "# only markdown", "page_idx": 0}]


def test_initialize_no_content_returns_false(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    inserts = _stub_engine(monkeypatch)
    _stub_parse(monkeypatch, blocks=None, markdown="")  # empty parse
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(b"%PDF")

    ok = asyncio.run(pipe.initialize("kb", [str(pdf)]))
    assert ok is False
    assert inserts == []


def test_initialize_fails_when_lightrag_records_doc_failure(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    monkeypatch.setattr(engine, "build_rag", lambda wd, **_: _FakeRag(wd))

    async def fake_insert(rag, content_list, *, file_name, doc_id):
        (rag.working_dir / "kv_store_doc_status.json").write_text(
            json.dumps(
                {
                    doc_id: {
                        "status": "failed",
                        "file_path": file_name,
                        "error_msg": "'list' object has no attribute 'size'",
                        "chunks_list": [],
                    }
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(engine, "insert", fake_insert)
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "hi", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    docx = tmp_path / "bad.docx"
    docx.write_bytes(b"docx")

    with pytest.raises(RuntimeError, match="list.*size"):
        asyncio.run(pipe.initialize("kb", [str(docx)]))

    assert resolve_storage_dir_for_read(tmp_path / "kb", None) is None


def test_search_needs_reindex_without_output(tmp_path) -> None:
    res = asyncio.run(LightRagPipeline(kb_base_dir=str(tmp_path)).search("q", "missing"))
    assert res["needs_reindex"] is True
    assert res["provider"] == "lightrag"


def test_search_not_configured_when_unavailable(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_engine(monkeypatch)
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    _force_available(monkeypatch, False)
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["error_type"] == "not_configured"


def test_search_happy_path_resolves_mode(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_engine(monkeypatch, answer="GROUNDED")
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    # Per-KB search_mode is read from kb_config.json next to the store.
    (tmp_path / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"kb": {"search_mode": "local"}}}), encoding="utf-8"
    )
    res = asyncio.run(pipe.search("question?", "kb"))
    assert res["answer"] == "GROUNDED|local"
    assert res["mode"] == "local"
    assert res["provider"] == "lightrag"


def test_explicit_mode_overrides_kb_config(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_engine(monkeypatch, answer="A")
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    res = asyncio.run(pipe.search("q", "kb", mode="global"))
    assert res["mode"] == "global"


def test_global_provider_mode_used_when_kb_has_none(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_engine(monkeypatch, answer="A")
    _stub_parse(monkeypatch, blocks=[{"type": "text", "text": "x", "page_idx": 0}])
    pipe = LightRagPipeline(kb_base_dir=str(tmp_path))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    asyncio.run(pipe.initialize("kb", [str(pdf)]))

    # No per-KB search_mode, but a global default mode set from the engine card.
    (tmp_path / "kb_config.json").write_text(
        json.dumps({"defaults": {"provider_modes": {"lightrag": "naive"}}}), encoding="utf-8"
    )
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["mode"] == "naive"
