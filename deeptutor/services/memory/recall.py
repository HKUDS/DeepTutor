"""Reading memory back — what the learner has been doing lately.

L1 keeps two kinds of record, and answering "what happened lately" needs both:

* the **snapshot** knows what *exists* — every chat session, notebook record,
  quiz attempt, document, book and knowledge base, each with a label and a
  timestamp. :func:`recent` reads that.
* the **trace** knows what was *done* — the events surfaces emit as they run.
  :func:`recent_queries` reads the one kind that records the learner asking
  something in their own words.

Both run on stamps: no message body, no document text, no answer is read. That
is what makes them safe to call from an interactive path rather than only from
consolidation, which is the whole reason this module exists separately from
:mod:`deeptutor.services.memory.store`.

Every hit carries ``days_ago`` rather than leaving an ISO timestamp for the
caller to subtract. A model asked to do date arithmetic on
``2026-08-16T11:03:00+00:00`` will sometimes get it wrong, and "how long ago"
is the entire basis on which anything decides whether an item is still worth
raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Iterable

from deeptutor.services.memory.paths import SURFACES, Surface

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
# A week: long enough to survive a couple of quiet days, short enough that what
# comes back is still recognisably "lately".
_DEFAULT_DAYS = 7
# A label is a title, a question or a filename. Anything longer is a body that
# leaked into one, and carrying it would defeat the point of stamps-only reads.
_MAX_LABEL_CHARS = 200


@dataclass(frozen=True, slots=True)
class RecallHit:
    """One thing the learner touched, shaped for a caller to act on."""

    surface: str
    label: str
    ts: str
    days_ago: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "label": self.label,
            "ts": self.ts,
            "days_ago": self.days_ago,
        }


# ── Time ─────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_ago(ts: str, *, now: datetime | None = None) -> int | None:
    """Whole days between ``ts`` and now, or ``None`` for an unusable stamp."""
    parsed = _parse_ts(ts)
    if parsed is None:
        return None
    delta = (now or _now()) - parsed
    # A future stamp (clock skew on an imported record) reads as today rather
    # than as a negative age.
    return max(0, delta.days)


def _cutoff(days: int | None, now: datetime) -> datetime | None:
    if days is None or days < 0:
        return None
    return now - timedelta(days=days)


# ── Shaping ──────────────────────────────────────────────────────────────


def _clean_label(raw: str) -> str:
    """One line, bounded. Empty when there is nothing worth showing."""
    text = " ".join(str(raw or "").split())
    return text[:_MAX_LABEL_CHARS]


def _resolve_surfaces(surfaces: Iterable[str] | None) -> tuple[Surface, ...]:
    if not surfaces:
        return SURFACES
    wanted = {str(surface).strip().lower() for surface in surfaces}
    resolved = tuple(surface for surface in SURFACES if surface in wanted)
    return resolved or SURFACES


def _clamp_limit(limit: int | None) -> int:
    if not limit or limit < 1:
        return _DEFAULT_LIMIT
    return min(int(limit), _MAX_LIMIT)


def _newest_first(hits: list[RecallHit]) -> list[RecallHit]:
    """Sort newest first, dropping repeats of the same label on the same surface.

    A knowledge base queried five times, or a session reopened all afternoon,
    is one thing the learner is working on — not five. Keeping the duplicates
    would let a single topic crowd out everything else downstream.
    """
    hits.sort(key=lambda hit: hit.ts, reverse=True)
    seen: set[tuple[str, str]] = set()
    deduped: list[RecallHit] = []
    for hit in hits:
        key = (hit.surface, hit.label.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


# ── What exists (snapshot) ───────────────────────────────────────────────


def recent(
    *,
    days: int | None = _DEFAULT_DAYS,
    limit: int | None = _DEFAULT_LIMIT,
    surfaces: Iterable[str] | None = None,
) -> list[RecallHit]:
    """The latest workspace activity across surfaces, newest first.

    Stamps only — no content is read, so this stays cheap enough to call on a
    page load.

    Items without a usable timestamp are dropped rather than kept: placing an
    item of unknown age inside "the last seven days" asserts something the data
    does not support. This notably excludes knowledge bases, whose snapshot
    timestamp is their *earliest* index time — a KB in daily use would look
    stale here. What the learner has actually been asking a KB lives in the
    trace instead; see :func:`recent_queries`.
    """
    from deeptutor.services.memory.snapshot import adapters

    now = _now()
    cutoff = _cutoff(days, now)
    hits: list[RecallHit] = []
    for surface in _resolve_surfaces(surfaces):
        try:
            stamps = adapters.read_stamps(surface)
        except Exception:
            logger.warning("recall.recent: stamps failed surface=%s", surface, exc_info=True)
            continue
        for stamp in stamps:
            parsed = _parse_ts(stamp.ts)
            if parsed is None or (cutoff is not None and parsed < cutoff):
                continue
            label = _clean_label(stamp.label)
            if not label:
                continue
            hits.append(
                RecallHit(
                    surface=surface,
                    label=label,
                    ts=stamp.ts,
                    days_ago=days_ago(stamp.ts, now=now),
                )
            )
    return _newest_first(hits)[: _clamp_limit(limit)]


# ── What was asked (trace) ───────────────────────────────────────────────

# The trace kinds that carry a learner-authored question. Knowledge-base
# queries are the only ones today: the other emitters record system-side facts
# (a stated preference, a partner turn), not something the learner typed as a
# question.
_QUERY_KINDS: dict[Surface, str] = {"kb": "query"}


def recent_queries(
    *,
    days: int | None = _DEFAULT_DAYS,
    limit: int | None = _DEFAULT_LIMIT,
) -> list[RecallHit]:
    """Searches the learner ran lately, in their own words, newest first.

    Complements :func:`recent`: the snapshot can say a knowledge base exists,
    but only the trace records that someone asked it about eigenvalues on
    Tuesday.
    """
    from deeptutor.services.memory import trace

    now = _now()
    cutoff = _cutoff(days, now)
    hits: list[RecallHit] = []
    for surface, kind in _QUERY_KINDS.items():
        try:
            events = trace.iter_since(surface, cutoff)
        except Exception:
            logger.warning("recall.recent_queries: failed surface=%s", surface, exc_info=True)
            continue
        for event in events:
            if event.kind != kind:
                continue
            label = _clean_label(str((event.payload or {}).get("query") or ""))
            if not label:
                continue
            hits.append(
                RecallHit(
                    surface=surface,
                    label=label,
                    ts=event.ts,
                    days_ago=days_ago(event.ts, now=now),
                )
            )
    return _newest_first(hits)[: _clamp_limit(limit)]


__all__ = ["RecallHit", "days_ago", "recent", "recent_queries"]
