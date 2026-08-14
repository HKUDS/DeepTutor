from __future__ import annotations

import pytest

from deeptutor.services.keypool import KeyPool


def test_keypool_rotates_in_round_robin_order() -> None:
    pool = KeyPool(["key-a", "key-b", "key-c"])

    assert [pool.next() for _ in range(5)] == [
        "key-a",
        "key-b",
        "key-c",
        "key-a",
        "key-b",
    ]


def test_keypool_cools_key_after_two_429s_and_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import keypool as keypool_module

    now = {"value": 100.0}
    monkeypatch.setattr(keypool_module, "monotonic", lambda: now["value"])
    pool = KeyPool(["key-a", "key-b"], cooldown_s=60)

    assert pool.next() == "key-a"
    pool.mark_429("key-a")
    pool.mark_429("key-a")
    assert [pool.next(), pool.next()] == ["key-b", "key-b"]

    now["value"] = 161.0
    assert pool.next() == "key-a"


def test_keypool_keeps_single_key_compatible_until_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import keypool as keypool_module

    now = {"value": 10.0}
    monkeypatch.setattr(keypool_module, "monotonic", lambda: now["value"])
    pool = KeyPool(["only-key"], cooldown_s=5)

    assert pool.next() == "only-key"
    pool.mark_429("only-key")
    assert pool.next() == "only-key"
    pool.mark_429("only-key")
    with pytest.raises(RuntimeError, match="cooling down"):
        pool.next()

    now["value"] = 16.0
    assert pool.next() == "only-key"
