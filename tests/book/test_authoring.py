"""Real file-store previews, source-bound proposals, apply receipts and undo."""

import json
from types import SimpleNamespace

import pytest

from deeptutor.book.authoring import BookEdit, apply_edit, list_edits, preview_edit, recover_edits
from deeptutor.book.models import PageStatus
from tests.book.test_chapter_crud import _seed, _storage


def test_add_rename_reorder_delete_section_preserves_compiled_blocks(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage)
    original = storage.load_page("bk", "pg_1").model_dump()
    record = preview_edit(
        storage,
        "bk",
        BookEdit(
            action="add_page",
            chapter_id="ch_0",
            title="Prerequisite",
            position=0,
            learning_objectives=["Understand limits"],
        ),
    )
    assert len(storage.list_pages("bk")) == 3  # preview has no content write
    apply_edit(storage, "bk", record["id"], 1)
    new = storage.list_pages("bk")[0]
    assert new.title == "Prerequisite" and new.status == PageStatus.PENDING
    assert new.learning_objectives == ["Understand limits"]
    assert storage.load_page("bk", "pg_1").model_dump() == original
    for action, kwargs in [
        ("rename_page", {"title": "Limits"}),
        ("move_page", {"position": 1}),
        ("delete_page", {}),
    ]:
        before = storage.load_book("bk").revision
        edit = preview_edit(storage, "bk", BookEdit(action=action, page_id=new.id, **kwargs))
        apply_edit(storage, "bk", edit["id"], before)
        assert storage.load_page("bk", "pg_1").model_dump() == original
    assert storage.load_page("bk", new.id) is None
    assert storage.load_book("bk").page_count == 3


def test_confirmed_ai_edit_is_receipted_traceable_and_undoable(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage)
    page = storage.load_page("bk", "pg_0").model_dump(mode="json")
    record = preview_edit(
        storage,
        "bk",
        BookEdit(
            action="extend_page", page_id="pg_0", title="Clarification", body="Agreed conclusion"
        ),
        source_session_id="session_1",
        source_turn_id="turn_1",
    )
    assert storage.load_page("bk", "pg_0").model_dump(mode="json") == page
    assert "Agreed conclusion" in record["diff"]
    receipt = apply_edit(storage, "bk", record["id"], 1)
    assert apply_edit(storage, "bk", record["id"], 1) == receipt
    assert len(storage.load_page("bk", "pg_0").blocks) == 2
    assert storage.load_page("bk", "pg_0").blocks[-1].metadata["source_turn_id"] == "turn_1"
    assert list_edits(storage, "bk", "pg_1") == []
    assert list_edits(storage, "bk", "pg_0")[0]["source_session_id"] == "session_1"
    apply_edit(storage, "bk", record["id"], 2, undo=True)
    assert storage.load_page("bk", "pg_0").model_dump(mode="json") == page
    assert storage.load_book("bk").revision == 3


def test_stale_preview_and_external_content_change_do_not_overwrite(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage)
    one = preview_edit(storage, "bk", BookEdit(action="rename_page", page_id="pg_0", title="One"))
    two = preview_edit(storage, "bk", BookEdit(action="rename_page", page_id="pg_1", title="Two"))
    apply_edit(storage, "bk", one["id"], 1)
    with pytest.raises(ValueError, match="revision"):
        apply_edit(storage, "bk", two["id"], 1)
    page = storage.load_page("bk", "pg_0")
    page.blocks[0].payload["body"] = "Later user edit"
    storage.save_page(page)
    with pytest.raises(ValueError, match="content changed"):
        apply_edit(storage, "bk", one["id"], 2, undo=True)
    assert storage.load_page("bk", "pg_0").blocks[0].payload["body"] == "Later user edit"


