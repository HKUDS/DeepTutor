from __future__ import annotations

import asyncio

import pytest

from deeptutor.learning.event_hub import MasteryTopicEventHub


@pytest.mark.asyncio
async def test_topic_hub_wakes_an_event_loop_from_a_worker_thread() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("topic-one")
    try:
        await asyncio.to_thread(hub.publish, "topic-one", 7, "mastery.updated")
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.path_id == "topic-one"
    assert signal.revision == 7
    assert signal.reason == "mastery.updated"


@pytest.mark.asyncio
async def test_topic_hub_isolated_by_path_and_unsubscribes_cleanly() -> None:
    hub = MasteryTopicEventHub()
    first = hub.subscribe("first")
    second = hub.subscribe("second")
    first.close()

    hub.publish("first", 1)
    hub.publish("second", 2, "session.bound")

    signal = await asyncio.wait_for(second.get(), timeout=1)
    second.close()
    assert signal.path_id == "second"
    assert signal.sequence >= 1
    assert first.queue.empty()


@pytest.mark.asyncio
async def test_topic_hub_isolated_by_workspace_scope() -> None:
    hub = MasteryTopicEventHub()
    first = hub.subscribe("shared", scope="workspace-a")
    second = hub.subscribe("shared", scope="workspace-b")
    try:
        hub.publish("shared", 3, scope="workspace-a")
        signal = await asyncio.wait_for(first.get(), timeout=1)
    finally:
        first.close()
        second.close()

    assert signal.revision == 3
    assert second.queue.empty()


@pytest.mark.asyncio
async def test_topic_hub_coalesces_slow_subscriber_to_latest_signal() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("topic-one")
    try:
        for revision in range(1, 51):
            hub.publish("topic-one", revision)
        await asyncio.sleep(0)
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.revision == 50
    assert subscription.queue.empty()
