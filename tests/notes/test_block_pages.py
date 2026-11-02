from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path

import pytest

from deeptutor.co_writer.storage import CoWriterStorage, RevisionConflict
from deeptutor.notes.blocks import blocks_to_markdown, validate_blocks
from deeptutor.notes.proposals import list_proposals, propose, review


class Paths:
    def __init__(self, root):
        self.root = root

    def get_co_writer_docs_dir(self):
        return self.root / "documents"

    def get_co_writer_doc_root(self, did):
        return self.get_co_writer_docs_dir() / f"doc_{did}"

    def get_co_writer_doc_manifest(self, did):
        return self.get_co_writer_doc_root(did) / "manifest.json"


@pytest.fixture
def store(tmp_path):
    return CoWriterStorage(Paths(tmp_path))


def block(bid="a", text="Hello"):
    return {
        "id": bid,
        "type": "paragraph",
        "props": {},
        "content": [{"type": "text", "text": text, "styles": {}}],
        "children": [],
    }


def page(store):
    return store.create_document(title="Notes", blocks=[block(), block("b", "Other")])


def test_legacy_migration_backs_up_exact_original_once(store):
    doc = store.create_document(content="Old title\n====\n【original】")
    migrated = store.update_document(doc.id, blocks=[block()], expected_revision=0)
    assert migrated.content == "Hello" and migrated.revision == 1
    backup = store.doc_root(doc.id) / "legacy.md"
    assert backup.read_text() == doc.content
    store.update_document(doc.id, blocks=[block(text="Changed")], expected_revision=1)
    assert backup.read_text() == doc.content
    with pytest.raises(RevisionConflict):
        store.update_document(doc.id, content="Stale textarea")


def test_compare_and_swap_serializes_writers(store):
    doc = page(store)

    def write(text):
        try:
            return store.update_document(doc.id, blocks=[block(text=text)], expected_revision=0)
        except RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["one", "two"]))
    assert sum(r is not None for r in results) == 1
    assert store.load_document(doc.id).revision == 1


def test_proposal_applies_after_unrelated_edit_but_rejects_changed_target(store):
    doc = page(store)
    suggestion = propose(store, doc.id, operation="replace", block_id="a", markdown="Better")
    changed = [block(), block("b", "User typed elsewhere")]
    store.update_document(doc.id, blocks=changed, expected_revision=0)
    result = review(store, doc.id, suggestion["id"], accept=True, blocks=[block("new", "Better")])
    assert "User typed elsewhere" in result.content and "Better" in result.content
    repeat = review(store, doc.id, suggestion["id"], accept=True, blocks=[block("ignored")])
    assert repeat.revision == result.revision
    suggestion = propose(store, doc.id, operation="delete", block_id="b")
    changed = copy.deepcopy(result.blocks)
    changed[1] = block("b", "New user edit")
    store.update_document(doc.id, blocks=changed, expected_revision=result.revision)
    with pytest.raises(RevisionConflict):
        review(store, doc.id, suggestion["id"], accept=True)
    assert "New user edit" in store.load_document(doc.id).content


def test_replacement_preserves_anchor_and_stale_review_cannot_overwrite_next_round(store):
    doc = page(store)
    first = propose(store, doc.id, operation="replace", block_id="a", markdown="First")
    stale = propose(store, doc.id, operation="replace", block_id="a", markdown="Stale")
    replacement = [block("generated-id", "First")]
    result = review(store, doc.id, first["id"], accept=True, blocks=replacement)
    assert [b["id"] for b in result.blocks] == ["a", "b"]
    assert replacement[0]["id"] == "generated-id"
    with pytest.raises(RevisionConflict):
        review(store, doc.id, stale["id"], accept=True, blocks=[block("old", "Stale")])
    review(store, doc.id, stale["id"], accept=False)
    second = propose(store, doc.id, operation="replace", block_id="a", markdown="Second")
    review(store, doc.id, second["id"], accept=True, blocks=[block("another-id", "Second")])
    reopened = store.load_document(doc.id)
    assert [b["id"] for b in reopened.blocks] == ["a", "b"]
    assert reopened.content == "Second\n\nOther"


def test_comment_and_dismiss_never_change_body(store):
    doc = page(store)
    comment = propose(
        store, doc.id, operation="comment", block_id="a", explanation="Check this claim"
    )
    review(store, doc.id, comment["id"], accept=True)
    suggestion = propose(store, doc.id, operation="delete", block_id="b")
    review(store, doc.id, suggestion["id"], accept=False)
    assert store.load_document(doc.id) == doc
    assert [p["status"] for p in list_proposals(store, doc.id)] == ["accepted", "dismissed"]


