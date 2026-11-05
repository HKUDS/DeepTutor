"""Review interval strategy templates: presets, CRUD, validation, binding (#1908)."""

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from deeptutor.api.routers.mastery_path import router
from deeptutor.learning.identity import resolve_mastery_path_binding
from deeptutor.learning.models import (
    KnowledgeType,
    LearningEvidence,
    LearningProgress,
    ReviewStrategyTemplate,
)
from deeptutor.learning.review_strategy import (
    BUILTIN_TEMPLATE_IDS,
    builtin_templates,
    scheduler_for_path,
    scheduler_for_progress,
)
from deeptutor.learning.scheduler import INTERVAL_SEQUENCES, SpacedRepetitionScheduler
from deeptutor.learning.storage import LearningStore


def _valid_intervals() -> dict[str, list[int]]:
    return {
        "memory": [0, 2, 5, 10, 20, 45],
        "concept": [2, 6, 14, 28],
        "procedure": [2, 6, 14],
        "design": [10, 21],
    }


@pytest.fixture
def app(tmp_path, monkeypatch):
    def _make_store_with_tmp(root=None):
        return LearningStore(root=tmp_path)

    monkeypatch.setattr(
        "deeptutor.api.routers.mastery_path.LearningStore",
        _make_store_with_tmp,
    )
    app = FastAPI()
    app.state.learning_root = tmp_path
    app.include_router(router, prefix="/api/mastery-paths")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def path_id(app):
    store = LearningStore(root=app.state.learning_root)
    progress = LearningProgress(book_id="strategy-path", name="Strategy path")
    progress.knowledge_types["kp1"] = KnowledgeType.MEMORY
    store.save(progress)
    return "strategy-path"


# -- Presets -----------------------------------------------------------------


def test_builtin_presets_cover_the_four_named_modes():
    assert set(BUILTIN_TEMPLATE_IDS) == {
        "preset-daily-long-term",
        "preset-exam-cramming",
        "preset-language",
        "preset-science",
    }
    for template in builtin_templates().values():
        assert set(template.intervals) == set(KnowledgeType)
        assert template.builtin is True


def test_daily_long_term_preset_matches_baseline_sequences():
    preset = builtin_templates()["preset-daily-long-term"]
    assert {k.value: v for k, v in preset.intervals.items()} == {
        k.value: v for k, v in INTERVAL_SEQUENCES.items()
    }


# -- Model validation ----------------------------------------------------------


def _template(**overrides):
    payload = {
        "template_id": "custom-x",
        "name": "My plan",
        "intervals": _valid_intervals(),
    }
    payload.update(overrides)
    return ReviewStrategyTemplate(**payload)


def test_template_accepts_independent_per_round_intervals():
    template = _template(
        intervals={
            "memory": [0, 1, 1, 2, 4, 8],
            "concept": [3, 30],
            "procedure": [2, 2, 2],
            "design": [60],
        }
    )
    assert template.intervals[KnowledgeType.MEMORY] == [0, 1, 1, 2, 4, 8]
    assert template.intervals[KnowledgeType.DESIGN] == [60]


@pytest.mark.parametrize(
    "intervals",
    [
        {k: v for k, v in _valid_intervals().items() if k != "design"},
        {"memory": [], "concept": [3], "procedure": [3], "design": [7]},
        {"memory": [0, -1], "concept": [3], "procedure": [3], "design": [7]},
        {"memory": [5, 1], "concept": [3], "procedure": [3], "design": [7]},
        {"memory": [366], "concept": [3], "procedure": [3], "design": [7]},
        {"memory": [0, 0], "concept": [3], "procedure": [3], "design": [7]},
        {"memory": list(range(17)), "concept": [3], "procedure": [3], "design": [7]},
        {"memory": [0.5], "concept": [3], "procedure": [3], "design": [7]},
    ],
)
def test_template_rejects_invalid_interval_shapes(intervals):
    with pytest.raises(ValidationError):
        _template(intervals=intervals)


def test_template_rejects_invalid_metadata():
    with pytest.raises(ValidationError):
        _template(name="   ")
    with pytest.raises(ValidationError):
        _template(template_id="Not A Slug!")
    with pytest.raises(ValidationError):
        _template(desired_retention=0.5)


# -- Storage CRUD --------------------------------------------------------------


