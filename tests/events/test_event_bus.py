"""EventBus singleton reset semantics."""

from __future__ import annotations

from deeptutor.events.event_bus import EventBus, get_event_bus


def test_reset_clears_the_module_level_accessor() -> None:
    # get_event_bus caches its own module-level singleton; reset() must clear it
    # too, or the accessor keeps handing back a stopped bus after a reset.
    first = get_event_bus()
    try:
        EventBus.reset()
        assert get_event_bus() is not first
    finally:
        EventBus.reset()