def test_interrupted_multifile_apply_recovers_original_before_next_edit(tmp_path, monkeypatch):
    import deeptutor.book.authoring as authoring

    storage = _storage(tmp_path)
    _seed(storage)
    before = storage.load_spine("bk").model_dump()
    proposal = preview_edit(
        storage, "bk", BookEdit(action="add_page", chapter_id="ch_0", title="New")
    )
    original = authoring.atomic_write_json
    writes = 0

    def crash(path, value):
        nonlocal writes
        writes += 1
        if writes == 3:
            raise KeyboardInterrupt("simulated process termination")
        return original(path, value)

    monkeypatch.setattr(authoring, "atomic_write_json", crash)
    with pytest.raises(KeyboardInterrupt):
        apply_edit(storage, "bk", proposal["id"], 1)
    monkeypatch.setattr(authoring, "atomic_write_json", original)
    recover_edits(storage, "bk")
    assert storage.load_spine("bk").model_dump() == before
    assert len(storage.list_pages("bk")) == 3
    assert storage.load_book("bk").revision == 1
    assert list_edits(storage, "bk")[0]["status"] == "proposed"


@pytest.mark.asyncio
async def test_book_tool_only_proposes_in_its_server_bound_editable_page(tmp_path, monkeypatch):
    from deeptutor.book.authoring_tool import ProposeBookEditTool
    import deeptutor.multi_user.book_access as access

    storage = _storage(tmp_path)
    engine = _seed(storage)
    allowed = True
    monkeypatch.setattr(
        access,
        "resolve_book",
        lambda book_id: (
            SimpleNamespace(can_edit=allowed, engine=engine) if book_id == "bk" else None
        ),
    )
    tool = ProposeBookEditTool()
    kwargs = dict(
        action="extend_page",
        title="Proof",
        body="A useful proof",
        _book_scope={"book_id": "bk", "page_id": "pg_0"},
        _source_turn_id="turn_1",
        _source_session_id="session_1",
    )
    response = await tool.execute(**kwargs)
    assert response.success
    assert storage.load_book("bk").revision == 1
    assert len(storage.load_page("bk", "pg_0").blocks) == 1
    assert list_edits(storage, "bk")[0]["source_turn_id"] == "turn_1"
    allowed = False
    assert not (await tool.execute(**kwargs)).success
    assert not (await tool.execute(action="extend_page", body="No scope")).success


@pytest.mark.asyncio
async def test_new_section_compiles_with_its_own_goal_and_title(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    engine = _seed(storage)
    proposal = preview_edit(
        storage,
        "bk",
        BookEdit(
            action="add_page",
            chapter_id="ch_0",
            title="Limits",
            learning_objectives=["Explain limits"],
        ),
    )
    apply_edit(storage, "bk", proposal["id"], 1)
    page = storage.list_pages("bk")[0]
    seen = []

    async def compile_page(**kwargs):
        seen.append(kwargs["chapter"])
        return kwargs["page"]

    monkeypatch.setattr(engine.compiler, "compile_page", compile_page)
    await engine.compile_page(book_id="bk", page_id=page.id)
    assert seen[0].title == "Limits"
    assert seen[0].learning_objectives == ["Explain limits"]
    assert storage.load_page("bk", "pg_1").blocks[0].payload["body"] == "compiled prose 1"


@pytest.mark.asyncio
async def test_reconfirming_spine_keeps_independent_sections_and_compiled_content(tmp_path):
    storage = _storage(tmp_path)
    engine = _seed(storage)
    proposal = preview_edit(
        storage,
        "bk",
        BookEdit(
            action="add_page",
            chapter_id="ch_0",
            title="Independent section",
            body="Keep this explanation",
        ),
    )
    apply_edit(storage, "bk", proposal["id"], 1)
    section = storage.list_pages("bk")[0]
    pages = await engine.confirm_spine(book_id="bk", auto_compile=False)
    assert section.id in [p.id for p in pages]
    saved = storage.load_page("bk", section.id)
    assert saved.title == "Independent section"
    assert saved.blocks[0].payload["body"] == "Keep this explanation"
    assert storage.load_page("bk", "pg_0").blocks[0].payload["body"] == "compiled prose 0"
    assert len(storage.load_spine("bk").chapter_by_id("ch_0").page_ids) == 2