def test_store_roundtrips_custom_templates(tmp_path):
    store = LearningStore(root=tmp_path)
    template = ReviewStrategyTemplate(
        template_id="custom-mine", name="Mine", intervals=_valid_intervals()
    )
    store.save_review_strategy(template)
    loaded = store.get_review_strategy("custom-mine")
    assert loaded is not None
    assert loaded.name == "Mine"
    assert loaded.intervals[KnowledgeType.MEMORY] == [0, 2, 5, 10, 20, 45]
    assert loaded.builtin is False
    assert store.list_review_strategies()[0].template_id == "custom-mine"

    edited = loaded.model_copy(update={"name": "Mine v2"})
    store.save_review_strategy(edited)
    assert store.get_review_strategy("custom-mine").name == "Mine v2"

    assert store.delete_review_strategy("custom-mine") is True
    assert store.get_review_strategy("custom-mine") is None
    assert store.delete_review_strategy("custom-mine") is False


def test_store_refuses_to_shadow_builtin_templates(tmp_path):
    store = LearningStore(root=tmp_path)
    template = ReviewStrategyTemplate(
        template_id="preset-exam-cramming", name="Fake preset", intervals=_valid_intervals()
    )
    with pytest.raises(ValueError):
        store.save_review_strategy(template)


# -- Scheduler integration ------------------------------------------------------


def test_scheduler_uses_default_sequences_without_configuration():
    scheduler = SpacedRepetitionScheduler()
    assert scheduler.interval_sequences == {
        k: [float(i) for i in v] for k, v in INTERVAL_SEQUENCES.items()
    }


def test_scheduler_honours_custom_sequences():
    custom = {
        KnowledgeType.MEMORY: [0, 2, 5],
        KnowledgeType.CONCEPT: [2, 6],
        KnowledgeType.PROCEDURE: [2, 6],
        KnowledgeType.DESIGN: [10],
    }
    scheduler = SpacedRepetitionScheduler(interval_sequences=custom)
    assert scheduler.interval_sequences[KnowledgeType.MEMORY] == [0.0, 2.0, 5.0]


def test_custom_success_uses_the_configured_next_round():
    scheduler = SpacedRepetitionScheduler(
        interval_sequences={
            KnowledgeType.MEMORY: [5, 10],
            KnowledgeType.CONCEPT: [5, 10],
            KnowledgeType.PROCEDURE: [5, 10],
            KnowledgeType.DESIGN: [5, 10],
        }
    )
    start = 1_700_000_000.0
    state = scheduler.get_initial_state(KnowledgeType.MEMORY, now=start)
    state = scheduler.schedule_review(
        state,
        KnowledgeType.MEMORY,
        LearningEvidence(
            knowledge_point_id="kp1",
            timestamp=start + 5 * 86400,
            assessment_type="quiz",
            result="correct",
            quality=1.0,
        ),
        now=start + 5 * 86400,
    )
    assert state.next_review_at == pytest.approx(start + 15 * 86400)


def test_scheduler_for_progress_follows_binding_snapshot():
    progress = LearningProgress(book_id="p")
    assert scheduler_for_progress(progress).interval_sequences[KnowledgeType.MEMORY] == [
        float(i) for i in INTERVAL_SEQUENCES[KnowledgeType.MEMORY]
    ]
    template = builtin_templates()["preset-exam-cramming"]
    progress.review_strategy = template.as_binding(bound_at=time.time())
    scheduler = scheduler_for_progress(progress)
    assert scheduler.interval_sequences[KnowledgeType.MEMORY] == [
        float(i) for i in template.intervals[KnowledgeType.MEMORY]
    ]


def test_scheduler_for_path_loads_the_bound_strategy(tmp_path, path_id):
    store = LearningStore(root=tmp_path)
    template = ReviewStrategyTemplate(
        template_id="custom-cram", name="Cram", intervals=_valid_intervals()
    )
    store.save_review_strategy(template)
    progress = store.load(path_id)
    progress.review_strategy = template.as_binding(bound_at=time.time())
    store.save(progress)

    scheduler = scheduler_for_path(LearningStore(root=tmp_path), path_id)
    assert scheduler.interval_sequences[KnowledgeType.CONCEPT] == [2.0, 6.0, 14.0, 28.0]


def test_legacy_progress_without_binding_keeps_default_behaviour(tmp_path):
    legacy = LearningProgress(book_id="legacy").model_dump(mode="json")
    assert "review_strategy" not in legacy or legacy["review_strategy"] is None
    progress = LearningProgress.model_validate(legacy)
    assert progress.review_strategy is None
    assert scheduler_for_progress(progress).interval_sequences == {
        k: [float(i) for i in v] for k, v in INTERVAL_SEQUENCES.items()
    }


# -- Strategy CRUD API ----------------------------------------------------------


def test_list_strategies_returns_presets_then_custom(client):
    body = client.get("/api/mastery-paths/review-strategies").json()
    strategies = body["strategies"]
    assert [item["template_id"] for item in strategies][:4] == sorted(BUILTIN_TEMPLATE_IDS)
    assert all(item["builtin"] for item in strategies[:4])
    assert not any(item["builtin"] for item in strategies[4:])