def test_nested_proposals_follow_ids_after_reordering_and_preserve_siblings(store):
    parent = block("parent", "Parent")
    parent["children"] = [block("child", "Child"), block("sibling", "Keep")]
    doc = store.create_document(blocks=[block("first"), parent, block("last")])
    first = propose(
        store, doc.id, operation="replace", block_id="first", blocks=[block("new", "First revised")]
    )
    child = propose(
        store, doc.id, operation="replace", block_id="child", blocks=[block("new", "Child revised")]
    )
    assert child["anchors"][:2] == [
        {"id": "sibling", "side": "before"},
        {"id": "parent", "side": "after"},
    ]
    store.update_document(
        doc.id, blocks=[parent, block("last"), block("first")], expected_revision=0
    )
    updated_first = next(p for p in list_proposals(store, doc.id) if p["id"] == first["id"])
    assert updated_first["anchors"][0] == {"id": "last", "side": "after"}
    review(store, doc.id, child["id"], accept=True)
    review(store, doc.id, first["id"], accept=True)
    reopened = store.load_document(doc.id)
    assert [b["id"] for b in reopened.blocks] == ["parent", "last", "first"]
    assert reopened.blocks[0]["children"] == [
        block("child", "Child revised"),
        block("sibling", "Keep"),
    ]
    assert reopened.blocks[2] == block("first", "First revised")


def test_removed_nested_target_is_rejected_but_can_be_reviewed_after_undo(store):
    parent = block("parent")
    parent["children"] = [block("child")]
    doc = store.create_document(blocks=[parent, block("last")])
    proposal = propose(store, doc.id, operation="delete", block_id="child")
    assert proposal["anchors"] == [
        {"id": "parent", "side": "after"},
        {"id": "last", "side": "before"},
    ]
    deleted = block("parent")
    store.update_document(doc.id, blocks=[deleted, block("last")], expected_revision=0)
    with pytest.raises(RevisionConflict):
        review(store, doc.id, proposal["id"], accept=True)
    assert list_proposals(store, doc.id)[0]["status"] == "pending"
    store.update_document(doc.id, blocks=[parent, block("last")], expected_revision=1)
    review(store, doc.id, proposal["id"], accept=True)
    assert store.load_document(doc.id).blocks == [deleted, block("last")]


def test_deleted_review_anchor_remembers_latest_order_after_reopen(store):
    doc = store.create_document(blocks=[block("a"), block("b"), block("c")])
    propose(store, doc.id, operation="replace", block_id="c", markdown="Update")
    store.update_document(doc.id, blocks=[block("c"), block("a"), block("b")], expected_revision=0)
    store.update_document(doc.id, blocks=[block("a"), block("b")], expected_revision=1)
    reopened = list_proposals(store, doc.id)[0]
    assert reopened["anchors"][0] == {"id": "a", "side": "before"}
    assert reopened["status"] == "pending"


@pytest.mark.parametrize("child_first", [True, False])
def test_text_only_parent_and_child_reviews_compose_without_losing_nested_content(
    store, child_first
):
    parent = block("parent", "Parent")
    parent["children"] = [block("child", "Child"), block("keep", "Keep")]
    doc = store.create_document(blocks=[parent, block("last", "Last")])
    parent_edit = propose(
        store,
        doc.id,
        operation="replace",
        block_id="parent",
        blocks=[block("new", "Parent revised")],
    )
    child_edit = propose(
        store, doc.id, operation="replace", block_id="child", blocks=[block("new", "Child revised")]
    )
    assert parent_edit["preserve_children"]
    for proposal in [child_edit, parent_edit] if child_first else [parent_edit, child_edit]:
        review(store, doc.id, proposal["id"], accept=True)
    reopened = store.load_document(doc.id)
    expected = block("parent", "Parent revised")
    expected["children"] = [block("child", "Child revised"), block("keep", "Keep")]
    assert reopened.blocks == [expected, block("last", "Last")]


def test_explicit_subtree_replacement_still_rejects_concurrent_child_edits(store):
    parent = block("parent")
    parent["children"] = [block("child")]
    doc = store.create_document(blocks=[parent])
    replacement = copy.deepcopy(parent)
    replacement["children"] = [block("child", "AI changed child")]
    proposal = propose(store, doc.id, operation="replace", block_id="parent", blocks=[replacement])
    assert not proposal["preserve_children"]
    parent["children"][0] = block("child", "User changed child")
    store.update_document(doc.id, blocks=[parent], expected_revision=0)
    with pytest.raises(RevisionConflict):
        review(store, doc.id, proposal["id"], accept=True)
    assert store.load_document(doc.id).blocks == [parent]


def test_page_hierarchy_prevents_cycles_and_preserves_children(store):
    root = page(store)
    child = store.create_document(parent_id=root.id)
    leaf = store.create_document(parent_id=child.id)
    with pytest.raises(ValueError):
        store.update_document(root.id, parent_id=leaf.id)
    store.delete_document(child.id)
    assert store.load_document(leaf.id).parent_id == root.id


