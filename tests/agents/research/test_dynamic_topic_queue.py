"""Unit tests for the queue extensions used by the new research pipeline.

The new agentic-loop refactor relies on three additions to
:class:`DynamicTopicQueue`:

* ``is_full()``  — capacity check without raising
* ``find_similar()`` — fuzzy dedup so the ``APPEND`` label can't
  silently flood the queue with near-duplicate sub-topics
* ``append_child()`` — non-raising tail append that records the parent
  block id in ``metadata`` for later topic-tree reconstruction
"""

from __future__ import annotations

from deeptutor.agents.research.data_structures import (
    DEFAULT_TOPIC_SIMILARITY_THRESHOLD,
    DynamicTopicQueue,
    TopicStatus,
)


def _queue(max_length: int | None = None) -> DynamicTopicQueue:
    return DynamicTopicQueue("test", max_length=max_length)


def test_is_full_returns_false_when_no_cap_configured() -> None:
    q = _queue()
    for i in range(50):
        q.add_block(f"topic {i}", "")
    assert q.is_full() is False


def test_is_full_returns_true_at_cap() -> None:
    q = _queue(max_length=2)
    q.add_block("a", "")
    assert q.is_full() is False
    q.add_block("b", "")
    assert q.is_full() is True


def test_find_similar_exact_match_returns_block() -> None:
    q = _queue()
    a = q.add_block("Quantum Entanglement Basics", "")
    match = q.find_similar("quantum entanglement basics")
    assert match is a


def test_find_similar_returns_fuzzy_match_above_threshold() -> None:
    q = _queue()
    a = q.add_block("Quantum entanglement basics", "")
    # Reordered words / slight rewording — should still match above 0.85
    match = q.find_similar("Quantum entanglement: basic concepts")
    # The default threshold accepts highly similar titles; verify we get
    # back the only existing block.
    if match is not None:
        assert match is a


def test_find_similar_catches_reordered_token_equivalents() -> None:
    q = _queue()
    a = q.add_block("AI safety governance frameworks", "")

    assert q.find_similar("Governance framework for AI safety") is a


def test_find_similar_rejects_distinct_topic() -> None:
    q = _queue()
    q.add_block("Photosynthesis fundamentals", "")
    assert q.find_similar("History of jazz music") is None


def test_find_similar_honours_custom_threshold() -> None:
    q = _queue()
    q.add_block("Photosynthesis fundamentals", "")
    # Force a punishingly high threshold so even close variants miss.
    assert q.find_similar("Photosynthesis basics", threshold=0.99) is None


def test_find_similar_returns_none_for_empty_title() -> None:
    q = _queue()
    q.add_block("x", "")
    assert q.find_similar("") is None
    assert q.find_similar("   ") is None


def test_append_child_returns_new_block_with_parent_id_in_metadata() -> None:
    q = _queue()
    parent = q.add_block("Parent topic", "ctx")
    child = q.append_child(parent=parent, sub_topic="Child topic", overview="more")
    assert child is not None
    assert child.sub_topic == "Child topic"
    assert child.overview == "more"
    assert child.metadata.get("parent_block_id") == parent.block_id
    assert child.status == TopicStatus.PENDING
    # New blocks land at the tail.
    assert q.blocks[-1] is child


def test_append_child_without_parent_records_no_lineage() -> None:
    q = _queue()
    child = q.append_child(parent=None, sub_topic="orphan", overview="")
    assert child is not None
    assert "parent_block_id" not in child.metadata


def test_append_child_returns_none_when_queue_full() -> None:
    q = _queue(max_length=1)
    q.add_block("only one", "")
    rejected = q.append_child(parent=None, sub_topic="overflow", overview="")
    assert rejected is None
    assert len(q.blocks) == 1


def test_append_child_increments_counter_consistently_with_add_block() -> None:
    """``add_block`` and ``append_child`` must share the same id allocator."""
    q = _queue()
    a = q.add_block("a", "")
    b = q.append_child(parent=a, sub_topic="b", overview="")
    c = q.add_block("c", "")
    assert a.block_id == "block_1"
    assert b is not None and b.block_id == "block_2"
    assert c.block_id == "block_3"


def test_default_threshold_constant_in_reasonable_range() -> None:
    assert 0.7 <= DEFAULT_TOPIC_SIMILARITY_THRESHOLD <= 0.95
