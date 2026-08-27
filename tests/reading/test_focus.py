"""Focus Reading progression and the server-side checkpoint boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import zipfile

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import get_path_service_for_scope, user_context
from deeptutor.reading import (
    FocusCheckpointConflict,
    FocusEvaluation,
    FocusEvaluationError,
    FocusState,
    ReadingCatalogStore,
    ReadingStore,
    derive_focus_plan,
    evaluate_focus_answer,
    get_focus_snapshot,
    start_focus,
    submit_focus_check,
)


def _write_epub(path: Path) -> Path:
    chapters = [
        ("front", "Front Matter", "Front Matter\nCopyright 2026."),
        (
            "toc",
            "第二章 火车情结",
            "\n".join(f"第{i}章 目录项目" for i in range(1, 8)),
        ),
        ("one", "A real beginning", "A real beginning\n" + "alpha " * 100),
        ("two", "A second chapter", "A second chapter\n" + "beta " * 100),
        ("three", "A conclusion", "A conclusion\n" + "gamma " * 100),
    ]
    manifest = "".join(
        f"<item id='{key}' href='{key}.xhtml' media-type='application/xhtml+xml'/>"
        for key, _, _ in chapters
    )
    spine = "".join(f"<itemref idref='{key}'/>" for key, _, _ in chapters)
    nav = "".join(f"<li><a href='{key}.xhtml'>{title}</a></li>" for key, title, _ in chapters)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            "<container><rootfiles><rootfile full-path='OPS/book.opf'/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/book.opf",
            "<package xmlns:dc='http://purl.org/dc/elements/1.1/'><metadata>"
            "<dc:identifier>focus-test</dc:identifier><dc:title>Focus Test</dc:title>"
            "</metadata><manifest>"
            "<item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' "
            f"properties='nav'/>{manifest}"
            f"</manifest><spine>{spine}</spine></package>",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            "<html xmlns:epub='http://www.idpf.org/2007/ops'><body>"
            f"<nav epub:type='toc'><ol>{nav}</ol></nav></body></html>",
        )
        for key, title, body in chapters:
            archive.writestr(
                f"OPS/{key}.xhtml",
                f"<html><head><title>{title}</title></head>"
                f"<body><h1>{title}</h1><p>{body}</p></body></html>",
            )
    return path


@pytest.fixture
def focus_material(tmp_path: Path) -> tuple[ReadingStore, str]:
    store = ReadingStore(tmp_path / "reading")
    manifest = store.ingest(_write_epub(tmp_path / "focus.epub"))
    return store, manifest.material_id


async def _passing(*_args: str) -> FocusEvaluation:
    return FocusEvaluation(score=88, feedback="Good", strengths=("plot",), missing=())


def test_default_store_uses_the_request_scoped_reading_workspace(tmp_path: Path) -> None:
    alice = CurrentUser(
        id="alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="alice", root=tmp_path / "alice"),
    )
    bob = CurrentUser(
        id="bob",
        username="bob",
        role="user",
        scope=UserScope(kind="user", user_id="bob", root=tmp_path / "bob"),
    )

    with user_context(alice):
        alice_root = ReadingStore().root
    with user_context(bob):
        bob_root = ReadingStore().root

    assert alice_root == get_path_service_for_scope(alice.scope).get_workspace_feature_dir(
        "reading"
    )
    assert bob_root == get_path_service_for_scope(bob.scope).get_workspace_feature_dir("reading")
    assert alice_root != bob_root


def test_plan_skips_front_matter_and_toc_like_chapter(focus_material) -> None:
    store, material_id = focus_material
    checkpoints, _ = derive_focus_plan(store, material_id)

    assert [row.start_locator for row in checkpoints] == [3, 4, 5]
    assert all("Front Matter" not in row.title for row in checkpoints)


def test_catalog_copies_keep_independent_focus_runs(focus_material) -> None:
    store, material_id = focus_material
    catalog = ReadingCatalogStore(store.root)
    manifest = store.manifest(material_id)
    catalog.register_manifest(manifest)
    copy_id = "rm_123456abcdef"
    catalog.upsert_material(
        content_id=material_id,
        material_id=copy_id,
        filename=manifest.filename,
        title="Independent copy",
        source_kind="file",
        mime=manifest.mime,
        render_mode=manifest.render_mode,
        status="ready",
    )
    first = start_focus(store, material_id)
    _, passed, _ = asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoints[0].checkpoint_id,
            run_id=first.state.run_id,
            revision=first.state.revision,
            summary="This is a sufficiently detailed summary.",
            reflection="This part mattered to me.",
            evaluator=_passing,
        )
    )
    assert not get_focus_snapshot(store, copy_id).state.active
    second = start_focus(store, copy_id)
    assert second.state.run_id != first.state.run_id
    assert second.state.passed_checkpoint_ids == ()
    assert second.expected_checkpoint == first.checkpoints[0]
    start_focus(store, copy_id, reset=True)
    assert store.focus_state(material_id) == passed.state

    store.delete_material_state(copy_id)
    assert not store.focus_state(copy_id).active
    assert store.focus_state(material_id) == passed.state


def test_updated_source_invalidates_passes_even_with_identical_size(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    material_id = "a" * 16
    first_units = [
        "A beginning: " + "alpha " * 100,
        "A middle: " + "bravo " * 100,
        "An ending: " + "gamma " * 100,
    ]
    original = store.ingest_units(
        material_id, filename="source.md", units=first_units, unit="chapter"
    )
    first = start_focus(store, material_id)
    _, passed, _ = asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoints[0].checkpoint_id,
            run_id=first.state.run_id,
            revision=first.state.revision,
            summary="This is a sufficiently detailed summary.",
            reflection="This part mattered to me.",
            evaluator=_passing,
        )
    )
    revised = store.ingest_units(
        material_id,
        filename="source.md",
        units=[text.replace("alpha", "delta") for text in first_units],
        unit="chapter",
    )
    assert revised.char_count == original.char_count
    assert revised.revision == original.revision + 1
    # The source refresh preserves the state file; the plan invalidates it.
    assert store.focus_state(material_id) == passed.state
    restarted = start_focus(store, material_id)
    assert restarted.state.plan_hash != passed.state.plan_hash
    assert restarted.state.run_id != passed.state.run_id
    assert restarted.state.passed_checkpoint_ids == ()


def test_legacy_focus_state_is_not_inherited_by_catalog_copy(focus_material) -> None:
    store, material_id = focus_material
    manifest = store.manifest(material_id)
    copy_id = "rm_123456abcdef"
    ReadingCatalogStore(store.root).upsert_material(
        content_id=material_id,
        material_id=copy_id,
        filename=manifest.filename,
        title="Copy",
        source_kind="file",
        status="ready",
    )
    legacy = FocusState(active=True, run_id="legacy-run")
    (store.root / material_id / "focus.json").write_text(
        json.dumps(legacy.to_dict()), encoding="utf-8"
    )
    assert store.focus_state(material_id) == legacy
    assert not store.focus_state(copy_id).active


def test_later_checkpoint_is_rejected_before_evaluation_and_cannot_be_prepassed(
    focus_material,
) -> None:
    store, material_id = focus_material
    focus = start_focus(store, material_id)
    called = False

    async def evaluator(*_args: str) -> FocusEvaluation:
        nonlocal called
        called = True
        return await _passing(*_args)

    later = focus.checkpoints[1]
    with pytest.raises(FocusCheckpointConflict):
        asyncio.run(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=later.checkpoint_id,
                run_id=focus.state.run_id,
                revision=focus.state.revision,
                summary="This is a sufficiently detailed summary.",
                reflection="This part mattered to me.",
                evaluator=evaluator,
            )
        )

    assert called is False
    assert get_focus_snapshot(store, material_id).state.passed_checkpoint_ids == ()

    first = focus.expected_checkpoint
    assert first is not None
    _, after_first, _ = asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoint_id,
            run_id=focus.state.run_id,
            revision=focus.state.revision,
            summary="This is a sufficiently detailed summary.",
            reflection="This part mattered to me.",
            evaluator=_passing,
        )
    )
    assert after_first.expected_checkpoint == later


def test_out_of_order_persisted_ids_are_truncated_to_the_exact_prefix(
    focus_material,
) -> None:
    store, material_id = focus_material
    started = start_focus(store, material_id)
    first, second = started.checkpoints[:2]
    with store.material_lock(material_id):
        store._write_focus_state_locked(
            material_id,
            FocusState(
                active=True,
                run_id=started.state.run_id,
                revision=started.state.revision,
                plan_hash=started.state.plan_hash,
                passed_checkpoint_ids=(second.checkpoint_id, first.checkpoint_id),
            ),
        )

    resumed = start_focus(store, material_id)
    assert resumed.state.passed_checkpoint_ids == ()
    assert resumed.expected_checkpoint == first


def test_plan_change_starts_a_fresh_opaque_run(focus_material) -> None:
    store, material_id = focus_material
    started = start_focus(store, material_id)
    with store.material_lock(material_id):
        store._write_focus_state_locked(
            material_id,
            FocusState(
                active=True,
                run_id=started.state.run_id,
                revision=started.state.revision,
                plan_hash="obsolete-plan",
                passed_checkpoint_ids=(started.checkpoints[0].checkpoint_id,),
            ),
        )

    restarted = start_focus(store, material_id)
    assert restarted.state.run_id != started.state.run_id
    assert restarted.state.passed_checkpoint_ids == ()


def test_success_advances_exactly_one_checkpoint_and_old_request_is_idempotent(
    focus_material,
) -> None:
    store, material_id = focus_material
    focus = start_focus(store, material_id)
    first = focus.expected_checkpoint
    assert first is not None

    attempt, advanced, idempotent = asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoint_id,
            run_id=focus.state.run_id,
            revision=focus.state.revision,
            summary="The chapter establishes the central conflict clearly.",
            reflection="Its uncertainty felt personally meaningful.",
            evaluator=_passing,
        )
    )
    assert attempt.passed is True
    assert idempotent is False
    assert advanced.state.passed_checkpoint_ids == (first.checkpoint_id,)
    assert advanced.expected_checkpoint == advanced.checkpoints[1]

    repeated, same, idempotent = asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoint_id,
            run_id=focus.state.run_id,
            revision=focus.state.revision,
            summary="The chapter establishes the central conflict clearly.",
            reflection="Its uncertainty felt personally meaningful.",
            evaluator=_passing,
        )
    )
    assert idempotent is True
    assert repeated == attempt
    assert same.state.revision == advanced.state.revision


def test_idempotence_never_crosses_a_reset_run(focus_material) -> None:
    store, material_id = focus_material
    original = start_focus(store, material_id)
    first = original.expected_checkpoint
    assert first is not None
    asyncio.run(
        submit_focus_check(
            store,
            material_id,
            checkpoint_id=first.checkpoint_id,
            run_id=original.state.run_id,
            revision=original.state.revision,
            summary="The chapter establishes the central conflict clearly.",
            reflection="Its uncertainty felt personally meaningful.",
            evaluator=_passing,
        )
    )

    restarted = start_focus(store, material_id, reset=True)
    with pytest.raises(FocusCheckpointConflict):
        asyncio.run(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=first.checkpoint_id,
                run_id=original.state.run_id,
                revision=original.state.revision,
                summary="The chapter establishes the central conflict clearly.",
                reflection="Its uncertainty felt personally meaningful.",
                evaluator=_passing,
            )
        )
    current = get_focus_snapshot(store, material_id)
    assert current.state.run_id == restarted.state.run_id
    assert current.state.passed_checkpoint_ids == ()


def test_invalid_evaluator_response_does_not_write_zero_or_change_revision(
    focus_material,
) -> None:
    store, material_id = focus_material
    focus = start_focus(store, material_id)
    before = (store.root / material_id / "focus" / f"{material_id}.json").read_text(
        encoding="utf-8"
    )

    async def invalid(*_args: str) -> FocusEvaluation:
        raise FocusEvaluationError("invalid model response")

    with pytest.raises(FocusEvaluationError):
        asyncio.run(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=focus.expected_checkpoint.checkpoint_id,  # type: ignore[union-attr]
                run_id=focus.state.run_id,
                revision=focus.state.revision,
                summary="This is a sufficiently detailed summary.",
                reflection="This part mattered to me.",
                evaluator=invalid,
            )
        )

    after = (store.root / material_id / "focus" / f"{material_id}.json").read_text(encoding="utf-8")
    assert json.loads(after) == json.loads(before)
    assert get_focus_snapshot(store, material_id).state.attempts == ()


def test_reset_while_model_is_running_makes_old_result_stale(focus_material) -> None:
    store, material_id = focus_material

    async def scenario() -> None:
        focus = start_focus(store, material_id)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(*_args: str) -> FocusEvaluation:
            entered.set()
            await release.wait()
            return await _passing(*_args)

        task = asyncio.create_task(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=focus.expected_checkpoint.checkpoint_id,  # type: ignore[union-attr]
                run_id=focus.state.run_id,
                revision=focus.state.revision,
                summary="This is a sufficiently detailed summary.",
                reflection="This part mattered to me.",
                evaluator=blocked,
            )
        )
        await entered.wait()
        restarted = start_focus(store, material_id, reset=True)
        release.set()
        with pytest.raises(FocusCheckpointConflict):
            await task
        current = get_focus_snapshot(store, material_id)
        assert current.state.run_id == restarted.state.run_id
        assert current.state.passed_checkpoint_ids == ()
        assert current.state.attempts == ()

    asyncio.run(scenario())


def test_plan_change_while_model_is_running_cannot_commit_stale_progress(
    focus_material,
) -> None:
    store, material_id = focus_material

    async def scenario() -> None:
        focus = start_focus(store, material_id)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(*_args: str) -> FocusEvaluation:
            entered.set()
            await release.wait()
            return await _passing(*_args)

        task = asyncio.create_task(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=focus.expected_checkpoint.checkpoint_id,  # type: ignore[union-attr]
                run_id=focus.state.run_id,
                revision=focus.state.revision,
                summary="This is a sufficiently detailed summary.",
                reflection="This part mattered to me.",
                evaluator=blocked,
            )
        )
        await entered.wait()
        before = (store.root / material_id / "focus" / f"{material_id}.json").read_text(
            encoding="utf-8"
        )
        with store.material_lock(material_id):
            manifest_path = store.root / material_id / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["extractor"] = f"{manifest['extractor']}-upgraded"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        release.set()
        with pytest.raises(FocusCheckpointConflict):
            await task

        after = (store.root / material_id / "focus" / f"{material_id}.json").read_text(
            encoding="utf-8"
        )
        assert json.loads(after) == json.loads(before)
        current = get_focus_snapshot(store, material_id)
        assert current.state.run_id == ""
        assert current.state.passed_checkpoint_ids == ()

    asyncio.run(scenario())


def test_stale_revision_is_rejected_before_evaluation(focus_material) -> None:
    store, material_id = focus_material
    focus = start_focus(store, material_id)
    called = False

    async def evaluator(*_args: str) -> FocusEvaluation:
        nonlocal called
        called = True
        return await _passing(*_args)

    with pytest.raises(FocusCheckpointConflict):
        asyncio.run(
            submit_focus_check(
                store,
                material_id,
                checkpoint_id=focus.expected_checkpoint.checkpoint_id,  # type: ignore[union-attr]
                run_id=focus.state.run_id,
                revision=focus.state.revision + 1,
                summary="This is a sufficiently detailed summary.",
                reflection="This part mattered to me.",
                evaluator=evaluator,
            )
        )
    assert called is False


def test_concurrent_duplicate_submissions_advance_only_once(focus_material) -> None:
    store, material_id = focus_material

    async def scenario() -> None:
        focus = start_focus(store, material_id)
        entered = 0
        both_entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked(*_args: str) -> FocusEvaluation:
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return await _passing(*_args)

        kwargs = {
            "checkpoint_id": focus.expected_checkpoint.checkpoint_id,  # type: ignore[union-attr]
            "run_id": focus.state.run_id,
            "revision": focus.state.revision,
            "summary": "This is a sufficiently detailed summary.",
            "reflection": "This part mattered to me.",
            "evaluator": blocked,
        }
        tasks = [
            asyncio.create_task(submit_focus_check(store, material_id, **kwargs)) for _ in range(2)
        ]
        await both_entered.wait()
        release.set()
        results = await asyncio.gather(*tasks)

        assert sorted(result[2] for result in results) == [False, True]
        current = get_focus_snapshot(store, material_id)
        assert current.state.revision == focus.state.revision + 1
        assert len(current.state.passed_checkpoint_ids) == 1

    asyncio.run(scenario())


def test_default_evaluator_uses_small_non_reasoning_json_output(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_complete(prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return json.dumps(
            {
                "score": 72,
                "feedback": "Understood",
                "strengths": ["sequence"],
                "missing": [],
            }
        )

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    result = asyncio.run(
        evaluate_focus_answer(
            "Book",
            "Chapter",
            "Trusted source content",
            "A detailed account of what happened in the chapter.",
            "The ending changed how I saw the narrator.",
            "en",
        )
    )

    assert result.score == 72
    assert captured["max_tokens"] == 2048
    assert captured["reasoning_effort"] == "minimal"
    assert captured["response_format"] == {"type": "json_object"}


def test_default_evaluator_rejects_invalid_json(monkeypatch) -> None:
    async def fake_complete(*_args: object, **_kwargs: object) -> str:
        return "not structured output"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    with pytest.raises(FocusEvaluationError):
        asyncio.run(
            evaluate_focus_answer(
                "Book",
                "Chapter",
                "Source",
                "A detailed account of what happened in the chapter.",
                "The ending changed how I saw the narrator.",
                "en",
            )
        )