def test_projection_keeps_nested_links_tables_and_learning_content():
    heading = block("h", "Title")
    heading.update(type="heading", props={"level": 2}, children=[block("c", "Nested")])
    link = block("l")
    link["content"] = [
        {
            "type": "link",
            "href": "https://example.com",
            "content": [{"type": "text", "text": "Source", "styles": {"bold": True}}],
        }
    ]
    table = {
        "id": "t",
        "type": "table",
        "props": {},
        "content": {"rows": [{"cells": [[{"type": "text", "text": "A", "styles": {}}]]}]},
    }
    learning = {
        "id": "quiz",
        "type": "learning",
        "props": {"markdown": "Question?", "kind": "quiz"},
    }
    md = blocks_to_markdown(validate_blocks([heading, link, table, learning]))
    assert (
        "## Title" in md
        and "  Nested" in md
        and "[**Source**](https://example.com)" in md
        and "| --- |" in md
        and "Question?" in md
    )


def test_rejects_duplicate_block_ids_and_traversal(store):
    with pytest.raises(ValueError):
        validate_blocks([block(), block()])
    with pytest.raises(ValueError):
        store.load_document("../../other")


def test_workspaces_are_independent(tmp_path):
    one = CoWriterStorage(Paths(tmp_path / "one"))
    two = CoWriterStorage(Paths(tmp_path / "two"))
    doc = page(one)
    assert two.load_document(doc.id) is None
    with pytest.raises(ValueError):
        propose(two, doc.id, operation="insert", markdown="x")


def test_rich_blocks_round_trip_and_readable_projection(tmp_path):
    from deeptutor.notes.blocks import blocks_to_markdown, validate_blocks

    rich = [
        {
            "id": "columns",
            "type": "noteColumns",
            "children": [
                {
                    "id": "left",
                    "type": "noteColumn",
                    "children": [{"id": "tip", "type": "callout", "content": "Key idea"}],
                },
                {
                    "id": "right",
                    "type": "noteColumn",
                    "children": [
                        {
                            "id": "fold",
                            "type": "toggleHeading",
                            "props": {"level": 2, "collapsed": True},
                            "content": "Details",
                            "children": [
                                {"id": "body", "type": "paragraph", "content": "Still exported"}
                            ],
                        }
                    ],
                },
            ],
        },
        {
            "id": "link",
            "type": "webCard",
            "props": {"url": "https://example.org", "title": "Reference"},
        },
        {"id": "html", "type": "htmlEmbed", "props": {"source": "<h2>Example</h2>"}},
        {"id": "toc", "type": "tableOfContents"},
    ]
    validate_blocks(rich)
    text = blocks_to_markdown(rich)
    assert "> Key idea" in text and "## Details" in text and "Still exported" in text
    assert "[Reference](https://example.org)" in text and "```html" in text
    store = CoWriterStorage(Paths(tmp_path))
    page = store.create_document(blocks=rich)
    assert store.load_document(page.id).blocks == rich
    with pytest.raises(ValueError):
        validate_blocks([{"id": "bad", "type": "webCard", "props": {"url": "javascript:alert(1)"}}])


def test_clip_into_empty_page_stays_a_source_block_after_reopen(store, monkeypatch):
    import asyncio

    from deeptutor.api.routers import co_writer

    monkeypatch.setattr(co_writer, "get_co_writer_storage", lambda: store)
    doc = store.create_document(title="Favorite")
    asyncio.run(
        co_writer.append_note_clip(
            doc.id,
            co_writer.ClipRequest(
                title="Original",
                markdown="**Source**",
                source_url="/notebooks/inbox?record=r1",
                source_id="r1",
                favorite_type="video_learning",
                summary="Saved summary",
                favorite_metadata={"video_url": "/clip.mp4"},
            ),
        )
    )
    reopened = store.load_document(doc.id)
    assert len(reopened.blocks) == 1
    assert reopened.blocks[0]["type"] == "clip"
    assert reopened.blocks[0]["props"]["markdown"] == "**Source**"
    assert reopened.blocks[0]["props"]["sourceUrl"] == "/notebooks/inbox?record=r1"

    assert reopened.blocks[0]["props"]["favoriteType"] == "video_learning"
    assert reopened.blocks[0]["props"]["summary"] == "Saved summary"
    assert reopened.blocks[0]["props"]["expanded"] is False
    assert __import__("json").loads(reopened.blocks[0]["props"]["metadata"]) == {
        "video_url": "/clip.mp4"
    }


def test_cards_drop_stray_text_and_tell_the_model_what_they_hold():
    from deeptutor.notes.threads import card_content

    timeline = {
        "id": "t",
        "type": "learning",
        # A model echoing the kind as content; the editor rejects such a page.
        "content": "timeline",
        "props": {
            "kind": "timeline",
            "prompt": "Photosynthesis",
            "markdown": "",
            "data": '{"events": [{"date": "1771", "title": "Priestley", "description": "Mint"}]}',
        },
        "children": [],
    }
    validate_blocks([timeline])
    assert "content" not in timeline
    assert "1771 — Priestley" in card_content(timeline)
    assert card_content(block()) == ""
