from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

import pytest

from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgeType,
    LearningProgress,
    MasteryInteraction,
    PendingQuestion,
    RepetitionState,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.storage import (
    LearningConflictError,
    LearningPlanConflictError,
    LearningStore,
    LearningStoreError,
    PathLeaseConflictError,
    _atomic_write_text,
)


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


# ── Learning plans ─────────────────────────────────────────────────────


class TestLearningPlans:
    def test_owner_scopes_reads_and_all_state_mutations(self, store):
        plan = store.create_learning_plan(
            "plan-1",
            {"name": "Linear Algebra", "goal": "Learn vectors", "sources": []},
            owner_id="owner-a",
        )
        assert plan["state"] == "discussing"
        assert plan["brief"] == plan["input"]
        assert store.get_learning_plan("plan-1", owner_id="owner-b") is None

        with pytest.raises(KeyError):
            store.append_planning_session_message("plan-1", "user", "hello", owner_id="owner-b")
        with pytest.raises(KeyError):
            store.settle_learning_plan("plan-1", {}, owner_id="owner-b")
        with pytest.raises(KeyError):
            store.save_learning_plan_route_draft("plan-1", {}, owner_id="owner-b")

        store.append_planning_session_message("plan-1", "user", "hello", owner_id="owner-a")
        settled = store.settle_learning_plan(
            "plan-1",
            {"name": "Linear Algebra", "goal": "Learn vectors", "sources": []},
            owner_id="owner-a",
        )
        assert settled["state"] == "settled"
        drafted = store.save_learning_plan_route_draft(
            "plan-1", {"modules": []}, owner_id="owner-a"
        )
        assert drafted["state"] == "draft_ready"

    def test_brief_revision_and_reusable_planning_session(self, store):
        store.create_learning_plan("plan-1", {"name": "A"}, owner_id="owner-a")
        revised = store.revise_learning_plan_brief(
            "plan-1", {"name": "A", "goal": "Discussed goal"}, owner_id="owner-a"
        )
        assert revised["state"] == "discussing"
        assert revised["brief"]["goal"] == "Discussed goal"
        updated = store.update_learning_plan_brief(
            "plan-1", {"name": "B", "goal": "Practice"}, owner_id="owner-a"
        )
        assert updated["brief"] == {"name": "B", "goal": "Practice"}
        assert updated["brief_revision"] == 2
        session = store.create_planning_session("planning-1", owner_id="owner-a", plan_id="plan-1")
        assert session["planning_session_id"] == "planning-1"
        assert store.get_planning_session("planning-1", owner_id="owner-b") is None

    @pytest.mark.parametrize(
        ("method_name", "initial_state", "payload"),
        [
            ("settle_learning_plan", "discussing", {"name": "Settled"}),
            ("update_learning_plan_brief", "discussing", {"name": "Updated"}),
            ("update_learning_plan_route_draft", "draft_ready", {"modules": [{"name": "Edited"}]}),
        ],
    )
    def test_mutations_reject_claim_that_arrives_between_guard_and_update(
        self, store, monkeypatch, method_name, initial_state, payload
    ):
        """A conditional update must see an operation claim made after the guard read."""
        plan_id = f"plan-{method_name}"
        owner_id = "owner-a"
        store.create_learning_plan(plan_id, {"name": "Original"}, owner_id=owner_id)
        with store._connect() as conn:
            conn.execute(
                "UPDATE mastery_learning_plans SET state = ? WHERE plan_id = ? AND owner_id = ?",
                (initial_state, plan_id, owner_id),
            )

        original_connect = store._connect
        guard_read_seen = False

        @contextmanager
        def interleaving_connect(*args, **kwargs):
            nonlocal guard_read_seen
            with original_connect(*args, **kwargs) as conn:

                class ConnectionProxy:
                    def execute(self, sql, parameters=()):
                        nonlocal guard_read_seen
                        if (
                            not guard_read_seen
                            and "SELECT state" in sql
                            and "operation_kind" in sql
                            and "mastery_learning_plans" in sql
                        ):
                            result = conn.execute(sql, parameters)
                            guard_read_seen = True
                            with LearningStore(root=store._root)._connect() as competing:
                                competing.execute(
                                    """UPDATE mastery_learning_plans
                                    SET operation_kind = 'generation', operation_token = 'rival'
                                    WHERE plan_id = ? AND owner_id = ?""",
                                    (plan_id, owner_id),
                                )
                            return result
                        return conn.execute(sql, parameters)

                    def __getattr__(self, name):
                        return getattr(conn, name)

                yield ConnectionProxy()

        monkeypatch.setattr(store, "_connect", interleaving_connect)
        with pytest.raises(LearningPlanConflictError, match="busy"):
            getattr(store, method_name)(plan_id, payload, owner_id=owner_id)

        plan = store.get_learning_plan(plan_id, owner_id=owner_id)
        assert plan is not None
        with LearningStore(root=store._root)._connect() as conn:
            operation_kind = conn.execute(
                "SELECT operation_kind FROM mastery_learning_plans WHERE plan_id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()["operation_kind"]
        assert operation_kind == "generation"
        assert plan["brief"]["name"] == "Original"


# ── save / load ──────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_load(self, store):
        lp = LearningProgress(book_id="book1")
        lp.mastery_levels["kp1"] = 0.75
        store.save(lp)
        loaded = store.load("book1")
        assert loaded is not None
        assert loaded.book_id == "book1"
        assert loaded.mastery_levels["kp1"] == 0.75

    def test_enum_roundtrip(self, store):
        lp = LearningProgress(book_id="book1")
        lp.knowledge_types["kp1"] = KnowledgeType.MEMORY
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.knowledge_types["kp1"] == KnowledgeType.MEMORY

    def test_repetition_state_roundtrip(self, store):
        lp = LearningProgress(book_id="book1")
        state = RepetitionState(interval_index=2, next_review_at=time.time() + 86400)
        lp.repetition_states["kp1"] = state
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.repetition_states["kp1"].interval_index == 2

    def test_updated_at_auto_updates(self, store):
        lp = LearningProgress(book_id="book1")
        old_updated = lp.updated_at
        time.sleep(0.01)
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.updated_at >= old_updated

    def test_version_increments_on_each_save(self, store):
        lp = LearningProgress(book_id="book1")
        assert lp.version == 0
        store.save(lp)
        assert store.load("book1").version == 1
        store.save(lp)
        assert store.load("book1").version == 2

    def test_save_overwrites_previous(self, store):
        lp = LearningProgress(book_id="book1")
        lp.mastery_levels["kp1"] = 0.2
        store.save(lp)
        lp.mastery_levels["kp1"] = 0.9
        store.save(lp)
        assert store.load("book1").mastery_levels["kp1"] == 0.9

    def test_stale_snapshot_is_rejected_instead_of_losing_progress(self, store):
        store.save(LearningProgress(book_id="book1"))
        first = store.load("book1")
        second = store.load("book1")
        assert first is not None and second is not None

        first.mastery_levels["kp-a"] = 0.8
        store.save(first)
        second.qualitative_mastery["kp-b"] = True

        with pytest.raises(LearningConflictError) as conflict:
            store.save(second)

        assert conflict.value.expected == 1
        assert conflict.value.actual == 2
        loaded = store.load("book1")
        assert loaded is not None
        assert loaded.mastery_levels == {"kp-a": 0.8}
        assert loaded.qualitative_mastery == {}

    def test_transaction_serializes_concurrent_mutations(self, store):
        store.save(LearningProgress(book_id="book1"))

        def update(key: str) -> None:
            def mutate(tx):
                tx.progress.mastery_levels[key] = 0.5
                time.sleep(0.02)
                tx.touch()
                tx.emit("mastery.changed", {"knowledge_point_id": key})

            store.mutate("book1", mutate)

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(update, ["kp-a", "kp-b"]))

        loaded = store.load("book1")
        assert loaded is not None
        assert loaded.mastery_levels == {"kp-a": 0.5, "kp-b": 0.5}
        assert loaded.version == 3


