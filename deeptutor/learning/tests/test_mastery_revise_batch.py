"""Focused regression tests for coordinated (multi-module) ``mastery_revise``.

Upstream #1929: a coordinated outline adjustment used to need one
``mastery_revise`` call per module, each carrying a fresh full-outline
snapshot back into the model loop. The batch form revises several modules in
ONE reviewed request — one transaction, one revision, one result payload —
while the single-module form keeps its exact contract. Everything here runs
offline against a temp store; no LLM is involved."""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import MasteryAssessTool, MasteryBuildTool, MasteryReviseTool


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    """Point the LearningStore at a temp workspace and yield a stable path id."""
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return "test_path"


def _store_init_factory(root):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__ signature
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


async def _build_three_modules(path_id):
    """A path whose three modules have no cross-module prerequisites yet."""
    build = MasteryBuildTool()
    result = await build.execute(
        _mastery_path_id=path_id,
        path_name="命题逻辑入门",
        modules=[
            {
                "name": "布尔基础",
                "objective": "读懂一个真值表并判断两个命题是否等价",
                "knowledge_points": [
                    {"name": "真值表", "type": "memory"},
                    {"name": "XOR 的意义", "type": "concept"},
                ],
            },
            {
                "name": "联结词",
                "objective": "用与或非改写日常语句",
                "knowledge_points": [{"name": "合取与析取", "type": "concept"}],
            },
            {
                "name": "论证形式",
                "objective": "识别常见的有效论证形式",
                "knowledge_points": [
                    {"name": "肯定前件", "type": "memory"},
                    {"name": "否定后件", "type": "memory"},
                ],
            },
        ],
    )
    assert result.success, result.content
    return json.loads(result.content)


def _stored_state(path_id):
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    return progress, store


def _module(progress, module_id):
    return next(m for m in progress.modules if m.id == module_id)


@pytest.mark.asyncio
async def test_batch_revises_modules_in_one_revision_and_one_event(path_id):
    """One coordinated request: one commit, one revision, one result payload."""
    built = await _build_three_modules(path_id)
    base_revision = built["path_revision"]

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        modules=[
            {
                "module_id": "test_path_m0",
                "rewrite": [
                    {
                        "knowledge_point_id": "test_path_m0_kp1",
                        "name": "用 XOR 判断两个命题何时等价",
                        "type": "procedure",
                    }
                ],
            },
            {
                "module_id": "test_path_m2",
                "remove": ["test_path_m2_kp1"],
                "add": [{"name": "假言三段论", "type": "memory"}],
            },
        ],
    )

    assert revised.success, revised.content
    payload = json.loads(revised.content)
    assert payload["status"] == "revised"
    # One revision committed for the whole coordinated request — not one per
    # module.
    assert payload["path_revision"] == base_revision + 1

    # One report per touched module, each against its own stated promise.
    reports = {entry["module_id"]: entry for entry in payload["modules"]}
    assert set(reports) == {"test_path_m0", "test_path_m2"}
    assert reports["test_path_m0"]["module_objective"] == "读懂一个真值表并判断两个命题是否等价"
    assert reports["test_path_m0"]["progress_reset"] == ["XOR 的意义"]
    assert reports["test_path_m2"]["progress_reset"] == []
    assert [kp["name"] for kp in reports["test_path_m0"]["knowledge_points"]] == [
        "真值表",
        "用 XOR 判断两个命题何时等价",
    ]
    assert [kp["name"] for kp in reports["test_path_m2"]["knowledge_points"]] == [
        "肯定前件",
        "假言三段论",
    ]

    # The payload carries ONE full-outline map for the whole batch.
    assert isinstance(payload["map"]["modules"], list)
    assert len(payload["map"]["modules"]) == 3

    # Exactly one journal event for the whole coordinated request.
    progress, store = _stored_state(path_id)
    assert progress.version == base_revision + 1
    events = store.list_events(path_id, after_revision=base_revision)
    assert [event.event_type for event in events] == ["path.module_revised"]
    assert events[0].payload["module_count"] == 3

    # The stored outline reflects both modules' changes and nothing else.
    assert [kp.name for kp in _module(progress, "test_path_m0").knowledge_points] == [
        "真值表",
        "用 XOR 判断两个命题何时等价",
    ]
    assert [kp.name for kp in _module(progress, "test_path_m1").knowledge_points] == ["合取与析取"]
    assert [kp.name for kp in _module(progress, "test_path_m2").knowledge_points] == [
        "肯定前件",
        "假言三段论",
    ]