def test_create_update_and_delete_custom_strategy(client):
    created = client.post(
        "/api/mastery-paths/review-strategies",
        json={"name": "GRE sprint", "intervals": _valid_intervals()},
    )
    assert created.status_code == 201
    template = created.json()
    assert template["template_id"].startswith("custom-")
    assert template["builtin"] is False

    updated = client.put(
        f"/api/mastery-paths/review-strategies/{template['template_id']}",
        json={"name": "GRE sprint v2", "intervals": _valid_intervals()},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "GRE sprint v2"

    assert (
        client.get(f"/api/mastery-paths/review-strategies/{template['template_id']}").json()["name"]
        == "GRE sprint v2"
    )
    assert (
        client.delete(f"/api/mastery-paths/review-strategies/{template['template_id']}").status_code
        == 200
    )
    assert (
        client.get(f"/api/mastery-paths/review-strategies/{template['template_id']}").status_code
        == 404
    )


def test_create_rejects_invalid_intervals(client):
    bad = _valid_intervals()
    bad["memory"] = [0, 900]
    response = client.post(
        "/api/mastery-paths/review-strategies",
        json={"name": "Bad", "intervals": bad},
    )
    assert response.status_code == 422


def test_builtin_templates_cannot_be_modified_or_deleted(client):
    assert (
        client.put(
            "/api/mastery-paths/review-strategies/preset-exam-cramming",
            json={"name": "Nope", "intervals": _valid_intervals()},
        ).status_code
        == 403
    )
    assert client.delete("/api/mastery-paths/review-strategies/preset-science").status_code == 403
    assert (
        client.put(
            "/api/mastery-paths/review-strategies/missing-template",
            json={"name": "Nope", "intervals": _valid_intervals()},
        ).status_code
        == 404
    )
    assert client.delete("/api/mastery-paths/review-strategies/missing-template").status_code == 404
    # Ids that cannot name a stored template resolve as unknown, not as errors.
    assert client.get("/api/mastery-paths/review-strategies/../etc").status_code == 404
    assert client.delete("/api/mastery-paths/review-strategies/..%3Aetc").status_code == 404


def test_duplicate_preset_creates_an_independent_custom_copy(client):
    response = client.post(
        "/api/mastery-paths/review-strategies/preset-language/duplicate",
        json={"name": "My language plan"},
    )
    assert response.status_code == 201
    copy = response.json()
    assert copy["template_id"] != "preset-language"
    assert copy["builtin"] is False
    assert copy["name"] == "My language plan"
    assert (
        copy["intervals"]["memory"]
        == builtin_templates()["preset-language"].intervals[KnowledgeType.MEMORY]
    )
    assert (
        client.post(
            "/api/mastery-paths/review-strategies/missing-template/duplicate", json={"name": "X"}
        ).status_code
        == 404
    )


# -- Path binding API --------------------------------------------------------------


def test_bind_and_switch_path_strategy(client, app, path_id):
    bound = client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": "preset-exam-cramming"},
    )
    assert bound.status_code == 200
    settings = bound.json()["review_settings"]
    assert settings["strategy"]["template_id"] == "preset-exam-cramming"
    assert settings["strategy"]["builtin"] is True

    persisted = LearningStore(root=app.state.learning_root).load(path_id)
    assert persisted.review_strategy.template_id == "preset-exam-cramming"
    scheduler = scheduler_for_progress(persisted)
    assert scheduler.interval_sequences[KnowledgeType.MEMORY] == [
        float(i)
        for i in builtin_templates()["preset-exam-cramming"].intervals[KnowledgeType.MEMORY]
    ]

    custom = client.post(
        "/api/mastery-paths/review-strategies",
        json={"name": "Switch target", "intervals": _valid_intervals()},
    ).json()
    switched = client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": custom["template_id"]},
    )
    assert switched.status_code == 200
    assert switched.json()["review_settings"]["strategy"]["template_id"] == custom["template_id"]
    assert (
        client.get(f"/api/mastery-paths/topics/{path_id}/review-settings").json()["strategy"][
            "template_id"
        ]
        == custom["template_id"]
    )
    events = [
        event
        for event in LearningStore(root=app.state.learning_root).list_events(path_id)
        if event.event_type == "review.strategy_changed"
    ]
    assert [event.payload.get("template_id") for event in events] == [
        "preset-exam-cramming",
        custom["template_id"],
    ]


