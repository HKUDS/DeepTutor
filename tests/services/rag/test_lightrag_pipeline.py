from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import types

import pytest

from deeptutor.multi_user.context import (
    get_current_user_or_none,
    reset_current_user,
    set_current_user,
)
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.llm.exceptions import LLMAPIError, LLMAuthenticationError
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.factory import get_pipeline, list_pipelines, normalize_provider_name
from deeptutor.services.rag.index_versioning import list_kb_versions
from deeptutor.services.rag.pipelines.lightrag import config, engine, indexing_policy, storage
from deeptutor.services.rag.pipelines.lightrag.ingress import (
    IngressError,
    bundles_root,
    freeze_document,
    load_verified_bundle,
    pending_root,
)
from deeptutor.services.rag.pipelines.lightrag.pipeline import (
    BatchOutcome,
    LightRagBatchError,
    LightRagNeedsReindexError,
    LightRagPipeline,
)

REQUIRES_LIGHTRAG = pytest.mark.skipif(
    importlib.util.find_spec("lightrag") is None,
    reason="requires the optional rag-lightrag extra",
)


class _Bridge:
    def __init__(self) -> None:
        self.calls = 0

    def raise_if_cancelled(self) -> None:
        return None

    async def run(self, factory):
        self.calls += 1
        return await factory()

    async def call(self, callback, *args):
        self.calls += 1
        value = callback(*args)
        return await value if inspect.isawaitable(value) else value


def _indexing_snapshot():
    return types.SimpleNamespace(
        vision_available=True,
        persisted_policy=lambda: {"policy": "pinned", "fingerprint": "a" * 64},
    )


def test_factory_routes_without_importing_optional_sdk(tmp_path: Path, monkeypatch) -> None:
    sys.modules.pop("lightrag", None)
    pipeline = get_pipeline("lightrag", kb_base_dir=str(tmp_path))
    assert isinstance(pipeline, LightRagPipeline)
    assert "lightrag" not in sys.modules
    monkeypatch.setattr(config, "is_lightrag_available", lambda: False)
    entry = next(item for item in list_pipelines() if item["id"] == "lightrag")
    assert entry["configured"] is False
    assert normalize_provider_name("LightRAG") == "lightrag"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("MIX", "mix"), ("local", "local"), (None, "hybrid"), ("invalid", "hybrid")],
)
def test_normalize_mode(value, expected) -> None:
    assert config.normalize_mode(value) == expected


def test_availability_checks_native_lightrag_module(monkeypatch) -> None:
    seen: list[str] = []

    def find_spec(name: str):
        seen.append(name)
        return None

    monkeypatch.setattr(config.importlib.util, "find_spec", find_spec)
    assert config.is_lightrag_available() is False
    assert seen == ["lightrag"]


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, None),
        (
            {"llm_profile_id": " profile ", "llm_model_id": " model "},
            {"profile_id": "profile", "model_id": "model"},
        ),
        ({"llm_profile_id": "profile", "llm_model_id": ""}, None),
    ],
)
def test_released_lightrag_query_selection_keeps_fallback_contract(
    monkeypatch, settings, expected
) -> None:
    monkeypatch.setattr("deeptutor.services.config.load_lightrag_settings", lambda: settings)

    assert config.lightrag_llm_selection_from_settings() == expected


def test_indexing_selection_rejects_partial_released_setting(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings",
        lambda: {"llm_profile_id": "profile", "llm_model_id": ""},
    )

    with pytest.raises(ValueError, match="incomplete"):
        config.lightrag_indexing_selection_from_settings()


def test_query_model_resolver_falls_back_only_when_selected_entry_is_missing(
    monkeypatch,
) -> None:
    selection = {"profile_id": "profile", "model_id": "model"}
    fallback = object()
    calls: list[object] = []
    monkeypatch.setattr(config, "lightrag_llm_selection_from_settings", lambda: selection)

    def resolve(value):
        calls.append(value)
        if value is selection:
            raise ValueError("missing")
        return fallback

    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.resolve_llm_config_for_selection",
        resolve,
    )

    assert config.resolve_lightrag_query_llm_config() is fallback
    assert calls == [selection, None]


def test_lightrag_llm_adapter_uses_explicit_snapshot_config(monkeypatch) -> None:
    def build_model(config, *, allow_multimodal):
        assert config is selected_config
        assert allow_multimodal is False

        async def model_func(_prompt, **kwargs):
            assert kwargs["max_retries"] == 0
            return "ok"

        return model_func

    selected_config = object()
    monkeypatch.setattr("deeptutor.services.llm.client.build_model_func_for_config", build_model)

    adapter = config.build_llm_model_func(llm_config=selected_config)
    assert asyncio.run(adapter("prompt")) == "ok"