# ── load nonexistent ─────────────────────────────────────────────────────


class TestLoadNonexistent:
    def test_returns_none(self, store):
        assert store.load("nonexistent") is None


# ── exists ───────────────────────────────────────────────────────────────


class TestExists:
    def test_true_after_save(self, store):
        store.save(LearningProgress(book_id="book1"))
        assert store.exists("book1") is True

    def test_false_when_missing(self, store):
        assert store.exists("nonexistent") is False


# ── delete ───────────────────────────────────────────────────────────────


class TestDelete:
    def test_removes_progress_row(self, store, tmp_path):
        store.save(LearningProgress(book_id="book1"))
        assert (tmp_path / "mastery.sqlite3").exists()
        store.delete("book1")
        assert store.load("book1") is None
        assert not (tmp_path / "book1.json").exists()

    def test_delete_nonexistent_no_error(self, store):
        store.delete("nonexistent")  # should not raise

    def test_delete_only_targets_named_book(self, store):
        store.save(LearningProgress(book_id="keep"))
        store.save(LearningProgress(book_id="drop"))
        store.delete("drop")
        assert store.exists("keep") is True
        assert store.exists("drop") is False


# ── path traversal ───────────────────────────────────────────────────────


class TestPathTraversal:
    def test_rejects_slash(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("../settings/foo")

    def test_rejects_backslash(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("a\\b")

    def test_rejects_dotdot(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("..")

    def test_rejects_colon(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("D:foo")

    def test_rejects_in_save(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.save(LearningProgress(book_id="../evil"))

    def test_rejects_in_delete(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.delete("../evil")

    def test_rejects_in_exists(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.exists("../evil")


# ── list_all ──────────────────────────────────────────────────────────────


class TestListAll:
    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_list_all_multiple(self, store):
        store.save(LearningProgress(book_id="a"))
        store.save(LearningProgress(book_id="b"))
        ids = store.list_all()
        assert sorted(ids) == ["a", "b"]

    def test_list_all_after_delete(self, store):
        store.save(LearningProgress(book_id="x"))
        store.save(LearningProgress(book_id="y"))
        store.delete("x")
        assert store.list_all() == ["y"]

    def test_list_all_ignores_dotfiles(self, store, tmp_path):
        store.save(LearningProgress(book_id="visible"))
        (tmp_path / ".hidden.json").write_text("{}", encoding="utf-8")
        assert store.list_all() == ["visible"]


class TestTopicMetadata:
    def test_topic_metadata_and_mixed_sources_roundtrip(self, store):
        store.save(LearningProgress(book_id="path-1", name="Linear Algebra"))
        metadata = TopicMetadata(
            path_id="path-1",
            goal="Understand vectors and linear maps",
            description="A visual route through first-year linear algebra.",
            emoji="🧭",
            map_seed=42,
        )
        sources = [
            TopicSource(
                id="source-book",
                kind=TopicSourceKind.BOOK,
                source_id="book-1",
                label="Linear Algebra Notes",
                position=0,
            ),
            TopicSource(
                id="source-kb",
                kind=TopicSourceKind.KNOWLEDGE_BASE,
                source_id="kb-1",
                label="Course KB",
                position=1,
                metadata={"engine": "llamaindex"},
            ),
        ]

        store.put_topic(metadata, sources)

        topic = store.get_topic("path-1")
        assert topic is not None
        assert topic.metadata.goal == "Understand vectors and linear maps"
        assert topic.metadata.emoji == "🧭"
        assert [source.kind for source in topic.sources] == [
            TopicSourceKind.BOOK,
            TopicSourceKind.KNOWLEDGE_BASE,
        ]
        assert topic.sources[1].metadata == {"engine": "llamaindex"}
        assert store.list_events("path-1")[-1].event_type == "topic.updated"

    def test_existing_path_gets_stable_synthesized_topic_metadata(self, store):
        store.save(LearningProgress(book_id="legacy-path", name="Legacy"))

        first = store.get_topic("legacy-path")
        second = store.get_topic("legacy-path")

        assert first is not None and second is not None
        assert first.metadata.path_id == "legacy-path"
        assert first.metadata.map_seed == second.metadata.map_seed
        assert first.sources == []

    def test_topic_snapshots_batch_active_topics_with_counts_and_sources(self, store):
        for path_id in ("active-path", "archived-path"):
            store.save(LearningProgress(book_id=path_id, name=path_id))
        store.put_topic(
            TopicMetadata(path_id="active-path", goal="Learn"),
            [
                TopicSource(
                    id="source-1",
                    kind=TopicSourceKind.BOOK,
                    label="Course book",
                )
            ],
        )
        store.put_topic(
            TopicMetadata(path_id="archived-path", status="archived"),
            [],
        )
        store.bind_session("active-path", "session-a")
        store.bind_session("active-path", "session-b")

        snapshots = store.list_topic_snapshots()

        assert len(snapshots) == 1
        progress, topic, session_count, active_interaction = snapshots[0]
        assert progress.book_id == "active-path"
        assert [source.label for source in topic.sources] == ["Course book"]
        assert session_count == 2
        assert active_interaction is None


class TestLegacyMigration:
    def test_json_path_is_imported_and_archived_on_first_read(self, store, tmp_path):
        progress = LearningProgress(book_id="legacy")
        progress.mastery_levels["kp1"] = 0.75
        legacy_path = tmp_path / "legacy.json"
        legacy_path.write_text(
            json.dumps(progress.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

        loaded = store.load("legacy")

        assert loaded is not None
        assert loaded.mastery_levels == {"kp1": 0.75}
        assert loaded.version >= 1
        assert not legacy_path.exists()
        assert (tmp_path / ".legacy" / "legacy.json").exists()
        assert store.list_events("legacy")[0].event_type == "path.migrated"

    def test_binding_a_legacy_path_imports_before_creating_association(self, store, tmp_path):
        progress = LearningProgress(book_id="legacy-bound")
        progress.mastery_levels["kp1"] = 0.9
        (tmp_path / "legacy-bound.json").write_text(
            json.dumps(progress.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

        store.bind_session("legacy-bound", "session-1")

        loaded = store.load("legacy-bound")
        assert loaded is not None
        assert loaded.mastery_levels == {"kp1": 0.9}
        assert store.list_session_ids("legacy-bound") == ["session-1"]


class TestPathSessionOwnership:
    def test_legacy_session_keyed_path_is_deleted_on_detach(self, store):
        store.save(LearningProgress(book_id="legacy-session"))

        assert store.detach_session("legacy-session") == ["legacy-session"]
        assert store.exists("legacy-session") is False

    def test_owned_path_is_deleted_only_after_its_last_session_detaches(self, store):
        store.bind_session("path-1", "owner", owns_path=True)
        store.bind_session("path-1", "guest")

        assert store.detach_session("owner") == []
        assert store.exists("path-1") is True
        assert store.list_session_ids("path-1") == ["guest"]

        assert store.detach_session("guest") == []
        assert store.exists("path-1") is True

    def test_owned_orphan_is_deleted_with_owning_session(self, store):
        store.bind_session("path-1", "owner", owns_path=True)

        assert store.detach_session("owner") == ["path-1"]
        assert store.exists("path-1") is False

    def test_explicit_path_survives_session_deletion(self, store):
        store.bind_session("path-1", "session-1", owns_path=False)

        assert store.detach_session("session-1") == []
        assert store.exists("path-1") is True


class TestPathLease:
    def test_only_one_turn_can_own_a_path(self, store):
        first = store.acquire_path_lease("path-1", "session-1", "turn-1")
        assert first.turn_id == "turn-1"

        with pytest.raises(PathLeaseConflictError) as conflict:
            store.acquire_path_lease("path-1", "session-2", "turn-2")

        assert conflict.value.lease.session_id == "session-1"
        assert store.release_path_lease("path-1", turn_id="turn-2") is False
        assert store.release_path_lease("path-1", turn_id="turn-1") is True
        assert store.acquire_path_lease("path-1", "session-2", "turn-2").turn_id == "turn-2"


class TestInteractionsAndEvents:
    def _interaction(self, interaction_id: str) -> MasteryInteraction:
        question = PendingQuestion(
            question_id=interaction_id,
            knowledge_point_id="kp-1",
            prompt="Question?",
            expected_answer="answer",
        )
        return MasteryInteraction(
            interaction_id=interaction_id,
            path_id="path-1",
            question=question,
        )

    def test_transaction_persists_interaction_and_redacted_event(self, store):
        def register(tx):
            interaction = self._interaction("question-1")
            tx.progress.pending_question = interaction.question
            tx.put_interaction(interaction)
            tx.emit(
                "interaction.registered",
                {"interaction_id": interaction.interaction_id, "prompt": "Question?"},
            )

        progress, _ = store.mutate("path-1", register, create=True)

        assert progress.version == 1
        persisted = store.get_active_interaction("path-1")
        assert persisted is not None
        assert persisted.status == InteractionStatus.REGISTERED
        events = store.list_events("path-1")
        assert [event.event_type for event in events] == [
            "path.created",
            "interaction.registered",
        ]
        assert "expected_answer" not in json.dumps(events[-1].payload)

    def test_partial_unique_index_rejects_two_active_questions(self, store):
        def register_two(tx):
            tx.put_interaction(self._interaction("question-1"))
            tx.put_interaction(self._interaction("question-2"))

        with pytest.raises(sqlite3.IntegrityError):
            store.mutate("path-1", register_two, create=True)

        assert store.exists("path-1") is False

    def test_interaction_id_cannot_be_reassigned_to_another_path(self, store):
        store.mutate(
            "path-1",
            lambda tx: tx.put_interaction(self._interaction("question-1")),
            create=True,
        )
        second = self._interaction("question-1")
        second.path_id = "path-2"

        with pytest.raises(ValueError, match="another path"):
            store.mutate(
                "path-2",
                lambda tx: tx.put_interaction(second),
                create=True,
            )

        assert store.exists("path-2") is False
        assert store.get_interaction("path-1", "question-1") is not None

    def test_terminal_interaction_cannot_be_reopened(self, store):
        interaction = self._interaction("question-1")
        interaction.status = InteractionStatus.GRADED
        store.mutate(
            "path-1",
            lambda tx: tx.put_interaction(interaction),
            create=True,
        )
        interaction.status = InteractionStatus.REGISTERED

        with pytest.raises(LearningStoreError, match="graded -> registered"):
            store.mutate(
                "path-1",
                lambda tx: tx.put_interaction(interaction),
            )

        persisted = store.get_interaction("path-1", "question-1")
        assert persisted is not None
        assert persisted.status == InteractionStatus.GRADED


# ── atomic write ──────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "nested" / "out.json"
        _atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c.json"
        _atomic_write_text(target, "x")
        assert target.exists()

    def test_no_orphan_temp_files_on_success(self, tmp_path):
        target = tmp_path / "out.json"
        _atomic_write_text(target, "data")
        leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert leftovers == []

    def test_cleans_up_temp_on_replace_failure(self, tmp_path, monkeypatch):
        target = tmp_path / "out.json"

        def boom(self, _dst):  # noqa: ANN001
            raise OSError("simulated replace failure")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError, match="simulated replace failure"):
            _atomic_write_text(target, "data")
        # The original target must not exist, and no .tmp leftover should remain.
        assert not target.exists()
        leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert leftovers == []
