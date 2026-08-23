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


def test_keypool_still_serves_a_single_cooling_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-key setup must never be refused service.

    Cooling is only useful as a hint about which key to prefer. With one key
    there is nothing to prefer, so refusing to hand it out would turn a
    retryable provider 429 into a hard failure for every LLM and embedding
    call until the cooldown expires.
    """
    from deeptutor.services import keypool as keypool_module

    now = {"value": 10.0}
    monkeypatch.setattr(keypool_module, "monotonic", lambda: now["value"])
    pool = KeyPool(["only-key"], cooldown_s=5)

    assert pool.next() == "only-key"
    pool.mark_429("only-key")
    assert pool.next() == "only-key"
    pool.mark_429("only-key")
    assert pool.next() == "only-key"

    now["value"] = 16.0
    assert pool.next() == "only-key"


def test_keypool_prefers_the_soonest_recovering_key_when_all_are_cooling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import keypool as keypool_module

    now = {"value": 0.0}
    monkeypatch.setattr(keypool_module, "monotonic", lambda: now["value"])
    pool = KeyPool(["key-a", "key-b"], cooldown_s=60)

    # key-a cools at t=0 (until 60), key-b at t=10 (until 70).
    pool.mark_429("key-a")
    pool.mark_429("key-a")
    now["value"] = 10.0
    pool.mark_429("key-b")
    pool.mark_429("key-b")

    now["value"] = 20.0
    assert pool.next() == "key-a"