def test_lightrag_vision_adapter_uses_explicit_snapshot_config(monkeypatch) -> None:
    def build_model(config, *, allow_multimodal):
        assert config is selected_config
        assert allow_multimodal is True

        async def model_func(_prompt, **kwargs):
            assert kwargs["allow_image_fallback"] is False
            assert kwargs["image_data"] == "sentinel"
            return "ok"

        return model_func

    selected_config = object()
    monkeypatch.setattr("deeptutor.services.llm.client.build_model_func_for_config", build_model)

    adapter = config.build_vision_model_func(llm_config=selected_config)
    assert asyncio.run(adapter("prompt", image_inputs=[{"base64": "sentinel"}])) == "ok"


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("fail", [False, True])
def test_explicit_adapter_installs_owner_scope_and_restores_ambient_scope(
    monkeypatch, tmp_path: Path, role: str, fail: bool
) -> None:
    owner = CurrentUser(
        id=f"owner-{role}",
        username=f"owner-{role}",
        role=role,
        scope=UserScope(kind=role, user_id=f"owner-{role}", root=tmp_path / "owner"),
    )
    ambient = CurrentUser(
        id="ambient",
        username="ambient",
        role="user",
        scope=UserScope(kind="user", user_id="ambient", root=tmp_path / "ambient"),
    )

    def build_model(_config, *, allow_multimodal):
        assert allow_multimodal is False

        async def model_func(_prompt, **_kwargs):
            assert get_current_user_or_none() == owner
            if fail:
                raise RuntimeError("provider failed")
            return "ok"

        return model_func

    monkeypatch.setattr("deeptutor.services.llm.client.build_model_func_for_config", build_model)
    adapter = config.build_llm_model_func(llm_config=object(), owner=owner)
    token = set_current_user(ambient)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="provider failed"):
                asyncio.run(adapter("prompt"))
        else:
            assert asyncio.run(adapter("prompt")) == "ok"
        assert get_current_user_or_none() == ambient
    finally:
        reset_current_user(token)


def test_build_rag_keeps_indexing_snapshot_out_of_embedding_kwargs(
    monkeypatch, tmp_path: Path
) -> None:
    """The 1.6 native adapter must not pass LLM-only kwargs to embedding."""

    class NativeLightRag:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_lightrag = types.ModuleType("lightrag")
    fake_lightrag.__path__ = []  # type: ignore[attr-defined]
    fake_roles = types.ModuleType("lightrag.llm_roles")

    class RoleLLMConfig:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    fake_roles.RoleLLMConfig = RoleLLMConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "lightrag", fake_lightrag)
    monkeypatch.setitem(sys.modules, "lightrag.llm_roles", fake_roles)
    monkeypatch.setattr(engine, "_require_exact_version", lambda: None)
    monkeypatch.setattr(engine, "_register_parser", lambda: None)
    monkeypatch.setattr(engine, "_controlled_class", lambda: NativeLightRag)
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)
    query_config = types.SimpleNamespace(binding="openai")
    monkeypatch.setattr(engine, "resolve_lightrag_query_llm_config", lambda: query_config)
    monkeypatch.setattr(indexing_policy, "cache_identity_for_config", lambda _config: "query-id")
    llm_calls: list[dict[str, object]] = []
    embedding_calls: list[object] = []

    def build_llm(**kwargs):
        llm_calls.append(kwargs)
        return "llm"

    def build_embedding(*, io_bridge=None):
        embedding_calls.append(io_bridge)
        return "embedding"

    monkeypatch.setattr(engine, "build_llm_model_func", build_llm)
    monkeypatch.setattr(engine, "build_embedding_func", build_embedding)

    rag = engine.build_rag(tmp_path)

    assert llm_calls == [{"llm_config": query_config}]
    assert embedding_calls == [None]
    assert rag.kwargs["embedding_func"] == "embedding"


@REQUIRES_LIGHTRAG
def test_distribution_identity_is_exact_rc2() -> None:
    assert engine.installed_version() == "1.5.7rc2"
    assert engine.LIGHTRAG_DISTRIBUTION == "lightrag-hku"


def test_preflight_rejects_a_different_installed_lightrag_version(monkeypatch) -> None:
    from deeptutor.services.rag import preflight

    monkeypatch.setattr(config, "is_lightrag_available", lambda: True)
    monkeypatch.setattr(engine, "installed_version", lambda: "1.5.8")
    monkeypatch.setattr(preflight, "_active_embedding", lambda: ("embedding", 3))
    monkeypatch.setattr(preflight, "_active_chat_model", lambda: ("chat", "openai"))
    report = preflight._lightrag_preflight()
    package = next(check for check in report["checks"] if check["key"] == "package")
    assert package["ok"] is False
    assert package["detail"] == "Found 1.5.8; required 1.5.7rc2."


def test_workspace_is_stable_and_version_specific(tmp_path: Path) -> None:
    first = engine.workspace_for(tmp_path / "version-1")
    assert first == engine.workspace_for(tmp_path / "version-1")
    assert first != engine.workspace_for(tmp_path / "version-2")
    assert first.startswith("deeptutor_")


def _resolver(tmp_path: Path):
    cls = engine._controlled_class()
    rag = object.__new__(cls)
    rag.working_dir = str(tmp_path)
    return rag


