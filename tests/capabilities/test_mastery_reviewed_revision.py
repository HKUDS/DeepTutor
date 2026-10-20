"""Reviewed outline edits: real SQLite isolation, atomicity, and exact payloads."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.mastery.tools import (
    MasteryReviseTool,
    _plan_module_revision,
    _revise_specs,
)
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    MasteryInteraction,
    PendingQuestion,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.outline_revision import exact_diff
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningConflictError, LearningStore


@pytest.fixture
def system(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    modules = [
        LearningModule(
            id=f"m{i}",
            name=f"Module {i}",
            order=i,
            objective=f"Purpose {i}",
            knowledge_points=[
                KnowledgePoint(
                    id=f"p{i}",
                    name=f"Objective {i}",
                    type=KnowledgeType.CONCEPT,
                    module_id=f"m{i}",
                    prerequisite_ids=["p0"] if i == 1 else [],
                    required_visual_tasks=["relationship"] if i == 0 else [],
                )
            ],
        )
        for i in range(3)
    ]
    service.replace_modules_for_path("path", modules)

    def prepare(tx):
        tx.put_topic(
            TopicMetadata(path_id="path"),
            [
                TopicSource(
                    id="source",
                    kind=TopicSourceKind.BOOK,
                    label="Synthetic source",
                )
            ],
        )
        tx.progress.modules[0].knowledge_points[0].topic_source_ids = ["source"]
        tx.progress.mastery_levels = {"p0": 0.3, "p2": 1.0}
        tx.progress.qualitative_mastery = {"p2": True}
        tx.progress.feynman_explanations = {"p2": "The comparison finally helped."}
        pending = PendingQuestion(
            question_id="question",
            knowledge_point_id="p0",
            module_id="m0",
            prompt="Explain the relationship",
            expected_answer="Because of the boundary",
        )
        tx.progress.pending_question = pending
        tx.put_interaction(
            MasteryInteraction(
                interaction_id="question",
                path_id="path",
                question=pending,
                session_id="session",
            )
        )

    store.mutate("path", prepare)
    return store, service


def revisions():
    return [
        {
            "module_id": f"m{i}",
            "rewrite": [
                {
                    "knowledge_point_id": f"p{i}",
                    "name": f"Revised objective {i}",
                }
            ],
        }
        for i in range(2)
    ]


def plan_revisions(progress, edits):
    specs, error = _revise_specs({"modules": edits})
    if error:
        raise ValueError(error)
    return _plan_module_revision(progress, specs)[0]


def preview(system, edits=None):
    store, service = system
    progress = store.load("path")
    return service.preview_module_revision(
        "path",
        plan_revisions(progress, edits or revisions()),
        expected_revision=progress.version,
        session_id="session",
    )


def state(progress):
    return progress.model_dump(mode="json", exclude={"version", "updated_at"})


def apply_diff(before, changes):
    result = deepcopy(before)
    for change in changes:
        parts = [x.replace("~1", "/").replace("~0", "~") for x in change["path"].split("/")[1:]]
        target = result
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        if change["before_exists"]:
            assert target[key] == change["before"]
        if change["after_exists"]:
            target[key] = deepcopy(change["after"])
        else:
            del target[key]
    return result


def test_preview_is_pure_and_commit_is_exact_and_retry_safe(system):
    store, service = system
    before = store.load("path")
    interaction = store.get_active_interaction("path").model_dump(mode="json")
    result, proposed = preview(system)
    assert result["module_order_changed"] is False
    assert result["before_module_order"] == result["proposed_module_order"]
    assert store.load("path").model_dump() == before.model_dump()
    assert store.get_active_interaction("path").model_dump(mode="json") == interaction
    assert apply_diff(state(before), result["changes"]) == state(proposed)
    assert proposed.modules[1].knowledge_points[0].prerequisite_ids == [
        proposed.modules[0].knowledge_points[0].id
    ]
    assert proposed.modules[0].knowledge_points[0].required_visual_tasks == ["relationship"]
    assert proposed.modules[0].knowledge_points[0].topic_source_ids == ["source"]
    assert proposed.mastery_levels["p2"] == 1
    assert proposed.feynman_explanations["p2"] == "The comparison finally helped."
    assert "p0" not in proposed.mastery_levels
    assert proposed.pending_question is None
    assert result["effects"]["active_interaction_removed"] is True
    committed, receipt = service.commit_module_revision(
        "path",
        result["preview_id"],
        session_id="session",
    )
    assert state(committed) == state(proposed)
    assert committed.version == before.version + 1
    assert not receipt["replayed"]
    assert store.get_active_interaction("path") is None
    # A fresh service (including a process restart) can safely retry the receipt.
    retry, receipt2 = LearningService(LearningStore(root=store._root)).commit_module_revision(
        "path",
        result["preview_id"],
        session_id="session",
    )
    assert retry.model_dump() == committed.model_dump()
    assert receipt2["replayed"]
    assert receipt2["applied_revision"] == committed.version


def test_noop_preview_does_not_reset_or_publish_progress(system):
    store, service = system
    before = store.load("path")
    with pytest.raises(ValueError, match="changes nothing"):
        service.preview_module_revision(
            "path", before.modules, expected_revision=before.version, session_id="session"
        )
    assert store.load("path").model_dump() == before.model_dump()


def test_unrelated_question_and_mastered_evidence_survive_batch(system):
    store, service = system
    before = store.get_active_interaction("path").model_dump()
    result, proposed = preview(system, [{"module_id": "m1", "add": [{"name": "Extra objective"}]}])
    assert proposed.pending_question.knowledge_point_id == "p0"
    committed, _ = service.commit_module_revision(
        "path", result["preview_id"], session_id="session"
    )
    assert store.get_active_interaction("path").model_dump() == before
    assert committed.qualitative_mastery["p2"] is True


def test_retry_after_later_progress_returns_current_state_not_old_snapshot(system):
    store, service = system
    result, _ = preview(system)
    service.commit_module_revision("path", result["preview_id"], session_id="session")
    now = store.load("path")
    current = service.replace_modules_for_path("path", now.modules, name="Later name")
    replay, receipt = service.commit_module_revision(
        "path", result["preview_id"], session_id="session"
    )
    assert receipt["replayed"] is True
    assert receipt["applied_revision"] < replay.version
    assert replay.model_dump() == current.model_dump()


def test_stale_preview_and_preview_load_race_cannot_overwrite(system):
    store, service = system
    result, _ = preview(system)
    old = store.load("path")
    current = service.replace_modules_for_path("path", old.modules, name="Changed name")
    with pytest.raises(LearningConflictError):
        service.commit_module_revision("path", result["preview_id"], session_id="session")
    with pytest.raises(LearningConflictError):
        service.preview_module_revision(
            "path", old.modules, expected_revision=old.version, session_id="session"
        )
    assert store.load("path").model_dump() == current.model_dump()


def test_preview_is_scoped_to_path_session_and_workspace(system, tmp_path):
    store, service = system
    result, _ = preview(system)
    modules = store.load("path").modules
    modules[0].knowledge_points[0].topic_source_ids = []
    service.replace_modules_for_path("other", modules)
    for path_id, session in [("other", "session"), ("path", "different")]:
        with pytest.raises(ValueError, match="unavailable"):
            service.commit_module_revision(path_id, result["preview_id"], session_id=session)
    isolated = LearningService(LearningStore(root=tmp_path / "other-workspace"))
    isolated.replace_modules_for_path("path", modules)
    with pytest.raises(ValueError, match="unavailable"):
        isolated.commit_module_revision("path", result["preview_id"], session_id="session")


def test_expired_or_tampered_preview_cannot_commit(system):
    store, service = system
    result, _ = preview(system)
    before = store.load("path").model_dump()
    with sqlite3.connect(store.db_path) as db:
        db.execute("UPDATE mastery_events SET created_at=0 WHERE id=?", (result["preview_id"],))
    with pytest.raises(ValueError, match="expired"):
        service.commit_module_revision("path", result["preview_id"], session_id="session")
    result, _ = preview(system)
    with sqlite3.connect(store.db_path) as db:
        raw = db.execute(
            "SELECT payload_json FROM mastery_events WHERE id=?", (result["preview_id"],)
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["after_digest"] = "incorrect"
        db.execute(
            "UPDATE mastery_events SET payload_json=? WHERE id=?",
            (json.dumps(payload), result["preview_id"]),
        )
    with pytest.raises(ValueError, match="matches"):
        service.commit_module_revision("path", result["preview_id"], session_id="session")
    assert store.load("path").model_dump() == before
    assert store.get_active_interaction("path") is not None  # SQL side effects rolled back too.


def test_concurrent_drafts_have_one_winner_not_a_partial_merge(system):
    store, _ = system
    first, _ = preview(system)
    second, _ = preview(system, [{"module_id": "m1", "add": [{"name": "New objective"}]}])

    def commit(preview_id):
        try:
            return LearningService(LearningStore(root=store._root)).commit_module_revision(
                "path",
                preview_id,
                session_id="session",
            )[1]
        except LearningConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, [first["preview_id"], second["preview_id"]]))
    assert results.count("conflict") == 1
    assert sum(isinstance(x, dict) for x in results) == 1


@pytest.mark.parametrize(
    "edit",
    [
        [{"module_id": "m2", "rewrite": [{"knowledge_point_id": "p2", "name": "New content"}]}],
        [{"module_id": "m0", "remove": ["p0"], "add": [{"name": "New content"}]}],
        [{"module_id": "m0", "add": [{"name": "New content", "prerequisite_ids": ["unknown"]}]}],
        [
            {
                "module_id": "m0",
                "rewrite": [
                    {"knowledge_point_id": "p0", "name": "New content", "prerequisite_ids": ["p1"]}
                ],
            }
        ],
    ],
)
def test_invalid_batch_is_all_or_nothing(system, edit):
    store, _ = system
    before = store.load("path").model_dump()
    with pytest.raises(ValueError):
        preview(system, edit)
    assert store.load("path").model_dump() == before
    assert store.get_active_interaction("path") is not None


def test_exact_diff_preserves_types_null_removals_and_pointer_escaping():
    before = {"a/b~c": {"old": None, "keep": True}, "list": [1, 2]}
    after = {"a/b~c": {"new": None, "keep": 1}, "list": [1]}
    changes = exact_diff(before, after)
    assert any(c["path"] == "/a~1b~0c/keep" for c in changes)
    assert apply_diff(before, changes) == after
    assert exact_diff({"nested": [True]}, {"nested": [1]}) == [
        {
            "path": "/nested/0",
            "before_exists": True,
            "after_exists": True,
            "before": True,
            "after": 1,
        }
    ]


@pytest.mark.asyncio
async def test_reorder_only_preview_commit_preserves_every_objective_and_pending_question(
    system, monkeypatch
):
    from deeptutor.capabilities.mastery import tools

    store, service = system
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    before = store.load("path")
    interaction = store.get_active_interaction("path").model_dump(mode="json")
    args = {
        "_mastery_path_id": "path",
        "_session_id": "session",
        "_mastery_session_mode": "outline",
    }
    tool = MasteryReviseTool()
    preview_result = await tool.execute(**args, action="preview", module_order=["m2", "m0", "m1"])
    assert preview_result.success, preview_result.content
    draft = json.loads(preview_result.content)
    assert draft["status"] == "preview_only_not_saved"
    assert draft["before_module_order"] == ["m0", "m1", "m2"]
    assert draft["proposed_module_order"] == ["m2", "m0", "m1"]
    assert draft["module_order_changed"] is True
    assert store.load("path").model_dump() == before.model_dump()
    result = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    assert result.success, result.content
    receipt = json.loads(result.content)
    assert receipt["applied_module_order"] == ["m2", "m0", "m1"]
    committed = store.load("path")
    assert [m.id for m in committed.modules] == ["m2", "m0", "m1"]
    assert [m.order for m in committed.modules] == [0, 1, 2]
    assert committed.current_module_id == before.current_module_id
    assert committed.current_kp_index == before.current_kp_index
    assert committed.pending_question == before.pending_question
    assert store.get_active_interaction("path").model_dump(mode="json") == interaction
    for field in (
        "mastery_levels",
        "qualitative_mastery",
        "feynman_explanations",
        "knowledge_types",
    ):
        assert getattr(committed, field) == getattr(before, field)
    original = {m.id: m for m in before.modules}
    for module in committed.modules:
        assert module.model_dump(exclude={"order"}) == original[module.id].model_dump(
            exclude={"order"}
        )
    assert apply_diff(state(before), draft["changes"]) == state(committed)
    replay = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    assert json.loads(replay.content)["replayed"] is True
    assert store.load("path").model_dump() == committed.model_dump()


@pytest.mark.parametrize(
    "order",
    [
        [],
        ["m0", "m1"],
        ["m0", "m1", "m1"],
        ["m0", "m1", "foreign"],
        ["m0", "m1", 2],
        "m2,m0,m1",
    ],
)
@pytest.mark.asyncio
async def test_invalid_order_refuses_whole_preview_even_with_valid_content_edit(
    system, monkeypatch, order
):
    from deeptutor.capabilities.mastery import tools

    store, service = system
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    before = store.load("path").model_dump()
    result = await MasteryReviseTool().execute(
        _mastery_path_id="path",
        _session_id="session",
        _mastery_session_mode="outline",
        action="preview",
        modules=revisions(),
        module_order=order,
    )
    assert not result.success
    assert store.load("path").model_dump() == before
    with sqlite3.connect(store.db_path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM mastery_events WHERE event_type='path.modules_previewed'"
        ).fetchone()[0]
        assert count == 0


@pytest.mark.asyncio
async def test_order_requires_review_and_combined_edit_has_exact_diff(system, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    store, service = system
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    tool = MasteryReviseTool()
    args = {
        "_mastery_path_id": "path",
        "_session_id": "session",
        "_mastery_session_mode": "outline",
    }
    before = store.load("path")
    refused = await tool.execute(**args, module_order=["m2", "m0", "m1"], modules=revisions())
    assert not refused.success
    result = await tool.execute(
        **args, action="preview", module_order=["m2", "m0", "m1"], modules=revisions()
    )
    assert result.success, result.content
    draft = json.loads(result.content)
    assert store.load("path").model_dump() == before.model_dump()
    committed = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    assert committed.success, committed.content
    after = store.load("path")
    assert apply_diff(state(before), draft["changes"]) == state(after)
    assert after.modules[1].knowledge_points[0].name == "Revised objective 0"
    assert after.mastery_levels["p2"] == 1


@pytest.mark.asyncio
async def test_reorder_noop_stale_preview_and_historical_commit_receipt(system, monkeypatch):
    import jsonschema

    from deeptutor.capabilities.mastery import tools

    store, service = system
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    tool = MasteryReviseTool()
    args = {
        "_mastery_path_id": "path",
        "_session_id": "session",
        "_mastery_session_mode": "outline",
    }
    schema = tool.get_definition().to_openai_schema()["function"]["parameters"]
    request = {"action": "preview", "module_order": ["m2", "m0", "m1"]}
    jsonschema.validate(request, schema)
    before = store.load("path")
    noop = await tool.execute(**args, action="preview", module_order=["m0", "m1", "m2"])
    assert not noop.success and "changes nothing" in noop.content
    assert store.load("path").model_dump() == before.model_dump()
    draft = json.loads((await tool.execute(**args, **request)).content)
    service.replace_modules_for_path("path", before.modules)
    stale = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    assert not stale.success
    assert [m.id for m in store.load("path").modules] == ["m0", "m1", "m2"]
    draft = json.loads((await tool.execute(**args, **request)).content)
    committed = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    assert committed.success
    later_modules = _plan_module_revision(store.load("path"), {}, module_order=["m1", "m2", "m0"])[
        0
    ]
    service.replace_modules_for_path("path", later_modules)
    replay_result = await tool.execute(**args, action="commit", preview_id=draft["preview_id"])
    replay = json.loads(replay_result.content)
    assert replay["replayed"] is True
    assert replay["applied_module_order"] == ["m2", "m0", "m1"]
    assert replay["current_module_order"] == ["m1", "m2", "m0"]


@pytest.mark.asyncio
async def test_runtime_preview_requires_a_later_invocation_and_preserves_legacy_schema(
    system, monkeypatch
):
    import jsonschema

    from deeptutor.agents.loop.agent_loop import AgentLoop
    from deeptutor.capabilities.mastery import tools
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.stream_bus import StreamBus

    monkeypatch.setattr(tools, "_new_service", lambda: system[1])
    context = UnifiedContext(
        session_id="session",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "path",
            "mastery_session_mode": "outline",
        },
    )
    pipeline = MasteryLoopPipeline(language="en")

    async def chunks():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="Reviewed.", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    async def create(**kwargs):
        return chunks()

    engine = AgentLoop(
        pipeline=pipeline,
        context=context,
        stream=StreamBus(),
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        enabled_tools=[],
        tool_schemas=None,
    )

    async def invoke():
        await engine._call_llm(
            messages=[{"role": "user", "content": "Review the outline."}],
            label="review",
            call_kind="agent_loop_round",
            trace_role="answer",
            max_tokens=100,
        )

    capability = MasteryLoopCapability()
    tool = MasteryReviseTool()
    schema = tool.get_definition().to_openai_schema()["function"]["parameters"]
    edits = {"action": "preview", "modules": revisions()}
    jsonschema.validate(edits, schema)
    await invoke()
    args = capability.augment_kwargs(
        tool.name,
        {**edits, "_revision_request_id": "untrusted-model-value"},
        context,
    )
    invocation = args["_revision_request_id"]
    assert invocation and invocation != "untrusted-model-value"
    result = await tool.execute(**args)
    assert result.success, result.content
    assert "mastery_revision_preview" in result.metadata
    assert "mastery_revise" not in result.metadata
    commit = {"action": "commit", "preview_id": json.loads(result.content)["preview_id"]}
    jsonschema.validate(commit, schema)
    blocked = await tool.execute(**capability.augment_kwargs(tool.name, commit, context))
    assert not blocked.success and "later model round" in blocked.content
    await invoke()
    args = capability.augment_kwargs(tool.name, commit, context)
    assert args["_revision_request_id"] != invocation
    result = await tool.execute(**args)
    assert result.success, result.content
    # Existing callers omit action and still have their original schema.
    jsonschema.validate({"modules": revisions()}, schema)


@pytest.mark.asyncio
async def test_reviewed_tool_scope_and_commit_cannot_replace_reviewed_payload(system, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: system[1])
    tool = MasteryReviseTool()
    bound = {"_mastery_path_id": "path", "_session_id": "session"}
    result = await tool.execute(
        action="preview", modules=revisions(), **bound, _mastery_session_mode="study"
    )
    assert not result.success
    result = await tool.execute(
        action="preview", modules=revisions(), **bound, _mastery_session_mode="outline"
    )
    assert result.success, result.content
    preview_id = json.loads(result.content)["preview_id"]
    result = await tool.execute(
        action="commit", preview_id=preview_id, modules=revisions(), **bound
    )
    assert not result.success and "only preview_id" in result.content


def test_group_child_revision_is_previewed_without_retiring_live_questions(system):
    store, service = system

    def group_questions(tx):
        first = tx.progress.pending_question.model_copy(deep=True)
        first.question_id = "child-0"
        second = first.model_copy(
            update={"question_id": "child-1", "knowledge_point_id": "p1", "module_id": "m1"}
        )
        group = first.model_copy(
            update={
                "question_id": "question",
                "question_type": "group",
                "expected_answer": "",
                "questions": [first, second],
            }
        )
        tx.progress.pending_question = group
        active = tx.active_interaction()
        active.question = group
        tx.put_interaction(active)

    store.mutate("path", group_questions)
    before = store.get_active_interaction("path").model_dump()
    result, proposed = preview(
        system,
        [
            {
                "module_id": "m1",
                "rewrite": [{"knowledge_point_id": "p1", "name": "Changed child objective"}],
            }
        ],
    )
    assert proposed.pending_question is None
    assert result["effects"]["active_interaction_removed"] is True
    assert store.get_active_interaction("path").model_dump() == before
    service.commit_module_revision("path", result["preview_id"], session_id="session")
    assert store.get_active_interaction("path") is None
    assert store.load("path").pending_question is None
