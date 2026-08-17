"""
Book event hub
==============

One long-lived event stream **per book**, owned by the process rather than by
whichever request happened to start the work.

Why this exists
---------------

The Book Engine's unit of work is a *book*, not a request: ``confirm_spine``
returns as soon as the page shells exist, while the compilation it queued keeps
running for minutes afterwards. A bus that is created per request and closed in
the router's ``finally`` therefore drops every background event on the floor —
``StreamBus.emit()`` silently no-ops once the bus is closed, so the whole
"watch your book being written" experience degrades into a frozen page.

The hub inverts the ownership:

- **Producers** (engine, compiler, background worker) publish into
  ``get_book_bus(book_id)``. They never create or close a bus.
- **Consumers** (WebSocket clients) subscribe to that same bus and may come and
  go freely. ``StreamBus.subscribe()`` replays recent history, so a client that
  reconnects mid-compilation catches up instead of waiting for the next event.
- A bus is closed exactly once — when the book is deleted.

Because REST handlers publish into the same place as WebSocket handlers, a book
compiled via REST still streams to anyone watching over WebSocket.
"""

from __future__ import annotations

from deeptutor.core.stream_bus import StreamBus

from .streaming import BookStream

# Enough to replay the tail of an in-flight stage to a reconnecting client
# (a page emits ~2 events per block), without pinning a whole book's event
# log in memory for the lifetime of the process.
BOOK_EVENT_HISTORY_LIMIT = 400

_buses: dict[str, StreamBus] = {}


def get_book_bus(book_id: str) -> StreamBus:
    """Return the long-lived bus for *book_id*, creating it on first use.

    Safe to call from any coroutine: there is no ``await`` between the lookup
    and the insert, so concurrent callers cannot race into two buses.
    """
    bus = _buses.get(book_id)
    if bus is None:
        bus = StreamBus(max_history=BOOK_EVENT_HISTORY_LIMIT)
        _buses[book_id] = bus
    return bus


def get_book_stream(book_id: str) -> BookStream:
    """``get_book_bus`` wrapped in the Book-specific emit helpers."""
    return BookStream(get_book_bus(book_id))


def close_book_bus(book_id: str) -> None:
    """Close and forget the bus for *book_id* (called when a book is deleted).

    Synchronous on purpose — book deletion runs from sync engine and CLI paths.
    """
    bus = _buses.pop(book_id, None)
    if bus is not None:
        bus.mark_closed()


__all__ = [
    "BOOK_EVENT_HISTORY_LIMIT",
    "get_book_bus",
    "get_book_stream",
    "close_book_bus",
]