@REQUIRES_LIGHTRAG
def test_source_resolver_only_reads_version_ingress(tmp_path: Path, monkeypatch) -> None:
    pending = pending_root(tmp_path)
    pending.mkdir(parents=True)
    expected = pending / "doc.pdf"
    expected.write_bytes(b"right")
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "doc.pdf").write_bytes(b"wrong")
    monkeypatch.chdir(decoy)
    rag = _resolver(tmp_path)
    assert rag._resolve_source_file_for_parser("doc.pdf", parser_engine="deeptutor") == str(
        expected.resolve()
    )


@REQUIRES_LIGHTRAG
@pytest.mark.parametrize("bad", ["../doc.pdf", "/tmp/doc.pdf", "nested/doc.pdf"])
def test_source_resolver_rejects_noncanonical_paths(tmp_path: Path, bad: str) -> None:
    rag = _resolver(tmp_path)
    with pytest.raises(IngressError):
        rag._resolve_source_file_for_parser(bad, parser_engine="deeptutor")


@REQUIRES_LIGHTRAG
def test_source_resolver_rejects_symlink_and_ambiguity(tmp_path: Path) -> None:
    pending = pending_root(tmp_path)
    archived = pending / "__parsed__"
    archived.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    (pending / "doc.pdf").symlink_to(outside)
    rag = _resolver(tmp_path)
    with pytest.raises(IngressError, match="missing"):
        rag._resolve_source_file_for_parser("doc.pdf", parser_engine="deeptutor")
    (pending / "doc.pdf").unlink()
    (pending / "doc.pdf").write_bytes(b"one")
    (archived / "doc.pdf").write_bytes(b"two")
    with pytest.raises(IngressError, match="ambiguous"):
        rag._resolve_source_file_for_parser("doc.pdf", parser_engine="deeptutor")


@REQUIRES_LIGHTRAG
def test_source_resolver_rejects_other_parser(tmp_path: Path) -> None:
    with pytest.raises(IngressError, match="Unsupported parser"):
        _resolver(tmp_path)._resolve_source_file_for_parser("doc.pdf", parser_engine="mineru")


def test_vision_adapter_maps_one_base64_unchanged(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Client:
        def get_vision_model_func(self):
            async def call(prompt, **kwargs):
                captured["prompt"] = prompt
                captured.update(kwargs)
                return "seen"

            return call

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: Client())
    func = config.build_vision_model_func()
    assert asyncio.run(func("describe", image_inputs=[{"base64": "sentinel"}])) == "seen"
    assert captured["image_data"] == "sentinel"
    assert captured["allow_image_fallback"] is False


@pytest.mark.parametrize(
    "value",
    [None, [], [{"base64": "a"}, {"base64": "b"}], [{}], ["image"], [{"base64": ""}]],
)
def test_vision_adapter_rejects_invalid_inputs(monkeypatch, value) -> None:
    class Client:
        def get_vision_model_func(self):
            async def call(*_args, **_kwargs):
                raise AssertionError("prompt-only fallback must not run")

            return call

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", lambda: Client())
    with pytest.raises(ValueError):
        asyncio.run(config.build_vision_model_func()("describe", image_inputs=value))


@REQUIRES_LIGHTRAG
def test_embedding_adapter_preserves_query_and_document_roles(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    class EmbeddingConfig:
        dim = 3
        max_tokens = 99

    class Client:
        async def embed(self, texts, *, input_type=None):
            calls.append((list(texts), input_type))
            return [[1, 2, 3] for _ in texts]

    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_config", EmbeddingConfig)
    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_client", Client)
    adapter = config.build_embedding_func()
    query = asyncio.run(adapter(["question"], context="query"))
    document = asyncio.run(adapter(["passage"], context="document"))

    assert query.shape == (1, 3)
    assert document.shape == (1, 3)
    assert calls == [
        (["question"], "search_query"),
        (["passage"], "search_document"),
    ]


def test_llm_adapter_retries_only_transient_failures(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []

    class Client:
        def get_model_func(self):
            async def call(_prompt, **kwargs):
                nonlocal attempts
                attempts += 1
                assert kwargs["max_retries"] == 0
                if attempts < 3:
                    raise LLMAPIError("temporary", status_code=503)
                return "ok"

            return call

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", Client)
    monkeypatch.setattr(config.asyncio, "sleep", sleep)
    assert asyncio.run(config.build_llm_model_func()("prompt")) == "ok"
    assert attempts == 3
    assert sleeps == [1.0, 2.0]


def test_llm_adapter_does_not_retry_authentication_failure(monkeypatch) -> None:
    error = LLMAuthenticationError("unauthorized")
    attempts = 0

    class Client:
        def get_model_func(self):
            async def call(_prompt, **_kwargs):
                nonlocal attempts
                attempts += 1
                raise error

            return call

    monkeypatch.setattr("deeptutor.services.llm.get_llm_client", Client)
    with pytest.raises(LLMAuthenticationError) as caught:
        asyncio.run(config.build_llm_model_func()("prompt"))
    assert caught.value is error
    assert attempts == 1


def test_preparse_runs_once_and_bundle_ignores_later_parser_drift(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.md"
    source.write_text("original source", encoding="utf-8")
    calls = 0

    class ParseService:
        def parse(self, _path):
            nonlocal calls
            calls += 1
            return ParsedDocument(
                markdown="frozen markdown",
                engine="text_only",
                source_hash="source-hash",
                parser_signature="parser-v1",
            )

    monkeypatch.setattr("deeptutor.services.parsing.get_parse_service", ParseService)
    monkeypatch.setattr(config, "vision_model_available", lambda: False)
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path / "kb"))
    staged, failures = pipeline._stage_documents(
        tmp_path / "version-1", [str(source)], vision_available=True
    )
    source.write_text("changed after staging", encoding="utf-8")

    manifest, bundle = load_verified_bundle(tmp_path / "version-1", "source.md")
    assert calls == 1
    assert failures == {}
    assert len(staged) == 1
    assert (bundle / manifest["markdown"]["path"]).read_text() == "frozen markdown"
    assert staged[0].source_path.read_text() == "original source"


class _QueryRag:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0
        self.param = None

    async def aquery_llm(self, _question, *, param):
        self.calls += 1
        self.param = param
        return self.result


def _query_result() -> dict:
    return {
        "status": "success",
        "llm_response": {"is_streaming": False, "content": "answer"},
        "data": {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "content": "x" * 500,
                    "reference_id": "r1",
                    "page": 2,
                }
            ],
            "entities": [
                {
                    "entity_name": "Euler",
                    "entity_type": "person",
                    "description": "entity body",
                    "source_id": "c1",
                    "reference_id": "r1",
                }
            ],
            "relationships": [
                {
                    "src_id": "Euler",
                    "tgt_id": "Identity",
                    "description": "relationship body",
                    "keywords": ["math"],
                    "weight": 3.5,
                    "source_id": "c1",
                    "reference_id": "r1",
                }
            ],
            "references": [{"reference_id": "r1", "file_path": "notes.pdf"}],
        },
        "metadata": {"keywords": {"high_level": ["math"]}, "processing_info": {"chunks": 1}},
    }


