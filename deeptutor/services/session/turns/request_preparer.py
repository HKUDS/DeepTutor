"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any
import uuid

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.turn_request import TurnRequest
from deeptutor.runtime.capability_routing import route_explicit_quiz_request
from deeptutor.services.session.workspace_preferences import (
    WORKSPACE_MODE_MASTERY,
    WORKSPACE_MODE_READING,
)

from .._turn_runtime_shared import (
    _apply_course_defaults,
    _coerce_bool,
    _course_conventions_block,
    _extract_selection_tutor_context,
    _llm_selection_dict,
    _mastery_loop_managed,
    _mastery_path_id,
    _partner_group_references,
    _reading_material_id,
    _reading_material_revision,
    _reading_references,
    _reading_workspace_id,
    _resolve_selection_tutor_context,
    _timed_media_id,
    _TurnExecution,
    _workspace_mode,
)

if TYPE_CHECKING:
    from deeptutor.runtime.coordination import RuntimeCoordinator
    from deeptutor.services.session.protocol import SessionStoreProtocol


class TurnRequestPreparer:
    if TYPE_CHECKING:
        store: SessionStoreProtocol
        coordinator: RuntimeCoordinator | None
        owner_id: str
        _coordination_scope: str
        _lock: asyncio.Lock
        _executions: dict[str, _TurnExecution]

        async def _ensure_accepting_turns(self) -> None: ...

        def _turns_blocked_for_update_locked(self) -> bool: ...

        async def _validate_mastery_session_topic(
            self,
            *,
            session_id: str,
            requested_path_id: str,
            remembered_path_id: str,
        ) -> None: ...

        async def _commit_mastery_card_answer(
            self,
            *,
            path_id: str,
            session_id: str,
            turn_id: str,
            question_id: str,
            answer: str,
        ) -> None: ...

        async def _acquire_mastery_path_lease(
            self,
            *,
            path_id: str,
            session_id: str,
            turn_id: str,
            owns_path: bool,
        ) -> None: ...

        async def _publish_live_event(
            self,
            execution: _TurnExecution,
            event: StreamEvent,
        ) -> dict[str, Any]: ...

        async def _run_turn(self, execution: _TurnExecution) -> None: ...

        async def _coordinate_execution(self, execution: _TurnExecution) -> None: ...

    async def start_turn(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        await self._ensure_accepting_turns()
        # ``TurnRuntimeManager`` remains a one-version compatibility facade;
        # transport adapters normally strip their envelope before reaching it.
        payload = TurnRequest.model_validate(
            {key: value for key, value in payload.items() if key != "type"}
        ).to_payload()
        persona_explicit = "persona" in payload
        if not payload.get("language"):
            from deeptutor.services.settings.interface_settings import (
                get_response_language,
            )

            payload = {**payload, "language": get_response_language(default="en")}
        raw_config = dict(payload.get("config", {}) or {})
        per_turn_auto_route = payload.get("auto_route")
        if per_turn_auto_route is None:
            from deeptutor.services.config.runtime_settings import load_system_settings

            routing_enabled = _coerce_bool(
                load_system_settings().get("capability_routing_enabled"), False
            )
        else:
            routing_enabled = _coerce_bool(per_turn_auto_route, False)
        session = await self.store.ensure_session(payload.get("session_id"))
        preferences = session.get("preferences") or {}

        course_id_explicit = "course_id" in payload
        requested_course_id = str(
            (payload.get("course_id") if course_id_explicit else preferences.get("course_id")) or ""
        ).strip()
        bound_course = None
        if requested_course_id:
            from deeptutor.services.courses import (
                CourseNotFoundError,
                get_course_service,
            )

            try:
                bound_course = await asyncio.to_thread(
                    get_course_service().get,
                    requested_course_id,
                )
            except CourseNotFoundError:
                requested_course_id = ""
        if bound_course is not None:
            payload = _apply_course_defaults(
                payload,
                bound_course,
                preferences=preferences,
            )

        requested_capability = str(payload.get("capability") or "chat")
        # Resolved before routing, and from the *requested* action: the
        # workspace is what decides whether this turn may be re-routed at all,
        # so it cannot be derived from the routing outcome.
        workspace_mode_explicit = "workspace_mode" in payload
        workspace_mode = _workspace_mode(
            payload.get("workspace_mode")
            if workspace_mode_explicit
            else preferences.get("workspace_mode"),
            capability=requested_capability,
        )
        capability_route = route_explicit_quiz_request(
            payload.get("content"),
            requested_capability,
            enabled=routing_enabled,
            workspace_mode=workspace_mode,
        )
        capability = (
            capability_route.capability if capability_route is not None else requested_capability
        )
        try:
            from deeptutor.multi_user.learning_access import apply_learning_policy

            payload = apply_learning_policy({**payload, "capability": capability})
        except PermissionError as exc:
            raise RuntimeError(str(exc)) from exc

        try:
            from deeptutor.runtime.request_contracts import validate_capability_config

            # A routed capability owns a different schema. Chat-only options
            # must not be smuggled into the generator; the user request itself
            # carries the desired topic/count.
            validated_public_config = validate_capability_config(
                capability,
                {} if capability_route is not None else raw_config,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        payload = {
            **payload,
            "capability": capability,
            "workspace_mode": workspace_mode,
            "course_id": requested_course_id,
            # Rendered here, where the course is already loaded and validated,
            # and carried on the payload so the run phase needs no second read.
            # Session preferences are assembled key by key below, so this rides
            # along without being persisted.
            "course_conventions": (
                _course_conventions_block(bound_course, str(payload.get("language") or "en"))
                if bound_course is not None
                else ""
            ),
            "requested_capability": requested_capability,
            "capability_route": (
                capability_route.as_metadata() if capability_route is not None else None
            ),
            "config": validated_public_config,
        }
        reading_workspace_id = _reading_workspace_id(payload.get("reading_workspace_id"))
        reading_material_id = _reading_material_id(payload.get("reading_material_id"))
        reading_material_revision = _reading_material_revision(
            payload.get("reading_material_revision")
        )
        if workspace_mode == WORKSPACE_MODE_READING and reading_workspace_id:
            from deeptutor.reading import ReadingCatalogStore

            reading_catalog = ReadingCatalogStore()
            reading_workspace = reading_catalog.get_workspace(reading_workspace_id)
            if reading_workspace is None:
                raise RuntimeError("The reading workspace is unavailable.")
            reading_material_id = reading_material_id or str(
                reading_workspace.active_material_id or ""
            )
            if reading_material_id and reading_material_id not in {
                tab.material.material_id for tab in reading_workspace.tabs
            }:
                raise RuntimeError("The active material is not part of this reading workspace.")
            reading_catalog.attach_session(
                reading_workspace_id,
                session["id"],
                title=str(session.get("title") or "New reading conversation"),
                active_material_id=reading_material_id or None,
            )
            payload = {
                **payload,
                "reading_workspace_id": reading_workspace_id,
                "reading_material_id": reading_material_id,
                "reading_material_revision": reading_material_revision,
            }
        # A mastery path has a longer lifetime than any one conversation.
        # Persist the explicit association on the session, and restore it on
        # later turns whose frontend payload omits the field.
        mastery_path_explicit = "mastery_path_id" in payload
        configured_mastery_path_id = _mastery_path_id(
            payload.get("mastery_path_id")
            if mastery_path_explicit
            else preferences.get("mastery_path_id")
        )
        mastery_binding = None
        if workspace_mode == WORKSPACE_MODE_MASTERY:
            from deeptutor.learning.identity import resolve_mastery_path_binding

            mastery_binding = resolve_mastery_path_binding(
                configured_path_id=configured_mastery_path_id,
                book_references=payload.get("book_references", []),
                session_id=session["id"],
            )
            mastery_path_id = mastery_binding.path_id
            await self._validate_mastery_session_topic(
                session_id=session["id"],
                requested_path_id=mastery_path_id,
                remembered_path_id=_mastery_path_id(preferences.get("mastery_path_id")),
            )
        else:
            mastery_path_id = configured_mastery_path_id
        mastery_lease_managed = bool(
            mastery_binding is not None and _mastery_loop_managed(workspace_mode, capability)
        )
        # What this conversation is for — designing the outline, learning, or
        # reviewing. Durable session state like the path id, but *mutable*:
        # the tutor may change it mid-turn with ``mastery_mode`` and the
        # learner may change it from the header, so the value a turn starts
        # with is only where it starts.
        from deeptutor.capabilities.mastery.mode import enforced_mode

        # ``or``, not "is the key present": the client writes this key on every
        # turn and leaves it null whenever it does not happen to hold the mode
        # in memory (a reload, a session loaded from the server before its
        # preference came back). Reading a null as "the client said none" threw
        # away the mode the conversation was actually in — so the tutor was
        # told it was studying while the learner watched the outline mode
        # highlighted above the transcript, and never switched because it
        # believed it already had.
        raw_mastery_mode = payload.get("mastery_session_mode") or preferences.get(
            "mastery_session_mode"
        )
        # ``enforced_mode`` rather than ``normalize_mode``: a conversation that
        # never recorded a mode must stay unrecorded all the way down to the
        # tools, which read the absence as "enforce nothing".
        mastery_session_mode = enforced_mode(raw_mastery_mode)
        payload = {
            **payload,
            "mastery_path_id": mastery_path_id,
            "mastery_path_lease_managed": mastery_lease_managed,
            "mastery_session_mode": mastery_session_mode,
        }
        # Persona is a session-level preference (mirrors llm_selection): an
        # explicit ``persona`` key in the payload — including an empty string,
        # which means "Default" / no persona — wins and is persisted below.
        # A course default is filled above only when that key was absent; with
        # neither, the session's stored preference survives reloads.
        persona_pref = str(
            (payload.get("persona") if "persona" in payload else preferences.get("persona")) or ""
        ).strip()
        payload = {**payload, "persona": persona_pref}
        raw_llm_selection = payload.get("llm_selection")
        if raw_llm_selection is None:
            raw_llm_selection = preferences.get("llm_selection")
        try:
            llm_selection = _llm_selection_dict(raw_llm_selection)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if llm_selection:
            try:
                from deeptutor.multi_user.model_access import apply_allowed_llm_selection

                llm_selection = apply_allowed_llm_selection(llm_selection) or {}
            except PermissionError as exc:
                raise RuntimeError(str(exc)) from exc
        else:
            # Non-admin users MUST end up with a concrete llm_selection so we
            # never silently fall through to the global LLM client (which is
            # configured from admin runtime settings). Admin keeps the existing behavior
            # (None llm_selection → default config from admin scope).
            from deeptutor.multi_user.context import get_current_user
            from deeptutor.multi_user.model_access import (
                has_capability_access,
                redacted_model_access,
            )

            current_user = get_current_user()
            if not current_user.is_admin:
                # Single gate, shared with the frontend lock and any HTTP
                # surface: no usable LLM grant → a clear terminal error here
                # instead of a silent fall-through to the global client.
                if not has_capability_access("llm"):
                    raise RuntimeError(
                        "No LLM model is assigned to your account. Please contact an administrator."
                    )
                # Pin the first granted-and-available model as the selection.
                assigned_llms = [
                    item
                    for item in redacted_model_access(current_user.id).get("llm", [])
                    if item.get("available")
                ]
                llm_selection = {
                    "profile_id": assigned_llms[0].get("profile_id"),
                    "model_id": assigned_llms[0].get("model_id"),
                }
        if llm_selection:
            from deeptutor.multi_user.personal_models import merge_personal_llm_profiles
            from deeptutor.services.config import get_model_catalog_service
            from deeptutor.services.model_selection import (
                LLMSelection,
                apply_llm_selection_to_catalog,
            )

            try:
                # Personal (owner-bound) profiles live in the user's own
                # catalog, so validating against the shared one alone would
                # reject a Codex model the user signed in for themselves —
                # the same merge the resolution path performs (#781).
                apply_llm_selection_to_catalog(
                    merge_personal_llm_profiles(get_model_catalog_service().load()),
                    LLMSelection.from_payload(llm_selection),
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
        # If the caller didn't pin a per-turn tool list (e.g. non-web
        # channels or the new web UI which sources tools from
        # /settings/tools), back-fill from the user's saved toggleable-tool
        # preference so the chat pipeline sees the same set the user picked
        # in Settings. Callers that explicitly pass ``tools`` (including
        # an empty list) keep their value untouched.
        if payload.get("tools") is None:
            try:
                from deeptutor.services.settings.interface_settings import (
                    get_enabled_optional_tools,
                )

                payload = {**payload, "tools": list(get_enabled_optional_tools())}
            except Exception:
                payload = {**payload, "tools": []}
        # Admin-imposed per-user tool whitelist (grant v2). Sits after the
        # back-fill so explicit caller lists and settings defaults pass the
        # same gate; this is the single enforcement point for every
        # capability's turn.
        from deeptutor.multi_user.tool_access import allowed_optional_tools

        allowed_tools = allowed_optional_tools()
        if allowed_tools is not None:
            payload = {
                **payload,
                "tools": [t for t in (payload.get("tools") or []) if t in allowed_tools],
            }
        if capability_route is not None and capability_route.auto_routed:
            from deeptutor.runtime.registry.capability_registry import (
                get_capability_registry,
            )

            routed_capability = get_capability_registry().get(capability_route.capability)
            if routed_capability is not None:
                allowed_by_manifest = set(routed_capability.manifest.tools_used)
                payload = {
                    **payload,
                    "tools": [
                        tool for tool in (payload.get("tools") or []) if tool in allowed_by_manifest
                    ],
                }
        payload = {**payload, "llm_selection": llm_selection}
        lease = None
        if self.coordinator is not None:
            turn_id = f"turn_{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}"
            lease = await self.coordinator.acquire_turn(
                turn_id,
                f"{self._coordination_scope}:{session['id']}",
                self.owner_id,
            )
            if lease is None:
                raise RuntimeError("Session already has an active or recovering turn")
        preference_update: dict[str, Any] = {
            # Auto-routing is a one-turn execution choice; keep the durable
            # preference on what the caller explicitly selected.
            "capability": requested_capability,
            "tools": list(payload.get("tools") or []),
            "knowledge_bases": list(payload.get("knowledge_bases") or []),
            "language": str(payload.get("language") or "en"),
        }
        # Missing legacy chat fields should not manufacture an empty stored
        # preference. Explicit empties still clear a workspace, while a
        # non-empty legacy capability is persisted as part of migration.
        if workspace_mode_explicit or workspace_mode:
            preference_update["workspace_mode"] = workspace_mode
        if course_id_explicit:
            preference_update["course_id"] = requested_course_id

        raw_selection_context = payload.get("selection_tutor_context")
        if isinstance(raw_selection_context, dict):
            selection_tutor_context = _extract_selection_tutor_context(
                {"selection_tutor_context": dict(raw_selection_context)}
            )
            if selection_tutor_context is None:
                raise RuntimeError("Selection tutor context requires selected text")
            try:
                selection_tutor_context = await _resolve_selection_tutor_context(
                    self.store,
                    selection_tutor_context,
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            payload["selection_tutor_context"] = selection_tutor_context
            parent_session_id = str(selection_tutor_context.get("parent_session_id") or "").strip()
            if parent_session_id == session["id"]:
                raise RuntimeError("A selection tutor session cannot parent itself")
            if parent_session_id:
                from deeptutor.services.session.organization import (
                    validate_parent_assignment,
                )

                try:
                    parent_session = await validate_parent_assignment(
                        self.store,
                        session_id=session["id"],
                        parent_session_id=parent_session_id,
                    )
                except (LookupError, ValueError) as exc:
                    raise RuntimeError(str(exc)) from exc
                parent_preferences = parent_session.get("preferences") or {}
                preference_update.update(
                    {
                        "parent_session_id": parent_session_id,
                        "session_kind": "selection_tutor",
                        "course_id": str(parent_preferences.get("course_id") or ""),
                    }
                )
        if llm_selection:
            preference_update["llm_selection"] = llm_selection
        if persona_explicit:
            # Persist explicit set AND explicit clear ("" = back to Default).
            preference_update["persona"] = persona_pref
        if mastery_path_explicit or mastery_binding is not None:
            # Mastery turns persist their fully resolved path so a later turn
            # cannot silently fall back to a different aggregate.
            preference_update["mastery_path_id"] = mastery_path_id
            # …and what the conversation is for, which is decided when it is
            # opened and must survive every later turn that does not restate it.
            if mastery_session_mode:
                preference_update["mastery_session_mode"] = mastery_session_mode
        if workspace_mode == WORKSPACE_MODE_READING and reading_workspace_id:
            preference_update.update(
                {
                    "session_kind": "immersive_reading",
                    "reading_workspace_id": reading_workspace_id,
                    "reading_material_id": reading_material_id,
                }
            )
        elif (
            workspace_mode_explicit
            and not workspace_mode
            and preferences.get("session_kind") == "immersive_reading"
        ):
            preference_update.update(
                {
                    "session_kind": "chat",
                    "reading_workspace_id": "",
                    "reading_material_id": "",
                }
            )
        await self.store.update_session_preferences(session["id"], preference_update)
        try:
            if lease is None:
                turn = await self.store.create_turn(session["id"], capability=capability)
            else:
                turn = await self.store.begin_turn(
                    session["id"],
                    capability=capability,
                    turn_id=lease.turn_id,
                    owner_id=lease.owner_id,
                    fencing_token=lease.fencing_token,
                )
        except Exception:
            if lease is not None and self.coordinator is not None:
                with contextlib.suppress(Exception):
                    await self.coordinator.release_turn(lease)
            raise
        execution = _TurnExecution(
            turn_id=turn["id"],
            session_id=session["id"],
            capability=capability,
            payload=dict(payload),
            lease=lease,
        )
        # Publish an ownership marker before trying to recover another path
        # lease. Two start_turn calls can otherwise interleave after the first
        # turn row is created but before its task is registered, causing the
        # second caller to misclassify that healthy turn as a restart orphan.
        async with self._lock:
            update_blocked = self._turns_blocked_for_update_locked()
            if not update_blocked:
                self._executions[turn["id"]] = execution
        if update_blocked:
            with contextlib.suppress(Exception):
                await self.store.transition_turn(
                    turn["id"],
                    "failed",
                    error="DeepTutor is preparing an update; try again after it reconnects",
                    failure_code="rejected",
                )
            raise RuntimeError("DeepTutor is preparing an update; try again after it reconnects")
        mastery_lease_acquired = False
        if mastery_binding is not None and mastery_lease_managed:
            try:
                await self._acquire_mastery_path_lease(
                    path_id=mastery_binding.path_id,
                    session_id=session["id"],
                    turn_id=turn["id"],
                    owns_path=mastery_binding.owned_by_session,
                )
                mastery_lease_acquired = True
                card_answer = payload.get("mastery_answer") or {}
                if isinstance(card_answer, dict) and card_answer.get("question_id"):
                    # Commit before the loop starts so the tutor's first
                    # mastery_status already reports this answer.
                    await self._commit_mastery_card_answer(
                        path_id=mastery_binding.path_id,
                        session_id=session["id"],
                        turn_id=turn["id"],
                        question_id=str(card_answer.get("question_id") or ""),
                        answer=str(card_answer.get("text") or ""),
                    )
            except Exception as exc:
                async with self._lock:
                    self._executions.pop(turn["id"], None)
                with contextlib.suppress(Exception):
                    await self.store.transition_turn(
                        turn["id"],
                        "failed",
                        error=str(exc),
                        failure_code="rejected",
                    )
                raise
            persisted_turn = await self.store.get_turn(turn["id"])
            if persisted_turn is None or persisted_turn.get("status") != "running":
                # An administrative reset/delete can cancel the placeholder
                # while lease acquisition is in flight. Never launch a task
                # after that cancellation has already become durable.
                from deeptutor.learning.storage import LearningStore

                async with self._lock:
                    self._executions.pop(turn["id"], None)
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        LearningStore().release_path_lease,
                        mastery_binding.path_id,
                        turn_id=turn["id"],
                    )
                raise RuntimeError("Mastery turn was cancelled while starting")
        session_metadata: dict[str, Any] = {
            "session_id": session["id"],
            "turn_id": turn["id"],
        }
        regenerated_from = payload.get("regenerated_from_message_id")
        if regenerated_from is not None:
            session_metadata["regenerated_from_message_id"] = regenerated_from
        superseded_turn_id = payload.get("superseded_turn_id")
        if superseded_turn_id:
            session_metadata["superseded_turn_id"] = str(superseded_turn_id)
        if payload.get("regenerate"):
            session_metadata["regenerate"] = True
        if capability_route is not None:
            session_metadata["capability_route"] = capability_route.as_metadata()
        try:
            await self._publish_live_event(
                execution,
                StreamEvent(
                    type=StreamEventType.SESSION,
                    source="turn_runtime",
                    metadata=session_metadata,
                ),
            )
            async with self._lock:
                execution.task = asyncio.create_task(self._run_turn(execution))
                if execution.lease is not None and self.coordinator is not None:
                    execution.coordination_task = asyncio.create_task(
                        self._coordinate_execution(execution)
                    )
        except Exception as exc:
            async with self._lock:
                self._executions.pop(turn["id"], None)
            if mastery_binding is not None and mastery_lease_acquired:
                from deeptutor.learning.storage import LearningStore

                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        LearningStore().release_path_lease,
                        mastery_binding.path_id,
                        turn_id=turn["id"],
                    )
            with contextlib.suppress(Exception):
                await self.store.update_turn_status(turn["id"], "failed", str(exc))
            if lease is not None and self.coordinator is not None:
                with contextlib.suppress(Exception):
                    await self.coordinator.release_turn(lease)
            raise
        return session, turn

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Re-run the prior user message in ``session_id``.

        Deletes the trailing assistant message (if any), then dispatches a new
        turn with ``persist_user_message=False`` and ``regenerate=True`` so
        the runtime knows not to duplicate the user row or refresh long-term
        memory a second time. The original user message stays in place.
        """
        session_id = str(session_id or "").strip()
        if not session_id:
            raise RuntimeError("nothing_to_regenerate")

        session = await self.store.get_session(session_id)
        if session is None:
            raise RuntimeError("nothing_to_regenerate")

        active = await self.store.get_active_turn(session_id)
        if active is not None:
            raise RuntimeError("regenerate_busy")

        last_user = await self.store.get_last_message(session_id, role="user")
        if last_user is None:
            raise RuntimeError("nothing_to_regenerate")

        last_message = await self.store.get_last_message(session_id)
        previous_turn_id: str | None = None
        if last_message is not None and last_message.get("role") == "assistant":
            for event in last_message.get("events") or []:
                turn_id = str((event or {}).get("turn_id") or "")
                if turn_id:
                    previous_turn_id = turn_id
                    break
            await self.store.delete_message(last_message["id"])

        preferences = session.get("preferences") or {}
        overrides = overrides or {}
        snapshot = {}
        metadata = last_user.get("metadata") or {}
        if isinstance(metadata, dict):
            candidate = metadata.get("request_snapshot") or metadata.get("requestSnapshot")
            if isinstance(candidate, dict):
                snapshot = candidate

        capability = str(
            overrides.get("capability")
            or last_user.get("capability")
            or preferences.get("capability")
            or "chat"
        )
        tools = list(
            overrides.get("tools")
            if overrides.get("tools") is not None
            else preferences.get("tools") or []
        )
        knowledge_bases = list(
            overrides.get("knowledge_bases")
            if overrides.get("knowledge_bases") is not None
            else preferences.get("knowledge_bases") or []
        )
        language = str(overrides.get("language") or preferences.get("language") or "en")

        config: dict[str, Any] = dict(overrides.get("config") or {})
        llm_selection = (
            overrides.get("llm_selection")
            if overrides.get("llm_selection") is not None
            else snapshot.get("llmSelection") or preferences.get("llm_selection")
        )
        mastery_path_id = _mastery_path_id(
            overrides.get("mastery_path_id")
            if "mastery_path_id" in overrides
            else snapshot.get("masteryPathId") or preferences.get("mastery_path_id")
        )
        workspace_mode = _workspace_mode(
            overrides.get("workspace_mode")
            if "workspace_mode" in overrides
            else snapshot.get("workspaceMode") or preferences.get("workspace_mode"),
            capability=capability,
        )

        payload: dict[str, Any] = {
            "session_id": session_id,
            "capability": capability,
            "workspace_mode": workspace_mode,
            "content": str(last_user.get("content", "") or ""),
            "tools": tools,
            "knowledge_bases": knowledge_bases,
            "language": language,
            "attachments": list(last_user.get("attachments") or []),
            "notebook_references": list(
                overrides.get("notebook_references")
                if overrides.get("notebook_references") is not None
                else preferences.get("notebook_references") or []
            ),
            "history_references": list(
                overrides.get("history_references")
                if overrides.get("history_references") is not None
                else preferences.get("history_references") or []
            ),
            "partner_group_references": _partner_group_references(
                overrides.get("partner_group_references")
                if overrides.get("partner_group_references") is not None
                else snapshot.get("partnerGroupReferences")
                or preferences.get("partner_group_references")
                or []
            ),
            "book_references": list(
                overrides.get("book_references")
                if overrides.get("book_references") is not None
                else snapshot.get("bookReferences") or []
            ),
            "reading_references": _reading_references(
                overrides.get("reading_references")
                if "reading_references" in overrides
                else snapshot.get("readingReferences")
            ),
            "mastery_path_id": mastery_path_id,
            # A regenerate must run as the same kind of conversation the turn
            # originally ran as, or it would be handed a different tool surface
            # than the answer it is replacing.
            "mastery_session_mode": (
                overrides.get("mastery_session_mode")
                if "mastery_session_mode" in overrides
                else preferences.get("mastery_session_mode")
            ),
            # Recovered from the original turn's snapshot so the regenerate runs
            # against the same document. An explicit override wins (the reader
            # may have moved on), and the viewport is deliberately not restored —
            # "where the user was looking" is stale by definition on a retry.
            "reading_material_id": _reading_material_id(
                overrides.get("reading_material_id")
                if "reading_material_id" in overrides
                else snapshot.get("readingMaterialId")
            ),
            "reading_material_revision": _reading_material_revision(
                overrides.get("reading_material_revision")
                if "reading_material_revision" in overrides
                else snapshot.get("readingMaterialRevision")
            ),
            "reading_workspace_id": _reading_workspace_id(
                overrides.get("reading_workspace_id")
                if "reading_workspace_id" in overrides
                else snapshot.get("readingWorkspaceId") or preferences.get("reading_workspace_id")
            ),
            "timed_media_id": _timed_media_id(
                overrides.get("timed_media_id")
                if "timed_media_id" in overrides
                else snapshot.get("timedMediaId")
            ),
            "config": config,
            "persist_user_message": False,
            "regenerate": True,
            "regenerated_from_message_id": int(last_user["id"]),
        }
        if previous_turn_id:
            payload["superseded_turn_id"] = previous_turn_id
        if llm_selection:
            payload["llm_selection"] = llm_selection
        return await self.start_turn(payload)
