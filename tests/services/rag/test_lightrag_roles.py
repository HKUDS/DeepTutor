"""Four-role calls, task freezing, legacy policies, and write ownership contracts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.config.lightrag_roles import LightRagRoleModels
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.rag.pipelines.lightrag import engine, roles, storage
from deeptutor.services.rag.pipelines.lightrag import indexing_policy as policy
from deeptutor.services.rag.pipelines.lightrag.pipeline import BatchOutcome, LightRagPipeline
from deeptutor.services.rag.pipelines.lightrag.write_lock import write_ownership


def choice(number: int, effort: str | None = None) -> dict:
    result = {"profile_id": f"p{number}", "model_id": f"m{number}"}
    if effort is not None:
        result["reasoning_effort"] = effort
    return result


@pytest.fixture
def role_environment(tmp_path, monkeypatch):
    user = CurrentUser(
        id="role-user",
        username="tester",
        role="user",
        scope=UserScope(kind="user", user_id="role-user", root=tmp_path / "owner"),
    )
    token = set_current_user(user)
    models = LightRagRoleModels.model_validate(
        {
            "base": choice(0),
            "extract": {
                "mode": "inherit",
                "reasoning_effort": "none",
                "max_async": 2,
                "timeout": 101,
            },
            "keyword": {
                "mode": "model",
                "selection": choice(1),
                "reasoning_effort": "low",
                "max_async": 3,
                "timeout": 102,
            },
            "query": {
                "mode": "model",
                "selection": choice(2),
                "reasoning_effort": "high",
                "max_async": 4,
                "timeout": 103,
            },
            "vlm": {
                "mode": "model",
                "selection": choice(3),
                "reasoning_effort": "none",
                "max_async": 5,
                "timeout": 104,
            },
        }
    )
    state = {
        "settings": {"role_models": models.model_dump()},
        "allowed": {f"p{i}" for i in range(4)},
        "configs": {
            f"p{i}": LLMConfig(
                model=f"model-{i}",
                binding="custom",
                provider_name="custom",
                api_key="private-key",
                base_url=f"https://name:password@provider-{i}.test/v1?key=private",
                reasoning_effort="medium",
            )
            for i in range(4)
        },
        "vision": {f"model-{i}": i == 3 for i in range(4)},
    }

    def allowed(value):
        if value["profile_id"] not in state["allowed"]:
            raise PermissionError("Model access was revoked.")
        return value

    def resolve(value):
        selection = LLMSelection.from_payload(value)
        config = state["configs"][selection.profile_id]
        return config.model_copy(
            update={"reasoning_effort": selection.reasoning_effort or config.reasoning_effort}
        )

    def options():
        return {
            "active": choice(0),
            "options": [
                {
                    **choice(i),
                    "model": f"model-{i}",
                    "provider": "custom",
                    "model_name": f"Model {i}",
                    "profile_name": f"Provider {i}",
                    "is_active_default": i == 0,
                    "supported_reasoning_efforts": ["none", "low", "medium", "high"],
                }
                for i in range(4)
                if f"p{i}" in state["allowed"]
            ],
        }

    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings", lambda: deepcopy(state["settings"])
    )
    monkeypatch.setattr(roles, "allowed_llm_options", options)
    monkeypatch.setattr(roles, "apply_allowed_llm_selection", allowed)
    monkeypatch.setattr(roles, "resolve_llm_config_for_selection", resolve)
    monkeypatch.setattr(
        roles, "supports_vision", lambda _binding, model: state["vision"].get(model, False)
    )
    monkeypatch.setattr(policy, "apply_allowed_llm_selection", allowed)
    monkeypatch.setattr(policy, "resolve_llm_config_for_selection", resolve)
    monkeypatch.setattr(
        policy, "supports_vision", lambda _binding, model: state["vision"].get(model, False)
    )
    monkeypatch.setattr(policy, "_active_catalog_selection", lambda: choice(0))
    yield state
    reset_current_user(token)


def test_role_contract_distinguishes_inherit_explicit_disabled_and_none():
    models = LightRagRoleModels.model_validate(
        {"base": choice(0, "high"), "extract": {"reasoning_effort": "none"}}
    )
    assert models.selection_for("query").reasoning_effort == "high"
    assert models.selection_for("extract").reasoning_effort == "none"
    assert models.selection_for("vlm") is None
    for invalid in (
        {"base": choice(0), "query": {"mode": "disabled"}},
        {"base": choice(0), "vlm": {"mode": "disabled", "selection": choice(3)}},
        {"base": choice(0), "query": {"mode": "model"}},
        {"base": choice(0), "query": {"mode": "inherit", "selection": choice(1)}},
        {"base": choice(0), "query": {"max_async": 0}},
        {"base": choice(0), "query": {"timeout": True}},
        {"base": {**choice(0), "api_key": "private"}},
    ):
        with pytest.raises(ValidationError):
            LightRagRoleModels.model_validate(invalid)


def test_new_settings_do_not_fall_back_to_chat(role_environment, monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.config.resolve_lightrag_query_llm_config",
        lambda: pytest.fail("new settings must not resolve chat fallback"),
    )
    first = roles.resolve_query_roles()
    assert first["keyword"].config.model == "model-1"
    assert first["query"].config.model == "model-2"
    role_environment["settings"]["role_models"]["query"] = {"mode": "inherit"}
    role_environment["settings"]["role_models"]["base"] = choice(3)
    second = roles.resolve_query_roles()
    assert second["query"].config.model == "model-3"
    assert first["query"].config.model == "model-2"
    assert (first["query"].max_async, first["query"].timeout) == (4, 103)


def test_all_four_native_roles_call_their_frozen_models(role_environment, monkeypatch, tmp_path):
    pytest.importorskip("lightrag")
    calls = []

    def build(config, *, allow_multimodal):
        async def complete(prompt, **kwargs):
            calls.append((config.model, config.reasoning_effort, allow_multimodal, kwargs))
            return config.model

        return complete

    monkeypatch.setattr("deeptutor.services.llm.client.build_model_func_for_config", build)
    monkeypatch.setattr(engine, "_require_exact_version", lambda: None)
    monkeypatch.setattr(engine, "_register_parser", lambda: None)
    monkeypatch.setattr(engine, "_controlled_class", lambda: lambda **kwargs: kwargs)
    monkeypatch.setattr(engine, "build_embedding_func", lambda **kwargs: "independent embedding")
    monkeypatch.setattr(engine, "constructor_kwargs_from_settings", dict)
    monkeypatch.setattr(engine, "indexing_kwargs_from_settings", dict)
    snapshot = policy.freeze_roles()
    queries = roles.resolve_query_roles()
    indexed = engine.build_rag(tmp_path, indexing_snapshot=snapshot, enable_vlm=True)
    queried = engine.build_rag(tmp_path, query_roles=queries)

    async def exercise():
        await indexed["role_llm_configs"]["extract"].func("extract")
        await indexed["role_llm_configs"]["vlm"].func("vision", image_inputs=[{"base64": "image"}])
        await queried["role_llm_configs"]["keyword"].func("keyword")
        await queried["role_llm_configs"]["query"].func("query")

    asyncio.run(exercise())
    assert [(model, effort, vision) for model, effort, vision, _ in calls] == [
        ("model-0", "none", False),
        ("model-3", "none", True),
        ("model-1", "low", False),
        ("model-2", "high", False),
    ]
    assert all(kwargs["allow_image_fallback"] is False for *_, kwargs in calls)
    all_roles = {**indexed["role_llm_configs"], **queried["role_llm_configs"]}
    assert {name: (value.max_async, value.timeout) for name, value in all_roles.items()} == {
        "extract": (2, 101),
        "vlm": (5, 104),
        "keyword": (3, 102),
        "query": (4, 103),
    }
    assert len({value.metadata["model"] for value in all_roles.values()}) == 4


def test_index_policy_freezes_defaults_and_limits_but_refreshes_credentials(role_environment):
    snapshot = policy.freeze_roles()
    persisted = snapshot.persisted_policy()
    role_environment["settings"]["role_models"]["extract"]["max_async"] = 12
    role_environment["settings"]["role_models"]["extract"]["timeout"] = 900
    role_environment["settings"]["role_models"]["base"] = choice(2)
    role_environment["configs"]["p0"].api_key = "rotated-secret"
    fresh = policy.revalidate_snapshot(snapshot)
    assert fresh.extract.config.api_key == "rotated-secret"
    assert fresh.extract.config.model == "model-0"
    assert fresh.limits["extract"] == {"max_async": 2, "timeout": 101}
    assert fresh.persisted_policy() == persisted
    assert policy.freeze_roles().extract.config.model == "model-2"
    serialized = json.dumps(persisted)
    for forbidden in ("private", "password", "api_key", "role-user"):
        assert forbidden not in serialized
    assert "endpoint" not in json.dumps(policy.public_policy(persisted))


@pytest.mark.parametrize(
    "change", ["endpoint", "model", "wire_api", "context_window", "access", "vision"]
)
def test_invalid_pinned_identity_blocks_before_writes(role_environment, change):
    snapshot = policy.freeze_roles()
    if change == "endpoint":
        role_environment["configs"]["p0"].effective_url = "https://other.test/v1"
    elif change == "model":
        role_environment["configs"]["p0"].model = "different"
    elif change == "wire_api":
        role_environment["configs"]["p0"].api_format = "openai_responses"
    elif change == "context_window":
        role_environment["configs"]["p0"].context_window = 100000
    elif change == "access":
        role_environment["allowed"].remove("p3")
    else:
        role_environment["vision"]["model-3"] = False
    with pytest.raises(policy.IndexingPolicyError):
        policy.revalidate_snapshot(snapshot)


def test_unsupported_reasoning_and_nonvision_inheritance_fail(role_environment):
    models = deepcopy(role_environment["settings"]["role_models"])
    models["query"]["reasoning_effort"] = "max"
    with pytest.raises(ValueError, match="reasoning"):
        roles.validate_models(LightRagRoleModels.model_validate(models))
    models["query"]["reasoning_effort"] = "high"
    models["vlm"] = {"mode": "inherit"}
    with pytest.raises(ValueError, match="image inputs"):
        roles.validate_models(LightRagRoleModels.model_validate(models))


def test_legacy_single_policy_keeps_its_original_algorithm_and_vision(role_environment):
    legacy = policy.freeze_snapshot(choice(3, "none")).persisted_policy()
    adapted = policy.snapshot_from_persisted(legacy)
    assert adapted.vision_available
    assert adapted.extract.fingerprint == legacy["fingerprint"]
    assert adapted.vlm.fingerprint == legacy["fingerprint"]
    assert adapted.persisted_policy() == legacy
    assert "schema_version" not in adapted.persisted_policy()
    del legacy["vision_available"]
    with pytest.raises(policy.IndexingModelChangedError, match="historical vision"):
        policy.snapshot_from_persisted(legacy)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"policy": "legacy_unpinned"},
        {"policy": "pinned", "schema_version": 99},
        {"policy": "pinned", "schema_version": 2, "extract": {}, "vlm": {"mode": "enabled"}},
        {
            "policy": "pinned",
            "schema_version": 2,
            "extract": {},
            "vlm": {"mode": "disabled", "snapshot": {}},
        },
    ],
)
def test_malformed_policies_never_acquire_current_defaults(role_environment, bad):
    with pytest.raises(policy.IndexingPolicyError):
        policy.snapshot_from_persisted(bad)


def test_disabled_vlm_requires_rebuild_for_explicit_analysis(role_environment):
    disabled = policy.freeze_roles({"extract": choice(0), "vlm": {"mode": "disabled"}})
    assert not disabled.vision_available
    assert policy.with_image_analysis(disabled, False).vlm is None
    with pytest.raises(policy.IndexingModelChangedError, match="full re-index"):
        policy.with_image_analysis(disabled, True)
    enabled = policy.freeze_roles(
        {"extract": choice(0), "vlm": {"mode": "enabled", "selection": choice(3)}}
    )
    assert policy.with_image_analysis(enabled, True).vision_available
    assert (
        policy.with_image_analysis(enabled, False).persisted_policy() == enabled.persisted_policy()
    )


def _published(path: Path, value: dict):
    path.mkdir(parents=True, exist_ok=True)
    (path / "kv_store_doc_status.json").write_text('{"doc": {"status": "processed"}}')
    (path / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": storage.ADAPTER_SCHEMA,
                "parser_bridge_schema": 1,
                "state": "published",
                "indexing_policy": value,
            }
        )
    )


def test_stale_queued_target_is_rejected_before_graph_write(
    role_environment, tmp_path, monkeypatch
):
    kb = tmp_path / "kb"
    first = policy.freeze_roles()
    _published(kb / "version-1", first.persisted_policy())
    accepted = policy.bind_target(first, kb)
    _published(kb / "version-2", first.persisted_policy())
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(
        pipeline, "_run_indexing", lambda *_args: pytest.fail("stale job wrote graph")
    )
    with pytest.raises(policy.IndexingPolicyError, match="target index"):
        asyncio.run(pipeline.add_documents("kb", ["doc.md"], accepted_indexing_snapshot=accepted))
    assert storage.latest_published_root(kb) == kb / "version-2"


def test_two_writers_cannot_own_one_knowledge_base(tmp_path):
    kb = tmp_path / "kb"
    with write_ownership(kb):
        with pytest.raises(policy.IndexingPolicyError, match="Another indexing"):
            with write_ownership(kb):
                pytest.fail("both writers acquired ownership")
    with write_ownership(kb):
        pass


def test_failed_terminal_persistence_does_not_publish_candidate(
    role_environment, tmp_path, monkeypatch
):
    snapshot = policy.freeze_roles()
    kb = tmp_path / "kb"
    _published(kb / "version-1", snapshot.persisted_policy())
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(storage, "has_output", lambda _root: True)

    async def indexed(root, *_args):
        (root / "kv_store_doc_status.json").write_text('{"doc": {"status": "processed"}}')
        return BatchOutcome(
            1, accepted=1, processed=("doc.md",), indexing_policy=snapshot.persisted_policy()
        )

    def fail_terminal(_root):
        raise OSError("terminal persistence failed")

    monkeypatch.setattr(pipeline, "_run_indexing", indexed)
    with pytest.raises(OSError, match="terminal persistence"):
        asyncio.run(
            pipeline.initialize(
                "kb", ["doc.md"], indexing_snapshot=snapshot, before_publish=fail_terminal
            )
        )
    assert storage.latest_published_root(kb) == kb / "version-1"
    assert not (kb / "version-2" / "meta.json").exists()


def test_prepared_terminal_is_not_announced_or_read_as_completed(tmp_path, monkeypatch):
    from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker

    entry = {"status": "processing"}

    class Manager:
        def __init__(self, **_kwargs):
            pass

        def update_kb_status(self, *, status, progress, **_kwargs):
            entry.update(status=status, progress=progress)

        def get_kb_entry(self, _name):
            return entry

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", Manager)
    monkeypatch.setattr(
        "deeptutor.knowledge.progress_events.emit_task_progress", lambda *_args: None
    )
    tracker = ProgressTracker("kb", tmp_path)
    tracker.task_id = "rebuild-1"
    seen = []
    tracker.set_callback(lambda progress: seen.append(progress["stage"]))
    tracker.update(
        ProgressStage.COMPLETED,
        "Rebuild complete",
        current=1,
        total=1,
        indexed_count=1,
        index_changed=True,
        index_action="reindex",
        publication_version="version-2",
    )
    tracker.verify_terminal(
        current=1, total=1, indexed_count=1, index_action="reindex", publication_version="version-2"
    )
    assert entry["status"] == "processing"
    assert seen == ["processing_documents"]
    assert tracker.get_progress()["stage"] == "processing_documents"
    # A process interrupted here has a prepared record, not a published index.
    _published(tmp_path / "kb" / "version-2", {"policy": "pinned"})
    assert tracker.get_progress()["stage"] == "completed"


@pytest.mark.parametrize("lost_write", ["progress_file", "kb_status"])
def test_lost_terminal_write_is_detected_before_publication(tmp_path, monkeypatch, lost_write):
    from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker

    entry = {"status": "ready"}

    class Manager:
        def __init__(self, **_kwargs):
            pass

        def update_kb_status(self, *, status, progress, **_kwargs):
            if lost_write == "kb_status":
                raise OSError("status storage unavailable")
            entry.update(status=status, progress=progress)

        def get_kb_entry(self, _name):
            return entry

    monkeypatch.setattr("deeptutor.knowledge.manager.KnowledgeBaseManager", Manager)
    if lost_write == "progress_file":

        def fail(*_args):
            raise OSError("progress storage unavailable")

        monkeypatch.setattr("deeptutor.knowledge.progress_tracker.atomic_write_json", fail)
    tracker = ProgressTracker("kb", tmp_path)
    tracker.task_id = "new-task"
    tracker.update(
        ProgressStage.COMPLETED,
        current=1,
        total=1,
        indexed_count=1,
        index_changed=True,
        index_action="reindex",
        publication_version="version-2",
    )
    with pytest.raises(RuntimeError, match="terminal state was not persisted"):
        tracker.verify_terminal(
            current=1,
            total=1,
            indexed_count=1,
            index_action="reindex",
            publication_version="version-2",
        )


def test_concurrent_first_writers_do_not_publish_different_policies(
    role_environment, tmp_path, monkeypatch
):
    snapshot = policy.bind_target(policy.freeze_roles(), tmp_path / "kb")
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(pipeline, "_clear_pending_policy", lambda _name: None)
    monkeypatch.setattr(
        storage, "write_meta", lambda root, *, indexing_policy: _published(root, indexing_policy)
    )

    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def indexed(root, *_args):
            (root / "kv_store_doc_status.json").write_text('{"doc": {"status": "processed"}}')
            entered.set()
            await release.wait()
            return BatchOutcome(
                1, accepted=1, processed=("doc.md",), indexing_policy=snapshot.persisted_policy()
            )

        monkeypatch.setattr(pipeline, "_run_indexing", indexed)
        first = asyncio.create_task(
            pipeline.add_documents("kb", ["doc.md"], accepted_indexing_snapshot=snapshot)
        )
        await entered.wait()
        try:
            with pytest.raises(policy.IndexingPolicyError, match="Another indexing"):
                await pipeline.add_documents(
                    "kb", ["other.md"], accepted_indexing_snapshot=snapshot
                )
        finally:
            release.set()
        assert await first
        with pytest.raises(policy.IndexingPolicyError, match="target index"):
            await pipeline.add_documents("kb", ["other.md"], accepted_indexing_snapshot=snapshot)

    asyncio.run(exercise())
    published = storage.latest_published_root(tmp_path / "kb")
    assert published.name == "version-1"
    assert (
        storage.read_published_policy(published)["extract"]["fingerprint"]
        == snapshot.extract.fingerprint
    )


def test_pending_policy_change_invalidates_a_queued_first_write(role_environment, tmp_path):
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    kb = tmp_path / "kb"
    kb.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    original = policy.freeze_roles(policy=policy.POLICY_PENDING)
    manager.config["knowledge_bases"]["kb"] = {
        "path": "kb",
        "rag_provider": "lightrag",
        "pending_indexing_policy": original.persisted_policy(),
    }
    manager._save_config()
    accepted = policy.bind_target(original, kb)
    replacement = policy.freeze_roles(
        {"extract": choice(1), "vlm": {"mode": "disabled"}}, policy=policy.POLICY_PENDING
    )
    manager.config["knowledge_bases"]["kb"]["pending_indexing_policy"] = (
        replacement.persisted_policy()
    )
    manager._save_config()
    with pytest.raises(policy.IndexingPolicyError, match="pending policy changed"):
        policy.validate_target(accepted, kb)


def test_queued_rebuild_rejects_same_version_append_but_append_remains_valid(
    role_environment, tmp_path
):
    kb = tmp_path / "kb"
    snapshot = policy.freeze_roles()
    root = kb / "version-1"
    _published(root, snapshot.persisted_policy())
    rebuild = policy.bind_target(snapshot, kb, protect_contents=True)
    append = policy.bind_target(snapshot, kb)
    (root / "kv_store_doc_status.json").write_text(
        '{"doc": {"status": "processed"}, "later": {"status": "processed"}}'
    )
    with pytest.raises(policy.IndexingPolicyError, match="target index"):
        policy.validate_target(rebuild, kb)
    policy.validate_target(append, kb)


def test_disabled_vision_keeps_table_and_equation_processing(tmp_path, monkeypatch):
    pipeline = LightRagPipeline(str(tmp_path))
    from dataclasses import dataclass

    from deeptutor.services.rag.pipelines.lightrag import ingress

    @dataclass
    class Staged:
        process_options: str = "ite"

    monkeypatch.setattr(
        "deeptutor.services.parsing.get_parse_service",
        lambda: SimpleNamespace(parse=lambda path: object()),
    )
    monkeypatch.setattr(ingress, "freeze_document", lambda *args: Staged())
    disabled, failures = pipeline._stage_documents(tmp_path, ["doc.md"], vision_available=False)
    enabled, _ = pipeline._stage_documents(tmp_path, ["doc.md"], vision_available=True)
    assert not failures
    assert disabled[0].process_options == "te"
    assert enabled[0].process_options == "ite"


@pytest.mark.asyncio
async def test_github_sync_freezes_policy_before_download(role_environment, tmp_path, monkeypatch):
    from deeptutor.services.github_source import sync

    kb = tmp_path / "kb"
    pinned = policy.freeze_roles()
    _published(kb / "version-1", pinned.persisted_policy())
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider", lambda *args: "lightrag"
    )
    recorded = []
    monkeypatch.setattr(
        "deeptutor.knowledge.manager.KnowledgeBaseManager",
        lambda **kwargs: SimpleNamespace(
            update_github_source_state=lambda **data: recorded.append(data)
        ),
    )
    accepted = []

    async def add_documents(**kwargs):
        accepted.append(kwargs["accepted_indexing_snapshot"])
        return 1

    monkeypatch.setattr("deeptutor.knowledge.add_documents.add_documents", add_documents)

    class Client:
        async def get_latest_commit_sha(self, *args):
            role_environment["settings"]["role_models"]["base"] = choice(2)
            return "new-sha"

        async def get_tree(self, *args, **kwargs):
            return [SimpleNamespace(path="doc.md", type="blob")]

        async def download_file(self, *args):
            return b"test source"

    result = await sync.sync_source(
        "kb", {"id": "src", "repo": "owner/repo"}, base_dir=str(tmp_path), client=Client()
    )
    assert result.ok
    assert accepted[0].extract.fingerprint == pinned.extract.fingerprint
    assert accepted[0].vlm.fingerprint == pinned.vlm.fingerprint
    assert accepted[0].target_bound
    assert recorded[0]["last_synced_sha"] == "new-sha"


@pytest.mark.parametrize("outcome_kind", ["partial_append", "metadata_refresh_failure"])
def test_native_workspace_append_invalidates_queued_rebuild_without_meta_change(
    role_environment, tmp_path, monkeypatch, outcome_kind
):
    from deeptutor.services.rag.pipelines.lightrag.pipeline import LightRagBatchError

    kb = tmp_path / "kb"
    root = kb / "version-1"
    snapshot = policy.freeze_roles()
    _published(root, snapshot.persisted_policy())
    workspace = root / engine.workspace_for(root)
    workspace.mkdir()
    status = workspace / "kv_store_doc_status.json"
    (root / status.name).rename(status)
    before_meta = (root / "meta.json").read_bytes()
    rebuild = policy.bind_target(snapshot, kb, protect_contents=True)
    append = policy.bind_target(snapshot, kb)
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def append_native(*args):
        status.write_text('{"doc":{"status":"processed"},"later":{"status":"processed"}}')
        result = BatchOutcome(
            requested=2 if outcome_kind == "partial_append" else 1,
            accepted=2 if outcome_kind == "partial_append" else 1,
            processed=("later.md",),
            failed={"bad.md": "provider rejected"} if outcome_kind == "partial_append" else {},
            indexing_policy=snapshot.persisted_policy(),
        )
        if outcome_kind == "partial_append":
            raise LightRagBatchError(result)
        return result

    def fail_metadata(*args, **kwargs):
        raise OSError("metadata refresh failed")

    monkeypatch.setattr(pipeline, "_run_indexing", append_native)
    monkeypatch.setattr(storage, "write_meta", fail_metadata)
    if outcome_kind == "partial_append":
        with pytest.raises(LightRagBatchError):
            asyncio.run(
                pipeline.add_documents(
                    "kb", ["later.md", "bad.md"], accepted_indexing_snapshot=append
                )
            )
    else:
        assert asyncio.run(
            pipeline.add_documents("kb", ["later.md"], accepted_indexing_snapshot=append)
        )
    assert (root / "meta.json").read_bytes() == before_meta
    assert storage.latest_published_root(kb) == root
    with pytest.raises(policy.IndexingPolicyError, match="target index"):
        policy.validate_target(rebuild, kb)
    policy.validate_target(append, kb)


@pytest.mark.parametrize("model", ["qwen3-32b", "deepseek-r1"])
def test_custom_binary_reasoning_choices_match_actual_request(model):
    from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
    from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts
    from deeptutor.services.provider_registry import find_by_name

    assert supported_reasoning_efforts("custom", model) == ["minimal", "high"]
    assert supported_reasoning_efforts(
        "custom", model, metadata={"codex_supported_reasoning_levels": ["none", "low", "high"]}
    ) == ["high"]
    provider = OpenAICompatProvider(
        api_key="synthetic", default_model=model, spec=find_by_name("custom"), configure_env=False
    )
    disabled = provider._build_kwargs(
        [{"role": "user", "content": "test"}], None, model, 100, 0, "minimal", None
    )
    enabled = provider._build_kwargs(
        [{"role": "user", "content": "test"}], None, model, 100, 0, "high", None
    )
    if "qwen" in model:
        assert disabled["extra_body"]["enable_thinking"] is False
        assert enabled["extra_body"]["enable_thinking"] is True
    else:
        assert disabled["extra_body"]["thinking"]["type"] == "disabled"
        assert enabled["extra_body"]["thinking"]["type"] == "enabled"


def test_binary_provider_none_is_rejected_before_snapshot(role_environment):
    role_environment["configs"]["p0"].model = "qwen3-32b"
    # Use the real capability mapper with the same catalog model name.
    options = roles.allowed_llm_options

    def catalog():
        value = options()
        value["options"][0]["model"] = "qwen3-32b"
        return value

    from unittest.mock import patch

    with patch.object(roles, "allowed_llm_options", catalog):
        with pytest.raises(policy.IndexingPolicyError, match="reasoning effort"):
            policy.freeze_roles()


def test_fresh_defaults_do_not_enter_legacy_model_or_vision_fallback(role_environment, tmp_path):
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    fresh = service.load_lightrag()
    assert fresh["version"] == 2
    role_environment["settings"] = fresh
    with pytest.raises(policy.IndexingPolicyError, match="base model"):
        policy.freeze_roles()
    with pytest.raises(ValueError, match="base model"):
        roles.resolve_query_roles()
    # An old-form explicit model input on a fresh configuration still defaults VLM off.
    created = policy.freeze_roles(choice(3))
    assert created.vlm is None
    legacy_path = service.path_for("lightrag")
    legacy_path.write_text('{"llm_profile_id":"p3","llm_model_id":"m3"}')
    legacy = service.load_lightrag()
    assert legacy["version"] == 1
    role_environment["settings"] = legacy
    # The compatibility path retains historical vision semantics.
    assert policy.freeze_roles(choice(3)).vlm is not None