@REQUIRES_LIGHTRAG
def test_query_uses_one_call_and_preserves_complete_sources(monkeypatch) -> None:
    monkeypatch.setattr(engine, "query_kwargs_from_settings", lambda: {})
    rag = _QueryRag(_query_result())
    answer, sources = asyncio.run(engine.query_with_sources(rag, "q", "hybrid"))
    assert rag.calls == 1
    assert rag.param.stream is False
    assert answer == "answer"
    assert sources[0]["content"] == "x" * 500
    assert sources[0]["kind"] == "chunk"
    assert sources[1]["entity_name"] == "Euler"
    assert sources[2]["weight"] == 3.5
    assert "score" not in sources[2]
    assert sources[3]["kind"] == "reference"
    assert sources[3]["reference"] == {"reference_id": "r1", "file_path": "notes.pdf"}
    assert sources[-1]["metadata"]["processing_info"] == {"chunks": 1}


@REQUIRES_LIGHTRAG
@pytest.mark.parametrize(
    "result",
    [
        {"status": "failure", "message": "retrieval failed"},
        {"status": "success", "llm_response": {}, "data": {}, "metadata": {}},
        {
            "status": "success",
            "llm_response": {"is_streaming": True, "content": "x"},
            "data": {},
            "metadata": {},
        },
        "not an object",
    ],
)
def test_query_rejects_failure_and_malformed_envelopes(result) -> None:
    with pytest.raises(engine.LightRagContractError):
        asyncio.run(engine.query_with_sources(_QueryRag(result), "q"))


@REQUIRES_LIGHTRAG
def test_storage_publishes_schema_two_metadata(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "kv_store_doc_status.json").write_text(
        json.dumps({"id": {"status": "processed", "chunks_list": ["c"]}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.embedding_signature.embedding_meta_fields",
        lambda: {"embedding": "e"},
    )
    storage.write_meta(tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["state"] == "published"
    assert meta["lightrag_adapter_schema"] == 2
    assert meta["lightrag_package_version"] == "1.5.7rc2"
    assert meta["parser_inputs"] == []
    assert storage.meta_is_native_published(tmp_path) is True


def test_flat_schema_two_candidate_fails_closed_until_published(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "kv_store_doc_status.json").write_text(
        json.dumps({"id": {"status": "processed", "chunks_list": ["c"]}}), encoding="utf-8"
    )
    (version / "meta.json").write_text(
        json.dumps({"provider": "lightrag", "signature": "lightrag", "lightrag_adapter_schema": 2}),
        encoding="utf-8",
    )
    assert list_kb_versions(tmp_path)[0]["ready"] is False
    payload = json.loads((version / "meta.json").read_text())
    payload["state"] = "published"
    (version / "meta.json").write_text(json.dumps(payload), encoding="utf-8")
    assert list_kb_versions(tmp_path)[0]["ready"] is True


def _write_published_version(root: Path, *, indexing_policy_value: dict | None = None) -> None:
    root.mkdir(parents=True)
    (root / "kv_store_doc_status.json").write_text(
        json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}}),
        encoding="utf-8",
    )
    (root / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": storage.ADAPTER_SCHEMA,
                "parser_bridge_schema": 1,
                "state": "published",
                "indexing_policy": indexing_policy_value or {"policy": "legacy_unpinned"},
            }
        ),
        encoding="utf-8",
    )


