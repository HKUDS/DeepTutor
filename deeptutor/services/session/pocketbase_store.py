"""
PocketBase-backed session store.

Implements SessionStoreProtocol using PocketBase collections for all durable
storage.  The key performance design:

- Most methods make direct PocketBase HTTP calls. These are called at most a
  handful of times per turn (create, get, update status, add message) and the
  ~5–10 ms overhead is acceptable.

- Turn events are the exception: they arrive hundreds at a time when the turn
  runtime flushes its in-memory buffer after the stream ends. Generic callers
  may use ``append_turn_events`` for a background upload, while the runtime's
  terminal path selects ``append_turn_events_durable`` and waits for the exact
  DONE row before publishing completion to subscribers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any
import uuid

logger = logging.getLogger(__name__)

_VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_TURN_STATUS_LOCK = threading.Lock()


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
        # Strong refs to in-flight turn-event upload tasks: ``create_task``
        # results are weakly referenced by the loop, so without this a GC
        # could cancel an upload mid-flight. Tasks discard themselves on
        # completion.
        self._event_upload_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

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
        created = _to_float(getattr(record, "created", None)) or now or time.time()
        updated = _to_float(getattr(record, "updated", None)) or now or time.time()
        preferences_raw = getattr(record, "preferences_json", None)
        return {
            "id": sid,
            "session_id": sid,
            "title": t,
            "created_at": created,
            "updated_at": updated,
            "compressed_summary": getattr(record, "compressed_summary", "") or "",
            "summary_up_to_msg_id": int(getattr(record, "summary_up_to_msg_id", 0) or 0),
            "preferences": _json_loads(preferences_raw, {}),
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
                record.id, {"title": (title.strip() or "New conversation")[:100]}
            )
            return True

        try:
            return await asyncio.to_thread(_update)
        except Exception as exc:
            logger.warning(f"update_session_title failed: {exc}")
            return False

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
            query_params: dict[str, Any] = {"sort": "-updated", "filter": f'user_id="{uid}"'}
            return _pb().collection("sessions").get_list(page, limit, query_params=query_params)

        try:
            result = await asyncio.to_thread(_list)
            return [self._session_record_to_dict(r) for r in result.items]
        except Exception as exc:
            logger.warning(f"list_sessions failed: {exc}")
            return []

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
            merged = {**session.get("preferences", {}), **(preferences or {})}
            uid = _current_user_id()

            def _update():
                record = _find_session_record(_pb(), sid, uid)
                if record is None:
                    return False
                _pb().collection("sessions").update(record.id, {"preferences_json": merged})
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
            raise RuntimeError("session_message_persistence_failed") from exc

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

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        sid = _validate_id(session_id, "session_id")

        def _get():
            return (
                _pb()
                .collection("messages")
                .get_full_list(
                    query_params={
                        "filter": f'session_id="{sid}"',
                        "sort": "msg_created_at",
                    }
                )
            )

        try:
            records = await asyncio.to_thread(_get)
            return [self._message_record_to_dict(r) for r in records]
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
            {"id": m["id"], "role": m["role"], "content": m["content"] or ""}
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

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        sid = _validate_id(session_id, "session_id")
        uid = _current_user_id()
        now = time.time()
        turn_id = f"turn_{int(now * 1000)}_{uuid.uuid4().hex[:10]}"

        def _create():
            # Guard: ensure the session exists AND belongs to the current user.
            if _find_session_record(_pb(), sid, uid) is None:
                raise ValueError(f"Session not found: {sid}")
            # Guard: no duplicate active turns
            active = (
                _pb()
                .collection("turns")
                .get_full_list(query_params={"filter": f'session_id="{sid}" && status="running"'})
            )
            if active:
                raise RuntimeError(f"Session already has an active turn: {active[0].turn_id}")
            return (
                _pb()
                .collection("turns")
                .create(
                    {
                        "turn_id": turn_id,
                        "session_id": sid,
                        "capability": capability or "",
                        "status": "running",
                        "error": "",
                        "turn_created_at": now,
                        "turn_updated_at": now,
                        "finished_at": None,
                    }
                )
            )

        await asyncio.to_thread(_create)
        return {
            "id": turn_id,
            "turn_id": turn_id,
            "session_id": sid,
            "capability": capability or "",
            "status": "running",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_seq": 0,
        }

    async def reserve_research_retry(self, session_id: str, parent_attempt_id: str, retry_request_id: str, parameters_hash: str) -> dict[str, Any]:
        """Durable reservation. Missing PocketBase schema fails closed."""
        sid = _validate_id(session_id, "session_id")
        now = time.time()
        def _reserve():
            collection = _pb().collection("research_retry_reservations")
            bindings = _pb().collection("research_retry_bindings")
            rows = collection.get_full_list(query_params={"filter": f'session_id="{sid}" && parent_attempt_id="{parent_attempt_id}" && retry_request_id="{retry_request_id}"'})
            if rows:
                row = rows[0]
                if str(getattr(row, "parameters_hash", "")) != parameters_hash:
                    raise RuntimeError("research_retry_idempotency_conflict")
                binding_rows = bindings.get_full_list(
                    query_params={"filter": f'reservation_id="{row.id}"'}
                )
                bound_turn = str(getattr(row, "turn_id", "") or "")
                if not bound_turn and binding_rows:
                    bound_turn = str(getattr(binding_rows[0], "turn_id", "") or "")
                return row, bound_turn
            try:
                row = collection.create({"session_id": sid, "parent_attempt_id": parent_attempt_id, "retry_request_id": retry_request_id, "parameters_hash": parameters_hash, "turn_id": "", "created_at": now})
                return row, ""
            except Exception:
                # The compound unique index may have been won by a concurrent
                # request. Re-read and compare rather than creating a second
                # logical reservation or silently treating a conflict as one.
                rows = collection.get_full_list(query_params={"filter": f'session_id="{sid}" && parent_attempt_id="{parent_attempt_id}" && retry_request_id="{retry_request_id}"'})
                if not rows:
                    raise
                row = rows[0]
                if str(getattr(row, "parameters_hash", "")) != parameters_hash:
                    raise RuntimeError("research_retry_idempotency_conflict")
                binding_rows = bindings.get_full_list(
                    query_params={"filter": f'reservation_id="{row.id}"'}
                )
                bound_turn = str(getattr(row, "turn_id", "") or "")
                if not bound_turn and binding_rows:
                    bound_turn = str(getattr(binding_rows[0], "turn_id", "") or "")
                return row, bound_turn
        try:
            row, bound_turn = await asyncio.to_thread(_reserve)
        except RuntimeError as exc:
            if str(exc) == "research_retry_idempotency_conflict":
                raise
            raise RuntimeError("research_retry_reservation_unavailable") from exc
        except Exception as exc:
            raise RuntimeError("research_retry_reservation_unavailable") from exc
        return {"id": str(getattr(row, "id", "")), "session_id": sid, "parent_attempt_id": parent_attempt_id, "retry_request_id": retry_request_id, "parameters_hash": parameters_hash, "turn_id": bound_turn or None}

    async def bind_research_retry_turn(
        self,
        reservation_id: str,
        turn_id: str,
        owner_id: str = "",
        heartbeat_at: float | None = None,
    ) -> bool:
        lease_time = float(heartbeat_at if heartbeat_at is not None else 0.0)

        def _bind():
            rows = _pb().collection("research_retry_reservations").get_full_list(query_params={"filter": f'id="{reservation_id}"'})
            if not rows:
                return False
            # Legacy rows may already carry the immutable winner in turn_id.
            legacy_turn = str(getattr(rows[0], "turn_id", "") or "")
            if legacy_turn:
                return legacy_turn == turn_id
            bindings = _pb().collection("research_retry_bindings")
            winners = bindings.get_full_list(
                query_params={"filter": f'reservation_id="{reservation_id}"'}
            )
            if winners:
                return str(getattr(winners[0], "turn_id", "")) == turn_id
            try:
                bindings.create({
                    "reservation_id": reservation_id,
                    "turn_id": turn_id,
                    "owner_id": owner_id,
                    "heartbeat_at": lease_time,
                    "created_at": time.time(),
                })
                return True
            except Exception:
                # Unique-index loser replays the server-selected winner.
                winners = bindings.get_full_list(
                    query_params={"filter": f'reservation_id="{reservation_id}"'}
                )
                if not winners:
                    raise
                return str(getattr(winners[0], "turn_id", "")) == turn_id
        try:
            return await asyncio.to_thread(_bind)
        except Exception as exc:
            raise RuntimeError("research_retry_reservation_unavailable") from exc

    async def get_research_retry_bound_turn(self, reservation_id: str) -> str | None:
        def _get_bound():
            rows = _pb().collection("research_retry_reservations").get_full_list(
                query_params={"filter": f'id="{reservation_id}"'}
            )
            if not rows:
                return None
            legacy_turn = str(getattr(rows[0], "turn_id", "") or "")
            if legacy_turn:
                return legacy_turn
            winners = _pb().collection("research_retry_bindings").get_full_list(
                query_params={"filter": f'reservation_id="{reservation_id}"'}
            )
            return str(getattr(winners[0], "turn_id", "") or "") if winners else None

        try:
            return await asyncio.to_thread(_get_bound)
        except Exception as exc:
            raise RuntimeError("research_retry_reservation_unavailable") from exc

    async def is_research_retry_bound_turn(self, turn_id: str) -> bool:
        """Whether *turn_id* is an immutable retry winner.

        Subscription recovery uses this as a safety boundary: unavailable or
        partially migrated retry schema must never broaden ordinary orphan
        handling, so lookup failures return ``False``.
        """
        tid = _validate_id(turn_id, "turn_id")

        def _is_bound() -> bool:
            reservations = _pb().collection("research_retry_reservations")
            legacy = reservations.get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            if legacy:
                return True
            bindings = _pb().collection("research_retry_bindings").get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            return bool(bindings)

        try:
            return await asyncio.to_thread(_is_bound)
        except Exception:
            logger.warning(
                "Retry-binding lookup unavailable for turn %s; using normal orphan handling",
                tid,
            )
            return False

    async def get_research_retry_lease(self, turn_id: str) -> dict[str, Any] | None:
        """Return retry ownership, treating pre-lease rows as stale leases."""
        tid = _validate_id(turn_id, "turn_id")

        def _get_lease() -> dict[str, Any] | None:
            legacy = _pb().collection("research_retry_reservations").get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            if legacy:
                row = legacy[0]
                return {
                    "turn_id": tid,
                    "owner_id": str(getattr(row, "owner_id", "") or ""),
                    "heartbeat_at": _to_float(getattr(row, "heartbeat_at", 0)),
                }
            rows = _pb().collection("research_retry_bindings").get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            if not rows:
                return None
            row = rows[0]
            return {
                "turn_id": tid,
                "owner_id": str(getattr(row, "owner_id", "") or ""),
                "heartbeat_at": _to_float(getattr(row, "heartbeat_at", 0)),
            }

        try:
            return await asyncio.to_thread(_get_lease)
        except Exception:
            logger.warning(
                "Retry lease lookup unavailable for turn %s; treating it as stale",
                tid,
            )
            return None

    async def heartbeat_research_retry_turn(
        self, turn_id: str, owner_id: str, heartbeat_at: float
    ) -> bool:
        """Renew only the binding owned by *owner_id*; schema gaps fail closed."""
        tid = _validate_id(turn_id, "turn_id")
        if not owner_id:
            return False

        def _heartbeat() -> bool:
            rows = _pb().collection("research_retry_bindings").get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            if not rows or str(getattr(rows[0], "owner_id", "") or "") != owner_id:
                return False
            _pb().collection("research_retry_bindings").update(
                rows[0].id,
                {"heartbeat_at": float(heartbeat_at)},
            )
            return True

        try:
            return await asyncio.to_thread(_heartbeat)
        except Exception:
            logger.warning(
                "Retry lease heartbeat unavailable for turn %s; renewal rejected",
                tid,
            )
            return False

    async def release_research_retry(self, reservation_id: str) -> bool:
        def _release():
            rows = _pb().collection("research_retry_reservations").get_full_list(query_params={"filter": f'id="{reservation_id}"'})
            bindings = _pb().collection("research_retry_bindings")
            winners = bindings.get_full_list(
                query_params={"filter": f'reservation_id="{reservation_id}"'}
            )
            if not rows or getattr(rows[0], "turn_id", "") or winners:
                return False
            _pb().collection("research_retry_reservations").delete(rows[0].id)
            return True
        try:
            return await asyncio.to_thread(_release)
        except Exception as exc:
            raise RuntimeError("research_retry_reservation_unavailable") from exc

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
                    query_params={
                        "filter": f'session_id="{sid}" && status="running"',
                        "sort": "-turn_updated_at",
                    }
                )
            )
            return records[0] if records else None

        record = await asyncio.to_thread(_get)
        return self._turn_record_to_dict(record) if record else None

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        sid = _validate_id(session_id, "session_id")

        def _list():
            return (
                _pb()
                .collection("turns")
                .get_full_list(
                    query_params={
                        "filter": f'session_id="{sid}" && status="running"',
                        "sort": "-turn_updated_at",
                    }
                )
            )

        try:
            records = await asyncio.to_thread(_list)
            return [self._turn_record_to_dict(r) for r in records]
        except Exception:
            return []

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        tid = _validate_id(turn_id, "turn_id")
        now = time.time()
        finished_at = now if status in {"completed", "failed", "cancelled"} else None

        def _update():
            records = (
                _pb().collection("turns").get_full_list(query_params={"filter": f'turn_id="{tid}"'})
            )
            if not records:
                return False
            _pb().collection("turns").update(
                records[0].id,
                {
                    "status": status,
                    "error": error or "",
                    "turn_updated_at": now,
                    "finished_at": finished_at,
                },
            )
            return True

        try:
            updated = await asyncio.to_thread(_update)
        except Exception as exc:
            logger.warning(f"update_turn_status failed: {exc}")
            return False

        return updated

    async def fail_running_turn(self, turn_id: str, error: str) -> bool:
        """Fail a restart orphan without overwriting an observed terminal row."""
        tid = _validate_id(turn_id, "turn_id")
        now = time.time()

        def _fail() -> bool:
            # PocketBase has no conditional update primitive. The process-wide
            # lock makes concurrent local followers one transition; the status
            # re-read keeps terminal rows immutable on this path.
            with _TURN_STATUS_LOCK:
                records = _pb().collection("turns").get_full_list(
                    query_params={"filter": f'turn_id="{tid}"'}
                )
                if not records or str(getattr(records[0], "status", "")) != "running":
                    return False
                _pb().collection("turns").update(
                    records[0].id,
                    {
                        "status": "failed",
                        "error": error,
                        "turn_updated_at": now,
                        "finished_at": now,
                    },
                )
                return True

        try:
            return await asyncio.to_thread(_fail)
        except Exception as exc:
            logger.warning("fail_running_turn failed: %s", exc)
            return False

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
        }

    # ------------------------------------------------------------------
    # Turn events — background replay writes and durable terminal batches
    # ------------------------------------------------------------------

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Single-event convenience wrapper over ``append_turn_events``."""
        persisted = await self.append_turn_events(turn_id, [event])
        return persisted[0]

    async def append_turn_events(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Annotate a turn's buffered events and upload them in the background.

        Returns the annotated payloads immediately for non-terminal callers.
        The turn runtime selects ``append_turn_events_durable`` instead.
        """
        tid = _validate_id(turn_id, "turn_id")
        payloads = self._annotate_turn_events(tid, events)
        if payloads:
            task = asyncio.create_task(self._upload_turn_events(tid, payloads))
            self._event_upload_tasks.add(task)
            task.add_done_callback(self._event_upload_tasks.discard)
        return payloads

    async def append_turn_events_durable(
        self, turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Persist a terminal batch before the runtime publishes its DONE."""
        tid = _validate_id(turn_id, "turn_id")
        payloads = self._annotate_turn_events(tid, events)

        def _create_all() -> None:
            pb = _pb()
            records = [self._turn_event_record(tid, event) for event in payloads]
            create_batch = getattr(pb, "create_batch", None)
            if callable(create_batch) and records:
                batch = create_batch()
                for record in records:
                    batch.collection("turn_events").create(record)
                results = batch.send()
                failures = [
                    result
                    for result in results
                    if not 200 <= int(result.get("status_code", 0)) < 300
                ]
                if failures or len(results) != len(records):
                    raise RuntimeError(
                        f"PocketBase terminal batch failed: {failures or results!r}"
                    )
                return
            for record in records:
                pb.collection("turn_events").create(record)

        await asyncio.to_thread(_create_all)
        return payloads

    async def finalize_turn_with_events(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        status: str,
        error: str = "",
    ) -> list[dict[str, Any]]:
        """Atomically persist the terminal event batch and turn status."""
        tid = _validate_id(turn_id, "turn_id")
        payloads = self._annotate_turn_events(tid, events)
        now = time.time()
        status_payload = {
            "status": status,
            "error": error or "",
            "turn_updated_at": now,
            "finished_at": (
                now if status in {"completed", "failed", "cancelled"} else None
            ),
        }

        def _finalize() -> None:
            pb = _pb()
            turns = pb.collection("turns")
            turn_rows = turns.get_full_list(
                query_params={"filter": f'turn_id="{tid}"'}
            )
            if not turn_rows:
                raise ValueError(f"Turn not found: {tid}")
            records = [self._turn_event_record(tid, event) for event in payloads]
            create_batch = getattr(pb, "create_batch", None)
            if callable(create_batch):
                batch = create_batch()
                for record in records:
                    batch.collection("turn_events").create(record)
                batch.collection("turns").update(turn_rows[0].id, status_payload)
                results = batch.send()
                failures = [
                    result
                    for result in results
                    if not 200 <= int(result.get("status_code", 0)) < 300
                ]
                if failures or len(results) != len(records) + 1:
                    raise RuntimeError(
                        f"PocketBase terminal batch failed: {failures or results!r}"
                    )
                return
            # Test/legacy-client fallback. Status remains running until every
            # event create succeeds, so a partial failure cannot publish a
            # completed turn through the runtime.
            for record in records:
                pb.collection("turn_events").create(record)
            turns.update(turn_rows[0].id, status_payload)

        await asyncio.to_thread(_finalize)
        return payloads

    @staticmethod
    def _annotate_turn_events(
        turn_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        base_seq = int(time.time() * 1000) % 1_000_000
        payloads: list[dict[str, Any]] = []
        for offset, event in enumerate(events):
            payload = dict(event)
            payload.setdefault("turn_id", turn_id)
            if not payload.get("seq"):
                payload["seq"] = base_seq + offset
            payloads.append(payload)
        return payloads

    @staticmethod
    def _turn_event_record(turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": turn_id,
            "session_id": event.get("session_id", ""),
            "seq": int(event.get("seq", 0)),
            "type": event.get("type", ""),
            "source": event.get("source", ""),
            "stage": event.get("stage", ""),
            "content": str(event.get("content", ""))[:10000],
            "metadata_json": event.get("metadata", {}),
            "event_timestamp": float(event.get("timestamp", 0)),
        }

    async def _upload_turn_events(self, turn_id: str, payloads: list[dict[str, Any]]) -> None:
        def _create_all() -> int:
            pb = _pb()
            created = 0
            for event in payloads:
                try:
                    pb.collection("turn_events").create(
                        self._turn_event_record(turn_id, event)
                    )
                    created += 1
                except Exception as exc:
                    logger.debug(f"turn_events upload item failed: {exc}")
            return created

        try:
            created = await asyncio.to_thread(_create_all)
            logger.debug(f"Uploaded {created}/{len(payloads)} turn events for {turn_id}")
        except Exception as exc:
            logger.warning(f"Turn-event upload failed for {turn_id}: {exc}")

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