def test_switching_strategy_replays_evidence_and_reschedules_pending_review(client, app, path_id):
    store = LearningStore(root=app.state.learning_root)
    progress = store.load(path_id)
    start = 1_700_000_000.0
    first_due = start + 5 * 86400
    evidence = LearningEvidence(
        evidence_id="evidence-1",
        knowledge_point_id="kp1",
        timestamp=first_due,
        assessment_type="quiz",
        result="correct",
        quality=1.0,
    )
    progress.repetition_states["kp1"] = SpacedRepetitionScheduler().get_initial_state(
        KnowledgeType.MEMORY, now=start
    )
    progress.learning_evidence.append(evidence)
    store.save(progress)

    custom = client.post(
        "/api/mastery-paths/review-strategies",
        json={
            "name": "Longer switch",
            "intervals": {
                "memory": [5, 20],
                "concept": [5, 20],
                "procedure": [5, 20],
                "design": [5, 20],
            },
        },
    ).json()
    response = client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": custom["template_id"]},
    )

    assert response.status_code == 200
    persisted = LearningStore(root=app.state.learning_root).load(path_id)
    state = persisted.repetition_states["kp1"]
    assert state.next_review_at == pytest.approx(first_due + 20 * 86400)
    replayed = scheduler_for_progress(persisted).replay(
        KnowledgeType.MEMORY,
        [evidence],
        now=first_due,
        desired_retention=persisted.desired_retention,
    )
    assert state.model_dump() == replayed.model_dump()


def test_binding_preset_applies_its_retention_target(client, app, path_id):
    response = client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": "preset-exam-cramming"},
    )
    assert response.status_code == 200
    persisted = LearningStore(root=app.state.learning_root).load(path_id)
    assert (
        persisted.desired_retention == builtin_templates()["preset-exam-cramming"].desired_retention
    )


def test_unbind_restores_default_template_and_keeps_retention(client, app, path_id):
    client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": "preset-exam-cramming"},
    )
    unbound = client.put(
        f"/api/mastery-paths/topics/{path_id}/review-strategy",
        json={"template_id": ""},
    )
    assert unbound.status_code == 200
    assert unbound.json()["review_settings"]["strategy"] is None
    persisted = LearningStore(root=app.state.learning_root).load(path_id)
    assert persisted.review_strategy is None
    # Retention is a separate setting: unbinding keeps the learner's target.
    assert (
        persisted.desired_retention == builtin_templates()["preset-exam-cramming"].desired_retention
    )


def test_mastery_session_resolves_the_bound_path_and_inherits_its_strategy(path_id):
    binding = resolve_mastery_path_binding(
        configured_path_id=path_id,
        session_id="another-session",
    )
    assert binding.path_id == path_id


def test_binding_unknown_template_or_path_fails(client, path_id):
    assert (
        client.put(
            f"/api/mastery-paths/topics/{path_id}/review-strategy",
            json={"template_id": "missing-template"},
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/mastery-paths/topics/missing-path/review-strategy",
            json={"template_id": "preset-language"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("value", [True, False, "1", 1.0])
def test_intervals_require_json_integers(value):
    intervals = _valid_intervals()
    intervals["concept"] = [value]
    with pytest.raises(ValidationError):
        _template(intervals=intervals)


def test_switch_preserves_legacy_reviews_without_evidence():
    from deeptutor.learning.models import RepetitionState

    progress = LearningProgress(book_id="legacy", name="Legacy")
    state = RepetitionState(
        review_count=7,
        last_review_at=1000,
        last_scheduled_at=1000,
        next_review_at=2000,
        stability=12,
        difficulty=0.4,
    )
    progress.repetition_states["kp"] = state
    progress.knowledge_types["kp"] = KnowledgeType.CONCEPT
    progress.review_strategy = _template().as_binding()
    scheduler_for_progress(progress).rebuild_from_evidence(progress, now=1500)
    assert state.review_count == 7
    assert state.last_review_at == 1000
    assert state.stability == 12
    assert state.next_review_at == pytest.approx(1000 + 28 * 86400)
    assert progress.learning_evidence == []


def test_rebinding_identical_strategy_is_idempotent(client, app, path_id):
    url = f"/api/mastery-paths/topics/{path_id}/review-strategy"
    payload = {"template_id": "preset-exam-cramming"}
    assert client.put(url, json=payload).status_code == 200
    store = LearningStore(root=app.state.learning_root)
    before = store.load(path_id).model_dump()
    assert client.put(url, json=payload).status_code == 200
    assert store.load(path_id).model_dump() == before


def test_strategy_api_rejects_boolean_intervals(client):
    intervals = _valid_intervals()
    intervals["concept"] = [True]
    response = client.post(
        "/api/mastery-paths/review-strategies", json={"name": "Invalid", "intervals": intervals}
    )
    assert response.status_code == 422