def test_rebuild_failure_before_index_output_keeps_previous_published_version(
    tmp_path: Path, monkeypatch
) -> None:
    kb_dir = tmp_path / "kb"
    old = kb_dir / "version-1"
    _write_published_version(old)
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def fail_before_output(*_args, **_kwargs):
        raise RuntimeError("indexing failed")

    monkeypatch.setattr(pipeline, "_run_indexing", fail_before_output)

    with pytest.raises(RuntimeError, match="indexing failed"):
        asyncio.run(
            pipeline.initialize(
                "kb",
                [str(tmp_path / "doc.md")],
                indexing_snapshot=_indexing_snapshot(),
            )
        )

    assert storage.latest_published_root(kb_dir) == old
    assert not (kb_dir / "version-2").exists()


def test_atomic_meta_failure_leaves_new_candidate_unpublished(tmp_path: Path, monkeypatch) -> None:
    kb_dir = tmp_path / "kb"
    old = kb_dir / "version-1"
    _write_published_version(old)
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def finish_index(root: Path, *_args, **_kwargs):
        (root / "kv_store_doc_status.json").write_text(
            json.dumps({"new": {"status": "processed", "chunks_list": ["chunk"]}}),
            encoding="utf-8",
        )
        return BatchOutcome(
            requested=1,
            accepted=1,
            processed=("doc.md",),
            indexing_policy={"policy": "legacy_unpinned"},
        )

    def fail_meta(*_args, **_kwargs):
        raise OSError("atomic publication failed")

    monkeypatch.setattr(pipeline, "_run_indexing", finish_index)
    monkeypatch.setattr(storage, "write_meta", fail_meta)

    with pytest.raises(OSError, match="atomic publication failed"):
        asyncio.run(
            pipeline.initialize(
                "kb",
                [str(tmp_path / "doc.md")],
                indexing_snapshot=_indexing_snapshot(),
            )
        )

    candidate = kb_dir / "version-2"
    assert candidate.is_dir()
    assert not (candidate / "meta.json").exists()
    assert storage.latest_published_root(kb_dir) == old


def test_append_metadata_refresh_failure_preserves_published_success(
    tmp_path: Path, monkeypatch
) -> None:
    kb_dir = tmp_path / "kb"
    published = kb_dir / "version-1"
    _write_published_version(
        published,
        indexing_policy_value={
            "policy": "pinned",
            "selection": {"profile_id": "profile", "model_id": "model"},
            "fingerprint": "a" * 64,
        },
    )
    original_meta = (published / "meta.json").read_bytes()
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def finish_index(*_args, **_kwargs):
        return BatchOutcome(
            requested=1,
            accepted=1,
            processed=("doc.md",),
            indexing_policy={"policy": "legacy_unpinned"},
        )

    monkeypatch.setattr(pipeline, "_run_indexing", finish_index)
    monkeypatch.setattr(
        indexing_policy,
        "snapshot_from_persisted",
        lambda _policy: _indexing_snapshot(),
    )
    monkeypatch.setattr(
        storage,
        "write_meta",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("metadata unavailable")),
    )

    assert asyncio.run(pipeline.add_documents("kb", [str(tmp_path / "doc.md")])) is True
    assert (published / "meta.json").read_bytes() == original_meta


def test_append_rejects_legacy_unpinned_index_before_mutation(tmp_path: Path, monkeypatch) -> None:
    published = tmp_path / "kb" / "version-1"
    _write_published_version(published)
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("legacy append must not reach indexing")

    monkeypatch.setattr(pipeline, "_run_indexing", unexpected)

    with pytest.raises(indexing_policy.IndexingModelChangedError, match="full re-index"):
        asyncio.run(pipeline.add_documents("kb", [str(tmp_path / "doc.md")]))


def test_append_rejects_explicit_indexing_snapshot_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    published = tmp_path / "kb" / "version-1"
    _write_published_version(published)
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("append must not reach indexing")

    monkeypatch.setattr(pipeline, "_run_indexing", unexpected)

    with pytest.raises(indexing_policy.IndexingPolicyError, match="full re-index"):
        asyncio.run(
            pipeline.add_documents(
                "kb",
                [str(tmp_path / "doc.md")],
                indexing_snapshot=_indexing_snapshot(),
            )
        )