@pytest.mark.asyncio
async def test_batch_unknown_module_refuses_the_whole_request(path_id):
    """A bad module id rejects the coordinated edit, not just its entry."""
    built = await _build_three_modules(path_id)
    base_revision = built["path_revision"]

    refused = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        modules=[
            {
                "module_id": "test_path_m0",
                "rewrite": [{"knowledge_point_id": "test_path_m0_kp0", "name": "真值表基础"}],
            },
            {
                "module_id": "test_path_m9",
                "add": [{"name": "不存在的模块"}],
            },
        ],
    )

    assert refused.success is False
    assert "test_path_m9" in refused.content
    progress, store = _stored_state(path_id)
    # The valid entry was not applied either: the request is all-or-nothing.
    assert [kp.name for kp in _module(progress, "test_path_m0").knowledge_points] == [
        "真值表",
        "XOR 的意义",
    ]
    assert progress.version == base_revision
    assert store.list_events(path_id, after_revision=base_revision) == []


@pytest.mark.asyncio
async def test_batch_cycle_rolls_back_to_untouched_state(path_id):
    """A cross-module prerequisite cycle rejects the whole plan at commit time."""
    build = MasteryBuildTool()
    built = json.loads(
        (
            await build.execute(
                _mastery_path_id=path_id,
                modules=[
                    {
                        "name": "Foundations",
                        "knowledge_points": [{"name": "Sets"}],
                    },
                    {
                        "name": "Relations",
                        "knowledge_points": [
                            {"name": "Functions", "prerequisite_refs": ["test_path_m0_kp0"]}
                        ],
                    },
                ],
            )
        ).content
    )
    base_revision = built["path_revision"]

    refused = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        modules=[
            {
                "module_id": "test_path_m0",
                # Sets now depends on Functions…
                "rewrite": [
                    {
                        "knowledge_point_id": "test_path_m0_kp0",
                        "name": "Sets and subsets",
                        "prerequisite_ids": ["test_path_m1_kp0"],
                    }
                ],
            },
            {
                "module_id": "test_path_m1",
                # …and Functions (rewritten) still depends on the rewritten
                # Sets, referenced by its pre-revision id.
                "rewrite": [
                    {
                        "knowledge_point_id": "test_path_m1_kp0",
                        "name": "Functions and maps",
                        "prerequisite_ids": ["test_path_m0_kp0"],
                    }
                ],
            },
        ],
    )

    assert refused.success is False
    assert "cycle" in refused.content.lower()
    progress, store = _stored_state(path_id)
    # Rollback is whole-plan: neither module moved, ids included.
    assert [kp.id for kp in _module(progress, "test_path_m0").knowledge_points] == [
        "test_path_m0_kp0"
    ]
    assert [kp.id for kp in _module(progress, "test_path_m1").knowledge_points] == [
        "test_path_m1_kp0"
    ]
    assert _module(progress, "test_path_m1").knowledge_points[0].prerequisite_ids == [
        "test_path_m0_kp0"
    ]
    assert progress.version == base_revision
    assert store.list_events(path_id, after_revision=base_revision) == []


@pytest.mark.asyncio
async def test_batch_shares_id_space_and_remaps_cross_module_prereqs(path_id):
    """Rewrites across modules mint non-colliding ids and re-point edges."""
    build = MasteryBuildTool()
    built = json.loads(
        (
            await build.execute(
                _mastery_path_id=path_id,
                modules=[
                    {"name": "Foundations", "knowledge_points": [{"name": "Sets"}]},
                    {
                        "name": "Relations",
                        "knowledge_points": [
                            {"name": "Functions", "prerequisite_refs": ["test_path_m0_kp0"]}
                        ],
                    },
                ],
            )
        ).content
    )
    base_revision = built["path_revision"]

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        modules=[
            {
                "module_id": "test_path_m0",
                "rewrite": [{"knowledge_point_id": "test_path_m0_kp0", "name": "Sets and subsets"}],
            },
            {
                "module_id": "test_path_m1",
                "rewrite": [
                    {"knowledge_point_id": "test_path_m1_kp0", "name": "Functions and maps"}
                ],
            },
        ],
    )
    assert revised.success, revised.content
    payload = json.loads(revised.content)
    assert payload["path_revision"] == base_revision + 1

    foundations = payload["map"]["modules"][0]["knowledge_points"]
    relations = payload["map"]["modules"][1]["knowledge_points"]
    new_sets_id = foundations[0]["id"]
    assert new_sets_id != "test_path_m0_kp0"
    assert relations[0]["id"] != "test_path_m1_kp0"
    # A shared id space: the two fresh ids differ even though both modules
    # minted their first rewrite at the same time.
    assert new_sets_id != relations[0]["id"]
    # The inherited cross-module edge follows the rewritten target, without
    # the model having to know the new id in advance.
    assert relations[0]["prerequisite_ids"] == [new_sets_id]

    progress, _ = _stored_state(path_id)
    stored_relations = _module(progress, "test_path_m1").knowledge_points[0]
    assert stored_relations.prerequisite_ids == [new_sets_id]


