"""
PocketBase-backed session store.

Implements SessionStoreProtocol using PocketBase collections for all durable
storage.  The key performance design:

- Most methods make direct PocketBase HTTP calls. These are called at most a
  handful of times per turn (create, get, update status, add message) and the
  ~5–10 ms overhead is acceptable.

- Turn events are flushed before a terminal status is committed.  This makes
  the PocketBase and SQLite backends share one durability contract: DONE never
  races a detached upload task and shutdown cannot silently lose trace rows.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import json
import logging
import re
import time
from typing import Any
import uuid

from .ask_user_trace import filter_ask_user_events
from .event_preview import MAX_TRACE_PREVIEW_EVENTS, compact_trace_preview
from .provider_response_state import redact_private_message_metadata
from .scope import StoreScope
from .workspace_preferences import upgrade_workspace_preferences

logger = logging.getLogger(__name__)

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_ACTIVE_TURN_STATUSES = frozenset({"queued", "running", "waiting_input"})
_TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled"})
_ALL_TURN_STATUSES = _ACTIVE_TURN_STATUSES | _TERMINAL_TURN_STATUSES


def _validate_id(value: str, name: str = "id") -> str:
    if not _VALID_ID.match(value):
        raise ValueError(f"Invalid {name}: {value!r}")
    return value


def _json_loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _pb():
    """Return the shared PocketBase client."""
    from deeptutor.services.pocketbase_client import get_pb_client

    return get_pb_client()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        return default


def _current_user_id() -> str:
    """Id of the request-scoped current user, used to isolate session rows.

    PocketBase is a single shared server queried by one process-wide
    admin-authenticated client, so it has no filesystem-level isolation. Every
    session row is therefore scoped by ``user_id`` (the SQLite backend isolates
    via a per-user database file instead — see ``get_sqlite_session_store``).
    This reads the same ``_current_user`` ContextVar that the SQLite path
    service resolves against, so the two backends share one source of truth and
    are equally reliable across HTTP, WebSocket, and turn-runtime threads. Falls
    back to the local-admin id in single-user / no-auth mode.

    The id is validated (it always matches ``_VALID_ID`` for real users — a
    PocketBase record id, a ``u_<hex>`` id, or ``local-admin``) so it is safe to
    interpolate into a PocketBase filter string.
    """
    from deeptutor.multi_user.context import get_current_user

    return _validate_id(get_current_user().id, "user_id")


def _find_session_record(pb: Any, session_id: str, user_id: str) -> Any | None:
    """Return the ``sessions`` record for *session_id* owned by *user_id*.

    Scoping every session lookup by ``user_id`` is the single point that keeps
    one user from reading or mutating another's sessions on the shared
    PocketBase backend. Returns ``None`` when no such row exists for this user.
    """
    records = pb.collection("sessions").get_full_list(
        query_params={"filter": f'session_id="{session_id}" && user_id="{user_id}"'}
    )
    return records[0] if records else None


class PocketBaseSessionStore:
    """PocketBase-backed implementation of SessionStoreProtocol."""

    def __init__(self) -> None:
        self._closed = False
        self.store_scope: StoreScope | None = None

    async def close(self) -> None:
        """Prevent lifecycle owners from retaining an already-closed store."""
        self._closed = True

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def migrate_workspace_preferences(self) -> int:
        """Persist canonical workspace metadata for the current PocketBase user.

        The explicit logical timestamps keep this metadata-only migration from
        changing conversation order even though PocketBase updates its own
        system ``updated`` field whenever a record is written.
        """

        uid = _current_user_id()

        def _migrate() -> int:
            collection = _pb().collection("sessions")
            records = collection.get_full_list(query_params={"filter": f'user_id="{uid}"'})
            records.sort(
                key=lambda record: (
                    _to_float(getattr(record, "session_updated_at", None))
                    or _to_float(getattr(record, "updated", None))
                )
            )
            migrated = 0
            for record in records:
                current = _json_loads(getattr(record, "preferences_json", None), {})
                upgraded = upgrade_workspace_preferences(current)
                created_at = (
                    _to_float(getattr(record, "session_created_at", None))
                    or _to_float(getattr(record, "created", None))
                    or time.time()
                )
                updated_at = (
                    _to_float(getattr(record, "session_updated_at", None))
                    or _to_float(getattr(record, "updated", None))
                    or created_at
                )
                payload: dict[str, Any] = {}
                if upgraded != current:
                    payload["preferences_json"] = upgraded
                    migrated += 1
                if not _to_float(getattr(record, "session_created_at", None)):
                    payload["session_created_at"] = created_at
                if not _to_float(getattr(record, "session_updated_at", None)):
                    payload["session_updated_at"] = updated_at
                if payload:
                    collection.update(record.id, payload)
            return migrated

        return await asyncio.to_thread(_migrate)

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        resolved_id = session_id or f"unified_{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        resolved_title = (title or "New conversation").strip() or "New conversation"
        owner_id = _current_user_id()

        def _create():
            return (
                _pb()
                .collection("sessions")
                .create(
                    {
                        "session_id": resolved_id,
                        "user_id": owner_id,
                        "title": resolved_title[:100],
                        "compressed_summary": "",
                        "summary_up_to_msg_id": 0,
                        "preferences_json": {},
                        "capability": "",
                        "status": "idle",
                        "session_created_at": now,
                        "session_updated_at": now,
                    }
                )
            )

        record = await asyncio.to_thread(_create)
        return self._session_record_to_dict(record, resolved_id, resolved_title, now)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()

        def _get():
            try:
                return _find_session_record(_pb(), sid, uid)
            except Exception:
                return None

        record = await asyncio.to_thread(_get)
        if record is None:
            return None
        return self._session_record_to_dict(record)

    async def ensure_session(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session()

    def _session_record_to_dict(
        self,
        record: Any,
        session_id: str | None = None,
        title: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        sid = session_id or getattr(record, "session_id", getattr(record, "id", ""))
        t = title or getattr(record, "title", "New conversation") or "New conversation"
        created = (
            _to_float(getattr(record, "session_created_at", None))
            or _to_float(getattr(record, "created", None))
            or now
            or time.time()
        )
        updated = (
            _to_float(getattr(record, "session_updated_at", None))
            or _to_float(getattr(record, "updated", None))
            or now
            or time.time()
        )
        preferences_raw = getattr(record, "preferences_json", None)
        return {
            "id": sid,
            "session_id": sid,
            "title": t,
            "created_at": created,
            "updated_at": updated,
            "compressed_summary": getattr(record, "compressed_summary", "") or "",
            "summary_up_to_msg_id": int(getattr(record, "summary_up_to_msg_id", 0) or 0),
            # PocketBase has no local schema-upgrade hook. Normalize at the
            # repository boundary so old remote rows immediately satisfy the
            # same API contract; their next preference write persists it.
            "preferences": upgrade_workspace_preferences(_json_loads(preferences_raw, {})),
            "capability": getattr(record, "capability", "") or "",
            "status": getattr(record, "status", "idle") or "idle",
            "active_turn_id": "",
        }

    async def update_session_title(self, session_id: str, title: str) -> bool:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()

        def _update():
            record = _find_session_record(_pb(), sid, uid)
            if record is None:
                return False
            _pb().collection("sessions").update(
                record.id,
                {
                    "title": (title.strip() or "New conversation")[:100],
                    "session_updated_at": time.time(),
                },
            )
            return True

        try:
            return await asyncio.to_thread(_update)
        except Exception as exc:
            logger.warning(f"update_session_title failed: {exc}")
            return False

    async def import_legacy_session(
        self,
        session_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        preferences: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Atomically-as-possible import one v1 chat into PocketBase.

        PocketBase has no cross-collection transaction in the Python client,
        so a failed import explicitly removes every row it created before the
        error is re-raised. Existing sessions are never updated.
        """

        sid = _validate_id(session_id, "session_id")
        owner_id = _current_user_id()

        def _import() -> dict[str, Any]:
            if _find_session_record(_pb(), sid, owner_id) is not None:
                return {"session_id": sid, "imported": False, "message_count": 0}
            session_record = None
            created_message_ids: list[str] = []
            try:
                session_record = (
                    _pb()
                    .collection("sessions")
                    .create(
                        {
                            "session_id": sid,
                            "user_id": owner_id,
                            "title": (title or "New conversation")[:100],
                            "compressed_summary": "",
                            "summary_up_to_msg_id": 0,
                            "preferences_json": preferences or {},
                            "capability": "chat",
                            "status": "idle",
                            "session_created_at": float(created_at),
                            "session_updated_at": float(updated_at),
                        }
                    )
                )
                for message in messages:
                    record = (
                        _pb()
                        .collection("messages")
                        .create(
                            {
                                "session_id": sid,
                                "role": str(message.get("role") or "user"),
                                "content": str(message.get("content") or ""),
                                "capability": "chat",
                                "events_json": [],
                                "attachments_json": [],
                                "metadata_json": message.get("metadata") or {},
                                "msg_created_at": float(message.get("created_at") or created_at),
                            }
                        )
                    )
                    created_message_ids.append(str(record.id))
            except Exception:
                for message_id in reversed(created_message_ids):
                    with contextlib.suppress(Exception):
                        _pb().collection("messages").delete(message_id)
                if session_record is not None:
                    with contextlib.suppress(Exception):
                        _pb().collection("sessions").delete(str(session_record.id))
                raise
            return {
                "session_id": sid,
                "imported": True,
                "message_count": len(created_message_ids),
            }

        return await asyncio.to_thread(_import)

    async def delete_session(self, session_id: str) -> bool:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()

        def _delete():
            record = _find_session_record(_pb(), sid, uid)
            if record is None:
                return False
            _pb().collection("sessions").delete(record.id)
            return True

        try:
            return await asyncio.to_thread(_delete)
        except Exception as exc:
            logger.warning(f"delete_session failed: {exc}")
            return False

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        page = (offset // limit) + 1
        uid = _current_user_id()

        def _list():
            query_params: dict[str, Any] = {
                "sort": "-session_updated_at",
                "filter": f'user_id="{uid}"',
            }
            return _pb().collection("sessions").get_list(page, limit, query_params=query_params)

        try:
            result = await asyncio.to_thread(_list)
            # Reading conversations are listed like any other: the sidebar
            # groups them under their collection and a click returns to the
            # reader. See the note on ``_WHERE_NATIVE`` in the SQLite store.
            return [self._session_record_to_dict(r) for r in result.items]
        except Exception as exc:
            logger.warning(f"list_sessions failed: {exc}")
            return []

    async def get_session_summaries(
        self,
        session_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return bounded metadata without loading complete chat transcripts."""

        async def summarize(session_id: str) -> dict[str, Any] | None:
            session = await self.get_session(session_id)
            if session is None:
                return None
            message_summary, active_turn = await asyncio.gather(
                self._get_message_summary(session_id),
                self.get_active_turn(session_id),
            )
            session.update(message_summary)
            if active_turn is not None:
                session["status"] = active_turn.get("status") or "running"
                session["active_turn_id"] = active_turn.get("id") or ""
            return session

        summaries = await asyncio.gather(
            *(summarize(session_id) for session_id in dict.fromkeys(session_ids))
        )
        return [summary for summary in summaries if summary is not None]

    async def _get_message_summary(self, session_id: str) -> dict[str, Any]:
        """Fetch one preview row plus PocketBase's aggregate count."""

        sid = _validate_id(session_id, "session_id")

        def _get() -> dict[str, Any]:
            result = (
                _pb()
                .collection("messages")
                .get_list(
                    1,
                    1,
                    query_params={
                        "filter": f'session_id="{sid}" && role!="system"',
                        "sort": "-msg_created_at",
                    },
                )
            )
            total = getattr(result, "total_items", getattr(result, "totalItems", None))
            items = list(getattr(result, "items", ()) or ())
            preview = self._message_record_to_dict(items[0]) if items else None
            return {
                "message_count": max(0, int(total if total is not None else len(items))),
                "last_message": str((preview or {}).get("content") or ""),
            }

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            logger.warning(f"get message summary failed: {exc}")
            return {"message_count": 0, "last_message": ""}

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()

        def _update():
            record = _find_session_record(_pb(), sid, uid)
            if record is None:
                return False
            _pb().collection("sessions").update(
                record.id,
                {
                    "compressed_summary": summary,
                    "summary_up_to_msg_id": max(0, int(up_to_msg_id)),
                },
            )
            return True

        try:
            return await asyncio.to_thread(_update)
        except Exception as exc:
            logger.warning(f"update_summary failed: {exc}")
            return False

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        sid = _validate_id(session_id, "session_id")

        async def _merge():
            session = await self.get_session(sid)
            if session is None:
                return False
            merged = upgrade_workspace_preferences(
                {**session.get("preferences", {}), **(preferences or {})}
            )
            uid = _current_user_id()

            def _update():
                record = _find_session_record(_pb(), sid, uid)
                if record is None:
                    return False
                _pb().collection("sessions").update(
                    record.id,
                    {"preferences_json": merged, "session_updated_at": time.time()},
                )
                return True

            return await asyncio.to_thread(_update)

        try:
            return await _merge()
        except Exception as exc:
            logger.warning(f"update_session_preferences failed: {exc}")
            return False

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        redact_private_message_metadata(session["messages"])
        session["active_turns"] = await self.list_active_turns(session_id)
        return session

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    # Messages/turns/turn_events are keyed by ``session_id`` and are reached
    # from the API only through a session lookup that is already user-scoped
    # (``get_session_with_messages`` returns ``None`` for another user's
    # session before any message is fetched, and ``create_turn`` rejects a
    # session the caller doesn't own). Internal callers always operate on the
    # current user's own session, so these rows don't carry a separate
    # ``user_id`` filter — the session boundary above is the access gate.

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None = None,
    ) -> int | str:
        # ``parent_message_id`` is accepted to match the protocol shape but is
        # not yet wired through PocketBase storage — branching only works on
        # the SQLite backend today.
        _ = parent_message_id
        sid = _validate_id(session_id, "session_id")
        now = time.time()

        def _add():
            payload = {
                "session_id": sid,
                "role": role,
                "content": content or "",
                "capability": capability or "",
                "events_json": events or [],
                "attachments_json": attachments or [],
                "metadata_json": metadata or {},
                "msg_created_at": now,
            }
            record = _pb().collection("messages").create(payload)
            uid = _current_user_id()
            session_record = _find_session_record(_pb(), sid, uid)
            if session_record is not None:
                _pb().collection("sessions").update(session_record.id, {"session_updated_at": now})
            # Title generation is owned by the turn runtime (LLM-driven
            # after the first user+assistant pair). Until that runs the
            # session keeps the ``New conversation`` sentinel.
            return record

        try:
            record = await asyncio.to_thread(_add)
            # Return the real PocketBase record id — the same id
            # ``get_messages`` serves — so callers (e.g. the DONE-event
            # reconcile metadata) hand the frontend ids that match what a
            # later session fetch would return.
            return str(getattr(record, "id", "") or "")
        except Exception as exc:
            logger.warning(f"add_message failed: {exc}")
            return 0

    async def delete_message(self, message_id: int | str) -> bool:
        def _delete():
            _pb().collection("messages").delete(str(message_id))
            return True

        try:
            return await asyncio.to_thread(_delete)
        except Exception as exc:
            logger.warning(f"delete_message failed: {exc}")
            return False

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        sid = _validate_id(session_id, "session_id")
        filter_str = f'session_id="{sid}"'
        if role:
            filter_str += f' && role="{role}"'

        def _get():
            records = (
                _pb()
                .collection("messages")
                .get_full_list(
                    query_params={
                        "filter": filter_str,
                        "sort": "-msg_created_at",
                        "perPage": 1,
                    }
                )
            )
            return records[0] if records else None

        try:
            record = await asyncio.to_thread(_get)
            return self._message_record_to_dict(record) if record is not None else None
        except Exception as exc:
            logger.warning(f"get_last_message failed: {exc}")
            return None

    @staticmethod
    def _event_record_to_payload(row: Any, session_id: str, turn_id: str) -> dict[str, Any]:
        return {
            "type": getattr(row, "type", ""),
            "source": getattr(row, "source", "") or "",
            "stage": getattr(row, "stage", "") or "",
            "content": getattr(row, "content", "") or "",
            "metadata": _json_loads(getattr(row, "metadata_json", None), {}),
            "session_id": session_id,
            "turn_id": turn_id,
            "seq": int(getattr(row, "seq", 0) or 0),
            "timestamp": _to_float(getattr(row, "event_timestamp", None)),
        }

    @staticmethod
    def _page_items(page: Any) -> list[Any]:
        return list(getattr(page, "items", ()) or ())

    @staticmethod
    def _page_total(page: Any) -> int:
        value = getattr(page, "total_items", getattr(page, "totalItems", None))
        return max(
            0, int(value if value is not None else len(PocketBaseSessionStore._page_items(page)))
        )

    def _trace_preview(
        self, pb: Any, *, session_id: str, turn_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        turn_id = _validate_id(turn_id, "turn_id")
        page = pb.collection("turn_events").get_list(
            1,
            MAX_TRACE_PREVIEW_EVENTS,
            query_params={"filter": f'turn_id="{turn_id}"', "sort": "-seq"},
        )
        rows = list(reversed(self._page_items(page)))
        events = [self._event_record_to_payload(row, session_id, turn_id) for row in rows]
        preview, omitted = compact_trace_preview(events)
        total = self._page_total(page)
        last_seq = int(getattr(rows[-1], "seq", 0) or 0) if rows else 0
        # The preview is the *tail* of the stream, so its first row is not
        # where the turn began. One extra single-row read gets the real start,
        # without which a turn that thought for a while and then answered in
        # one burst reports a span of zero. See ``_trace_bounds`` in the
        # SQLite store for the same reasoning.
        started_at = ended_at = None
        if rows:
            ended_at = _to_float(getattr(rows[-1], "event_timestamp", None))
            head = self._page_items(
                pb.collection("turn_events").get_list(
                    1,
                    1,
                    query_params={"filter": f'turn_id="{turn_id}"', "sort": "seq"},
                )
            )
            if head:
                started_at = _to_float(getattr(head[0], "event_timestamp", None))
        bounds = (
            {"started_at": started_at, "ended_at": max(started_at, ended_at or started_at)}
            if started_at is not None and ended_at is not None
            else {}
        )
        return preview, {
            "turn_id": turn_id,
            "total": total,
            "last_seq": last_seq,
            "truncated": omitted or total != len(preview),
            **bounds,
        }

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        sid = _validate_id(session_id, "session_id")

        def _get() -> list[dict[str, Any]]:
            pb = _pb()
            records = pb.collection("messages").get_full_list(
                query_params={
                    "filter": f'session_id="{sid}"',
                    "sort": "msg_created_at",
                }
            )
            turns = pb.collection("turns").get_full_list(
                query_params={"filter": f'session_id="{sid}"'}
            )
            turns_by_message = {
                str(getattr(turn, "assistant_message_id", "") or ""): turn
                for turn in turns
                if getattr(turn, "assistant_message_id", None)
            }
            result: list[dict[str, Any]] = []
            for record in records:
                message = self._message_record_to_dict(record)
                turn = turns_by_message.get(str(record.id))
                if record.role == "assistant" and turn is not None:
                    turn_id = str(getattr(turn, "turn_id", turn.id) or "")
                    message["events"], message["trace"] = self._trace_preview(
                        pb, session_id=sid, turn_id=turn_id
                    )
                elif record.role == "assistant":
                    legacy_events = message["events"]
                    message["events"], omitted = compact_trace_preview(legacy_events)
                    message["trace"] = {
                        "turn_id": None,
                        "total": len(legacy_events),
                        "last_seq": 0,
                        "truncated": omitted,
                    }
                result.append(message)
            return result

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            logger.warning(f"get_messages failed: {exc}")
            return []

    async def get_messages_for_context(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        # leaf_message_id (branch-aware context) is not supported on PocketBase
        # yet; fall back to the linear, append-only view.
        _ = leaf_message_id
        messages = await self.get_messages(session_id)
        return [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"] or "",
                "events": filter_ask_user_events(m.get("events")),
                "metadata": m.get("metadata") or {},
            }
            for m in messages
            if m["role"] in ("user", "assistant", "system")
        ]

    def _message_record_to_dict(self, record: Any) -> dict[str, Any]:
        return {
            "id": getattr(record, "id", ""),
            "session_id": getattr(record, "session_id", ""),
            "role": getattr(record, "role", ""),
            "content": getattr(record, "content", "") or "",
            "capability": getattr(record, "capability", "") or "",
            "events": _json_loads(getattr(record, "events_json", None), []),
            "attachments": _json_loads(getattr(record, "attachments_json", None), []),
            "metadata": _json_loads(getattr(record, "metadata_json", None), {}),
            "created_at": _to_float(getattr(record, "msg_created_at", None)),
        }

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def begin_turn(
        self,
        session_id: str,
        capability: str = "",
        *,
        turn_id: str | None = None,
        owner_id: str = "",
        fencing_token: int = 0,
    ) -> dict[str, Any]:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()
        now = time.time()
        resolved_turn_id = _validate_id(
            turn_id or f"turn_{int(now * 1000)}_{uuid.uuid4().hex[:10]}", "turn_id"
        )

        def _create():
            # Guard: ensure the session exists AND belongs to the current user.
            if _find_session_record(_pb(), sid, uid) is None:
                raise ValueError(f"Session not found: {sid}")
            # Guard: no duplicate active turns
            session_turns = (
                _pb()
                .collection("turns")
                .get_full_list(query_params={"filter": f'session_id="{sid}"'})
            )
            active = [
                record
                for record in session_turns
                if getattr(record, "status", "") in _ACTIVE_TURN_STATUSES
            ]
            if active:
                raise RuntimeError(f"Session already has an active turn: {active[0].turn_id}")
            return (
                _pb()
                .collection("turns")
                .create(
                    {
                        "turn_id": resolved_turn_id,
                        "session_id": sid,
                        "capability": capability or "",
                        "status": "running",
                        "error": "",
                        "turn_created_at": now,
                        "turn_updated_at": now,
                        "finished_at": None,
                        "owner_id": owner_id or "",
                        "fencing_token": max(0, int(fencing_token)),
                        "state_version": 1,
                        "failure_code": "",
                        "retryable": False,
                        "assistant_message_id": None,
                    }
                )
            )

        await asyncio.to_thread(_create)
        return {
            "id": resolved_turn_id,
            "turn_id": resolved_turn_id,
            "session_id": sid,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
            "owner_id": owner_id or "",
            "fencing_token": max(0, int(fencing_token)),
            "state_version": 1,
            "failure_code": "",
            "retryable": False,
            "assistant_message_id": None,
        }

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        return await self.begin_turn(session_id, capability)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        tid = _validate_id(turn_id, "turn_id")

        def _get():
            records = (
                _pb().collection("turns").get_full_list(query_params={"filter": f'turn_id="{tid}"'})
            )
            return records[0] if records else None

        record = await asyncio.to_thread(_get)
        return self._turn_record_to_dict(record) if record else None

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        sid = _validate_id(session_id, "session_id")

        def _get():
            records = (
                _pb()
                .collection("turns")
                .get_full_list(
                    query_params={"filter": f'session_id="{sid}"', "sort": "-turn_updated_at"}
                )
            )
            active = [
                record
                for record in records
                if getattr(record, "status", "") in _ACTIVE_TURN_STATUSES
            ]
            active.sort(key=lambda record: getattr(record, "turn_updated_at", 0), reverse=True)
            return active[0] if active else None

        record = await asyncio.to_thread(_get)
        return self._turn_record_to_dict(record) if record else None

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        sid = _validate_id(session_id, "session_id")

        def _list():
            records = (
                _pb()
                .collection("turns")
                .get_full_list(
                    query_params={"filter": f'session_id="{sid}"', "sort": "-turn_updated_at"}
                )
            )
            active = [
                record
                for record in records
                if getattr(record, "status", "") in _ACTIVE_TURN_STATUSES
            ]
            active.sort(key=lambda record: getattr(record, "turn_updated_at", 0), reverse=True)
            return active

        try:
            records = await asyncio.to_thread(_list)
            return [self._turn_record_to_dict(r) for r in records]
        except Exception:
            return []

    async def list_nonterminal_turns(self) -> list[dict[str, Any]]:
        def _list():
            records = (
                _pb().collection("turns").get_full_list(query_params={"sort": "turn_updated_at"})
            )
            return [
                record
                for record in records
                if getattr(record, "status", "") in _ACTIVE_TURN_STATUSES
            ]

        records = await asyncio.to_thread(_list)
        return [self._turn_record_to_dict(record) for record in records]

    async def transition_turn(
        self,
        turn_id: str,
        status: str,
        *,
        expected_status: str | None = None,
        fencing_token: int | None = None,
        error: str = "",
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool:
        if status not in _ALL_TURN_STATUSES:
            raise ValueError(f"Unsupported turn status: {status}")
        tid = _validate_id(turn_id, "turn_id")
        now = time.time()
        finished_at = now if status in _TERMINAL_TURN_STATUSES else None

        def _update():
            records = (
                _pb().collection("turns").get_full_list(query_params={"filter": f'turn_id="{tid}"'})
            )
            if not records:
                return False
            record = records[0]
            current_status = getattr(record, "status", "running")
            current_token = int(getattr(record, "fencing_token", 0) or 0)
            if expected_status is not None and current_status != expected_status:
                return False
            if fencing_token is not None and current_token != int(fencing_token):
                return False
            if current_status in _TERMINAL_TURN_STATUSES and current_status != status:
                return False
            _pb().collection("turns").update(
                record.id,
                {
                    "status": status,
                    "error": error or "",
                    "failure_code": failure_code or "",
                    "turn_updated_at": now,
                    "finished_at": finished_at,
                    "state_version": int(getattr(record, "state_version", 1) or 1) + 1,
                    "retryable": bool(retryable),
                },
            )
            return True

        try:
            updated = await asyncio.to_thread(_update)
        except Exception as exc:
            logger.warning(f"update_turn_status failed: {exc}")
            return False

        return updated

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        return await self.transition_turn(turn_id, status, error=error)

    def _turn_record_to_dict(self, record: Any) -> dict[str, Any]:
        turn_id = getattr(record, "turn_id", getattr(record, "id", ""))
        return {
            "id": turn_id,
            "turn_id": turn_id,
            "session_id": getattr(record, "session_id", ""),
            "capability": getattr(record, "capability", "") or "",
            "status": getattr(record, "status", "running") or "running",
            "error": getattr(record, "error", "") or "",
            "created_at": _to_float(getattr(record, "turn_created_at", None)),
            "updated_at": _to_float(getattr(record, "turn_updated_at", None)),
            "finished_at": _to_float(getattr(record, "finished_at", None)) or None,
            "last_seq": 0,
            "owner_id": getattr(record, "owner_id", "") or "",
            "fencing_token": int(getattr(record, "fencing_token", 0) or 0),
            "state_version": int(getattr(record, "state_version", 1) or 1),
            "failure_code": getattr(record, "failure_code", "") or "",
            "retryable": bool(getattr(record, "retryable", False)),
            "assistant_message_id": getattr(record, "assistant_message_id", None),
        }

    async def link_turn_message(self, turn_id: str, assistant_message_id: int | str) -> bool:
        tid = _validate_id(turn_id, "turn_id")
        message_id = _validate_id(str(assistant_message_id), "assistant_message_id")

        def _link() -> bool:
            page = (
                _pb()
                .collection("turns")
                .get_list(1, 1, query_params={"filter": f'turn_id="{tid}"'})
            )
            turns = self._page_items(page)
            if not turns:
                return False
            record = turns[0]
            if getattr(record, "assistant_message_id", None):
                return False
            _pb().collection("turns").update(
                record.id,
                {
                    "assistant_message_id": message_id,
                    "turn_updated_at": time.time(),
                },
            )
            return True

        return await asyncio.to_thread(_link)

    async def get_message_trace(
        self,
        session_id: str,
        message_id: int | str,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            sid = _validate_id(session_id, "session_id")
            mid = _validate_id(str(message_id), "message_id")
        except ValueError:
            return None
        row_limit = 500 if limit is None else min(1000, max(1, int(limit)))
        uid = _current_user_id()

        def _get():
            pb = _pb()
            if _find_session_record(pb, sid, uid) is None:
                return None
            message_page = pb.collection("messages").get_list(
                1,
                1,
                query_params={"filter": f'id="{mid}" && session_id="{sid}"'},
            )
            messages = self._page_items(message_page)
            if not messages:
                return None
            turn_page = pb.collection("turns").get_list(
                1,
                1,
                query_params={"filter": f'assistant_message_id="{mid}"'},
            )
            turns = self._page_items(turn_page)
            if not turns:
                return None
            turn = turns[0]
            turn_id = str(getattr(turn, "turn_id", getattr(turn, "id", "")) or "")
            stats_page = pb.collection("turn_events").get_list(
                1,
                1,
                query_params={"filter": f'turn_id="{turn_id}"', "sort": "-seq"},
            )
            last_rows = self._page_items(stats_page)
            last_seq = int(getattr(last_rows[0], "seq", 0) or 0) if last_rows else 0
            event_page = pb.collection("turn_events").get_list(
                1,
                row_limit,
                query_params={
                    "filter": f'turn_id="{turn_id}" && seq>{max(0, int(after_seq))}',
                    "sort": "seq",
                },
            )
            events = [
                self._event_record_to_payload(row, sid, turn_id)
                for row in self._page_items(event_page)
            ]
            loaded_seq = int(events[-1]["seq"]) if events else max(0, int(after_seq))
            complete = loaded_seq >= last_seq
            return {
                "session_id": sid,
                "message_id": message_id,
                "turn_id": turn_id,
                "events": events,
                "total": self._page_total(stats_page),
                "last_seq": last_seq,
                "next_seq": None if complete else loaded_seq,
                "complete": complete,
            }

        return await asyncio.to_thread(_get)

    # ------------------------------------------------------------------
    # Turn events — synchronously durable before terminal transition
    # ------------------------------------------------------------------

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Single-event convenience wrapper over ``append_turn_events``."""
        persisted = await self.append_turn_events(turn_id, [event])
        return persisted[0]

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return await self.append_events(turn_id, events)

    async def append_events(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        *,
        fencing_token: int | None = None,
    ) -> list[dict[str, Any]]:
        """Idempotently persist a batch before the caller can publish DONE."""
        tid = _validate_id(turn_id, "turn_id")

        def _persist() -> list[dict[str, Any]]:
            pb = _pb()
            if fencing_token is not None:
                turns = pb.collection("turns").get_full_list(
                    query_params={"filter": f'turn_id="{tid}"'}
                )
                if not turns or int(getattr(turns[0], "fencing_token", 0) or 0) != int(
                    fencing_token
                ):
                    raise RuntimeError(f"Turn lease lost: {tid}")

            existing_rows = pb.collection("turn_events").get_full_list(
                query_params={"filter": f'turn_id="{tid}"', "sort": "seq"}
            )
            existing_by_seq = {
                int(getattr(record, "seq", 0) or 0): record for record in existing_rows
            }
            next_seq = max(existing_by_seq, default=0) + 1
            payloads: list[dict[str, Any]] = []
            now = time.time()
            for event in events:
                payload = dict(event)
                seq = int(payload.get("seq") or 0)
                if seq <= 0:
                    seq = next_seq
                    next_seq += 1
                else:
                    next_seq = max(next_seq, seq + 1)
                payload["turn_id"] = payload.get("turn_id") or tid
                payload["seq"] = seq
                payload["timestamp"] = float(payload.get("timestamp") or now)

                existing = existing_by_seq.get(seq)
                if existing is not None:
                    same = (
                        (getattr(existing, "type", "") or "") == str(payload.get("type", ""))
                        and (getattr(existing, "source", "") or "")
                        == str(payload.get("source", ""))
                        and (getattr(existing, "stage", "") or "") == str(payload.get("stage", ""))
                        and (getattr(existing, "content", "") or "")
                        == str(payload.get("content", "") or "")[:10000]
                        and _json_loads(getattr(existing, "metadata_json", None), {})
                        == (payload.get("metadata") or {})
                    )
                    if not same:
                        raise ValueError(f"Turn event conflict: {tid} seq={seq}")
                    payload["timestamp"] = _to_float(
                        getattr(existing, "event_timestamp", None), payload["timestamp"]
                    )
                    payloads.append(payload)
                    continue

                record = pb.collection("turn_events").create(
                    {
                        "turn_id": tid,
                        "session_id": payload.get("session_id", ""),
                        "seq": seq,
                        "type": payload.get("type", ""),
                        "source": payload.get("source", ""),
                        "stage": payload.get("stage", ""),
                        "content": str(payload.get("content", ""))[:10000],
                        "metadata_json": payload.get("metadata", {}),
                        "event_timestamp": payload["timestamp"],
                    }
                )
                existing_by_seq[seq] = record
                payloads.append(payload)
            return payloads

        return await asyncio.to_thread(_persist)

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        """Retrieve persisted turn events from PocketBase (post-turn replay)."""
        tid = _validate_id(turn_id, "turn_id")

        def _get():
            filter_str = f'turn_id="{tid}"'
            if after_seq > 0:
                filter_str += f" && seq > {after_seq}"
            return (
                _pb()
                .collection("turn_events")
                .get_full_list(query_params={"filter": filter_str, "sort": "seq"})
            )

        try:
            records = await asyncio.to_thread(_get)
            return [
                {
                    "type": getattr(r, "type", ""),
                    "source": getattr(r, "source", ""),
                    "stage": getattr(r, "stage", ""),
                    "content": getattr(r, "content", "") or "",
                    "metadata": _json_loads(getattr(r, "metadata_json", None), {}),
                    "session_id": getattr(r, "session_id", ""),
                    "turn_id": tid,
                    "seq": int(getattr(r, "seq", 0)),
                    "timestamp": _to_float(getattr(r, "event_timestamp", None)),
                }
                for r in records
            ]
        except Exception as exc:
            logger.warning(f"get_turn_events failed: {exc}")
            return []

    async def get_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self.get_turn_events(turn_id, after_seq)