def test_pending_policy_drift_fails_before_creating_a_version(tmp_path: Path, monkeypatch) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (tmp_path / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "pending_indexing_policy": {
                            "policy": "pending_pinned",
                            "selection": {"profile_id": "profile", "model_id": "model"},
                            "fingerprint": "a" * 64,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    def changed(_policy):
        raise indexing_policy.IndexingModelChangedError("reindex required")

    monkeypatch.setattr(indexing_policy, "snapshot_from_persisted", changed)

    with pytest.raises(indexing_policy.IndexingModelChangedError):
        asyncio.run(pipeline.initialize("kb", [str(tmp_path / "doc.md")]))

    assert not any(kb_dir.glob("version-*"))


def test_schema_two_metadata_without_processed_workspace_output_is_not_ready(
    tmp_path: Path,
) -> None:
    version = tmp_path / "version-1"
    workspace = version / "workspace"
    workspace.mkdir(parents=True)
    (version / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": 2,
                "state": "published",
                "workspace": "workspace",
            }
        ),
        encoding="utf-8",
    )
    (workspace / "kv_store_doc_status.json").write_text(
        json.dumps({"id": {"status": "failed", "chunks_list": []}}), encoding="utf-8"
    )
    assert list_kb_versions(tmp_path)[0]["ready"] is False


def test_legacy_flat_metadata_stays_visible_but_requires_reindex(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "kv_store_doc_status.json").write_text(
        json.dumps({"id": {"status": "processed", "chunks_list": ["c"]}}), encoding="utf-8"
    )
    (version / "meta.json").write_text(
        json.dumps({"provider": "lightrag", "signature": "lightrag"}), encoding="utf-8"
    )
    assert list_kb_versions(tmp_path)[0]["ready"] is True
    assert storage.meta_is_native_published(version) is False


def test_batch_outcome_only_completes_all_processed() -> None:
    assert BatchOutcome(requested=1, accepted=1, processed=("a",)).complete is True
    assert BatchOutcome(requested=2, accepted=1, processed=("a",), missing=("b",)).complete is False


def test_reconcile_counts_terminal_rows_and_missing(tmp_path: Path) -> None:
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    pipeline._status_no_progress_seconds = 0
    staged = [types.SimpleNamespace(canonical_name="a.pdf", audit_ledger=None)]

    class Rag:
        working_dir = str(tmp_path)

        async def aget_docs_by_track_id(self, _track):
            return {"doc-a": types.SimpleNamespace(file_path="a.pdf", status="processed")}

    outcome = asyncio.run(
        pipeline._reconcile(Rag(), staged, {"bad.pdf": "parse failed"}, "track", _Bridge(), None)
    )
    assert outcome.accepted == 1
    assert outcome.processed == ("a.pdf",)
    assert outcome.preflight_failed == {"bad.pdf": "parse failed"}
    assert outcome.complete is False


def test_indexing_initializes_processes_reconciles_and_finalizes(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[object] = []
    staged = types.SimpleNamespace(canonical_name="doc.pdf", process_options="F", audit_ledger=None)

    class Rag:
        working_dir = str(tmp_path)

        async def apipeline_process_enqueue_documents(self):
            events.append("process")

        async def aget_docs_by_track_id(self, track_id):
            assert track_id == "track-1"
            return {"doc-id": types.SimpleNamespace(file_path="doc.pdf", status="processed")}

    rag = Rag()
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    snapshot = _indexing_snapshot()
    freeze_calls = 0

    def freeze_default():
        nonlocal freeze_calls
        freeze_calls += 1
        return snapshot

    def stage(*_args, **kwargs):
        assert kwargs["vision_available"] is True
        return [staged], {}

    def build(*_args, **kwargs):
        assert kwargs["indexing_snapshot"] is snapshot
        return rag

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.pipeline.freeze_default_snapshot",
        freeze_default,
    )
    monkeypatch.setattr(pipeline, "_stage_documents", stage)
    monkeypatch.setattr(engine, "build_rag", build)

    async def initialize(_rag):
        events.append("initialize")

    async def enqueue(_rag, documents):
        assert documents == [staged]
        events.append("enqueue")
        return "track-1"

    async def finalize(_rag, *, cancel_pending):
        events.append(("finalize", cancel_pending))

    monkeypatch.setattr(engine, "initialize", initialize)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", finalize)

    outcome = asyncio.run(pipeline._run_indexing(tmp_path, ["doc.pdf"], None))

    assert outcome.complete is True
    assert freeze_calls == 1
    assert outcome.indexing_policy == {"policy": "pinned", "fingerprint": "a" * 64}
    assert events == ["initialize", "enqueue", "process", ("finalize", False)]


def test_partial_failure_is_typed_and_finalizes_with_cancellation(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[object] = []
    staged = types.SimpleNamespace(canonical_name="bad.pdf", process_options="F", audit_ledger=None)

    class Rag:
        working_dir = str(tmp_path)

        async def apipeline_process_enqueue_documents(self):
            return None

        async def aget_docs_by_track_id(self, _track_id):
            return {
                "doc-id": types.SimpleNamespace(
                    file_path="bad.pdf", status="failed", error_msg="parse failed"
                )
            }

    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_stage_documents", lambda *_args, **_kwargs: ([staged], {}))
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: Rag())

    async def no_op(*_args, **_kwargs):
        return None

    async def enqueue(*_args, **_kwargs):
        return "track-1"

    async def finalize(_rag, *, cancel_pending):
        events.append(("finalize", cancel_pending))

    monkeypatch.setattr(engine, "initialize", no_op)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", finalize)

    with pytest.raises(LightRagBatchError) as caught:
        asyncio.run(pipeline._run_indexing(tmp_path, ["bad.pdf"], None, _indexing_snapshot()))
    assert caught.value.outcome.failed == {"bad.pdf": "parse failed"}
    assert events == [("finalize", True)]