@pytest.mark.asyncio
async def test_batch_refuses_when_any_module_touches_mastered_work(path_id, monkeypatch):
    """Proven work in ANY module of the batch refuses the whole request."""
    from deeptutor.learning import semantic_assessment

    learner_answer = (
        "Conjunction requires both propositions to be true; disjunction requires at least one."
    )

    async def judge(_config, items):
        assert all(item["answer"] == learner_answer for item in items)
        return {
            item["question_id"]: semantic_assessment.Verdict(
                result="correct", confidence=0.99, feedback="The explanation meets the objective."
            )
            for item in items
        }

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    built = await _build_three_modules(path_id)
    assessed = await MasteryAssessTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id="test_path_m1_kp0",
        _learner_message=learner_answer,
        feedback="学习者用自己的话说清了合取与析取的区别。",
    )
    assert assessed.success, assessed.content
    assert json.loads(assessed.content)["mastered"] is True
    _, store = _stored_state(path_id)
    post_assess_revision = store.load(path_id).version
    assert post_assess_revision > built["path_revision"]

    refused = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        modules=[
            {
                "module_id": "test_path_m0",
                "add": [{"name": "德摩根定律", "type": "memory"}],
            },
            {
                "module_id": "test_path_m1",
                "rewrite": [{"knowledge_point_id": "test_path_m1_kp0", "name": "与或非的日常说法"}],
            },
        ],
    )

    assert refused.success is False
    assert "already mastered" in refused.content
    progress, store = _stored_state(path_id)
    # The other module's addition was refused with it: one request, one verdict.
    assert [kp.name for kp in _module(progress, "test_path_m0").knowledge_points] == [
        "真值表",
        "XOR 的意义",
    ]
    assert [kp.name for kp in _module(progress, "test_path_m1").knowledge_points] == ["合取与析取"]
    assert progress.version == post_assess_revision
    assert all(
        event.event_type != "path.module_revised"
        for event in store.list_events(path_id, after_revision=post_assess_revision)
    )


@pytest.mark.asyncio
async def test_single_module_form_keeps_its_contract(path_id):
    """The original one-module call still returns its original payload shape."""
    built = await _build_three_modules(path_id)
    base_revision = built["path_revision"]

    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        module_id="test_path_m1",
        rewrite=[{"knowledge_point_id": "test_path_m1_kp0", "name": "合取、析取与否定"}],
    )

    assert revised.success, revised.content
    payload = json.loads(revised.content)
    assert set(payload) == {
        "status",
        "path_revision",
        "module_id",
        "module_name",
        "module_objective",
        "knowledge_points",
        "progress_reset",
        "map",
    }
    assert payload["module_id"] == "test_path_m1"
    assert payload["progress_reset"] == ["合取与析取"]
    assert [kp["name"] for kp in payload["knowledge_points"]] == ["合取、析取与否定"]

    progress, store = _stored_state(path_id)
    assert progress.version == base_revision + 1
    assert [e.event_type for e in store.list_events(path_id, after_revision=base_revision)] == [
        "path.module_revised"
    ]


@pytest.mark.asyncio
async def test_batch_rejects_malformed_requests(path_id):
    """Shape errors are named, and none of them touches stored state."""
    built = await _build_three_modules(path_id)
    base_revision = built["path_revision"]

    cases = [
        # Mixing the two forms has no single meaning.
        (
            {
                "module_id": "test_path_m0",
                "modules": [{"module_id": "test_path_m1", "add": [{"name": "冗余"}]}],
            },
            "not both",
        ),
        # Same module twice would race itself for one outline slot.
        (
            {
                "modules": [
                    {"module_id": "test_path_m0", "add": [{"name": "甲"}]},
                    {"module_id": "test_path_m0", "remove": ["test_path_m0_kp0"]},
                ]
            },
            "appears twice",
        ),
        # An entry that changes nothing is a request to do nothing.
        (
            {"modules": [{"module_id": "test_path_m0"}]},
            "at least one of rewrite, add or remove",
        ),
        # Without a module_id there is nothing to revise.
        ({"modules": [{"add": [{"name": "无名模块"}]}]}, "module_id"),
        # And with neither form named at all.
        ({"rewrite": []}, "mastery_revise needs"),
    ]

    tool = MasteryReviseTool()
    for kwargs, expected in cases:
        refused = await tool.execute(_mastery_path_id=path_id, **kwargs)
        assert refused.success is False, (kwargs, refused.content)
        assert expected in refused.content, (kwargs, refused.content)

    progress, store = _stored_state(path_id)
    assert progress.version == base_revision
    assert store.list_events(path_id, after_revision=base_revision) == []