@pytest.mark.parametrize("failure_stage", ["initialize", "enqueue"])
def test_pre_acceptance_failure_removes_ingress_and_allows_same_name_retry(
    tmp_path: Path, monkeypatch, failure_stage: str
) -> None:
    source = tmp_path / "source" / "doc.md"
    source.parent.mkdir()
    source.write_text("body", encoding="utf-8")
    working = tmp_path / "version-1"
    attempt = 0

    class Rag:
        working_dir = str(working)

        class DocStatus:
            async def get_docs_by_ids(self, _doc_ids, *, strict):
                assert strict is True
                return {}

        doc_status = DocStatus()

        async def apipeline_process_enqueue_documents(self):
            return None

        async def aget_docs_by_track_id(self, _track_id):
            return {"doc-id": types.SimpleNamespace(file_path="doc.md", status="processed")}

    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))

    def stage(_working, paths, **_kwargs):
        staged = freeze_document(
            working,
            Path(paths[0]),
            ParsedDocument(markdown="body", engine="text_only"),
        )
        return [staged], {}

    async def initialize(_rag):
        if attempt == 0 and failure_stage == "initialize":
            raise RuntimeError("initialize rejected")

    async def enqueue(_rag, _staged):
        if attempt == 0 and failure_stage == "enqueue":
            raise RuntimeError("enqueue rejected")
        return "track-1"

    async def finalize(_rag, *, cancel_pending):
        assert cancel_pending is (attempt == 0)

    monkeypatch.setattr(pipeline, "_stage_documents", stage)
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: Rag())
    monkeypatch.setattr(engine, "_document_id", lambda name: f"doc-{name}")
    monkeypatch.setattr(engine, "initialize", initialize)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", finalize)

    with pytest.raises(RuntimeError, match=failure_stage):
        asyncio.run(pipeline._run_indexing(working, [str(source)], None, _indexing_snapshot()))
    assert not (pending_root(working) / "doc.md").exists()
    assert not (bundles_root(working) / "doc.md.bundle").exists()

    attempt = 1
    outcome = asyncio.run(
        pipeline._run_indexing(working, [str(source)], None, _indexing_snapshot())
    )
    assert outcome.complete is True


def test_enqueue_partial_commit_removes_only_confirmed_unaccepted_ingress(
    tmp_path: Path, monkeypatch
) -> None:
    sources = [tmp_path / "source" / name for name in ("accepted.md", "rejected.md")]
    sources[0].parent.mkdir()
    for source in sources:
        source.write_text(source.stem, encoding="utf-8")
    working = tmp_path / "version-1"
    status_reads: list[tuple[list[str], bool]] = []

    class DocStatus:
        async def get_docs_by_ids(self, doc_ids, *, strict):
            status_reads.append((doc_ids, strict))
            return {doc_ids[0]: types.SimpleNamespace(status="pending")}

    class Rag:
        working_dir = str(working)
        doc_status = DocStatus()

    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))

    def stage(_working, paths, **_kwargs):
        return [
            freeze_document(
                working,
                Path(path),
                ParsedDocument(markdown=Path(path).stem, engine="text_only"),
            )
            for path in paths
        ], {}

    async def enqueue(_rag, _staged):
        raise RuntimeError("doc_status partially committed")

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline, "_stage_documents", stage)
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: Rag())
    monkeypatch.setattr(engine, "_document_id", lambda name: f"doc-{name}")
    monkeypatch.setattr(engine, "initialize", no_op)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", no_op)

    with pytest.raises(RuntimeError, match="partially committed"):
        asyncio.run(
            pipeline._run_indexing(
                working,
                [str(path) for path in sources],
                None,
                _indexing_snapshot(),
            )
        )

    assert len(status_reads) == 1
    assert status_reads[0][1] is True
    assert (pending_root(working) / "accepted.md").is_file()
    assert (bundles_root(working) / "accepted.md.bundle").is_dir()
    assert not (pending_root(working) / "rejected.md").exists()
    assert not (bundles_root(working) / "rejected.md.bundle").exists()


def test_enqueue_status_read_failure_retains_all_ingress(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source" / "doc.md"
    source.parent.mkdir()
    source.write_text("body", encoding="utf-8")
    working = tmp_path / "version-1"

    class DocStatus:
        async def get_docs_by_ids(self, _doc_ids, *, strict):
            assert strict is True
            raise RuntimeError("status unavailable")

    class Rag:
        working_dir = str(working)
        doc_status = DocStatus()

    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))

    def stage(_working, paths, **_kwargs):
        return [
            freeze_document(
                working,
                Path(paths[0]),
                ParsedDocument(markdown="body", engine="text_only"),
            )
        ], {}

    async def enqueue(_rag, _staged):
        raise ValueError("enqueue failed")

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline, "_stage_documents", stage)
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: Rag())
    monkeypatch.setattr(engine, "initialize", no_op)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", no_op)

    with pytest.raises(ValueError, match="enqueue failed"):
        asyncio.run(pipeline._run_indexing(working, [str(source)], None, _indexing_snapshot()))

    assert (pending_root(working) / "doc.md").is_file()
    assert (bundles_root(working) / "doc.md.bundle").is_dir()


@pytest.mark.parametrize("operation", ["initialize", "add_documents"])
def test_public_initial_ingestion_retains_uncertain_ingress(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    source = tmp_path / "source" / "doc.md"
    source.parent.mkdir()
    source.write_text("body", encoding="utf-8")
    staged_working: Path | None = None

    class DocStatus:
        async def get_docs_by_ids(self, _doc_ids, *, strict):
            assert strict is True
            raise RuntimeError("status unavailable")

    class Rag:
        doc_status = DocStatus()

    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path / "knowledge-bases"))

    def stage(working, paths, **_kwargs):
        nonlocal staged_working
        staged_working = working
        return [
            freeze_document(
                working,
                Path(paths[0]),
                ParsedDocument(markdown="body", engine="text_only"),
            )
        ], {}

    async def enqueue(_rag, _staged):
        raise ValueError("original enqueue failure")

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(pipeline, "_stage_documents", stage)
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: Rag())
    monkeypatch.setattr(engine, "initialize", no_op)
    monkeypatch.setattr(engine, "enqueue", enqueue)
    monkeypatch.setattr(engine, "finalize", no_op)

    with pytest.raises(ValueError, match="original enqueue failure"):
        asyncio.run(
            getattr(pipeline, operation)(
                "kb",
                [str(source)],
                indexing_snapshot=types.SimpleNamespace(
                    vision_available=True,
                    persisted_policy=lambda: {"policy": "legacy_unpinned"},
                ),
            )
        )

    assert staged_working is not None
    assert (pending_root(staged_working) / "doc.md").is_file()
    assert (bundles_root(staged_working) / "doc.md.bundle").is_dir()


def test_zero_accepted_candidate_cleanup_removes_empty_version(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    pending_root(version).mkdir(parents=True)
    bundles_root(version).mkdir(parents=True)

    LightRagPipeline(kb_base_dir=str(tmp_path))._remove_zero_accepted_candidate(version)

    assert not version.exists()


def test_append_rejects_corrupt_or_unpublished_existing_version(
    tmp_path: Path, monkeypatch
) -> None:
    version = tmp_path / "kb" / "version-1"
    workspace = version / "workspace"
    workspace.mkdir(parents=True)
    (version / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": 2,
                "parser_bridge_schema": 1,
                "state": "published",
                "workspace": "workspace",
            }
        ),
        encoding="utf-8",
    )
    (workspace / "kv_store_doc_status.json").write_text(
        json.dumps({"failed": {"status": "failed", "chunks_list": []}}),
        encoding="utf-8",
    )
    before = {
        path.relative_to(version): path.read_bytes()
        for path in version.rglob("*")
        if path.is_file()
    }
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    with pytest.raises(LightRagNeedsReindexError, match="unpublished, or corrupt"):
        asyncio.run(
            pipeline.add_documents(
                "kb",
                [str(tmp_path / "new.md")],
            )
        )

    assert not (tmp_path / "kb" / "version-2").exists()
    assert {
        path.relative_to(version): path.read_bytes()
        for path in version.rglob("*")
        if path.is_file()
    } == before


def test_search_failure_is_not_reported_as_empty_success(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "version-1"
    root.mkdir()
    pipeline = LightRagPipeline(kb_base_dir=str(tmp_path))
    monkeypatch.setattr(storage, "latest_published_root", lambda _kb_dir: root)
    monkeypatch.setattr(pipeline, "_resolve_mode", lambda *_args: "hybrid")
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(engine, "build_rag", lambda *_args, **_kwargs: object())

    async def no_op(*_args, **_kwargs):
        return None

    async def fail(*_args, **_kwargs):
        raise engine.LightRagContractError("retrieval failed")

    monkeypatch.setattr(engine, "initialize", no_op)
    monkeypatch.setattr(engine, "query_with_sources", fail)
    monkeypatch.setattr(engine, "finalize", no_op)

    result = asyncio.run(pipeline.search("question", "kb"))

    assert result["content"] == ""
    assert result["sources"] == []
    assert result["error_type"] == "retrieval_error"


def test_legacy_search_requires_reindex_without_mutating_files(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    version = kb / "version-1"
    version.mkdir(parents=True)
    meta = version / "meta.json"
    meta.write_text(json.dumps({"provider": "lightrag", "signature": "lightrag"}), encoding="utf-8")
    (version / "kv_store_doc_status.json").write_text(
        json.dumps({"id": {"status": "processed", "chunks_list": ["c"]}}),
        encoding="utf-8",
    )
    before = {path.name: path.read_bytes() for path in version.iterdir()}

    result = asyncio.run(LightRagPipeline(kb_base_dir=str(tmp_path)).search("q", "kb"))

    assert result["needs_reindex"] is True
    assert {path.name: path.read_bytes() for path in version.iterdir()} == before
