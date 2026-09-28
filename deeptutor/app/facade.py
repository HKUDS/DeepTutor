"""Stable application-layer facade for DeepTutor entry points."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import importlib.util
import inspect
import json
from typing import Any, AsyncIterator

from deeptutor.services.notebook import get_notebook_manager

from .container import get_application_container
from .contracts import TurnRequest


def _in_app_workspace(method):
    from deeptutor.services.workspace.activity import data_activity
    from deeptutor.services.workspace.models import WorkspaceError

    def validate(scope):
        if scope.archived and method.__name__ in {
            "rename_session",
            "delete_session",
            "create_notebook",
            "add_record",
            "update_record",
            "remove_record",
        }:
            raise WorkspaceError("Restore this workspace before changing its data.")

    if inspect.iscoroutinefunction(method):

        @wraps(method)
        async def call(self, *args, **kwargs):
            with self._workspace_context() as scope, data_activity():
                validate(scope)
                return await method(self, *args, **kwargs)
    else:

        @wraps(method)
        def call(self, *args, **kwargs):
            with self._workspace_context() as scope, data_activity():
                validate(scope)
                return method(self, *args, **kwargs)

    return call


@dataclass(slots=True)
class CapabilityAvailability:
    """Availability result for optional capabilities."""

    name: str
    available: bool
    install_hint: str = ""


class DeepTutorApp:
    """Facade around runtime, session, notebook, and capability contracts."""

    def __init__(self, *, workspace_id: str | None = None) -> None:
        self.workspace_id = workspace_id
        self._turn_workspaces: dict[str, str] = {}
        self.container = get_application_container()
        self.turns = self.container.turns
        self.capabilities = self.container.capability_registry

    def _workspace_context(self):
        from deeptutor.services.workspace.context import current_workspace_id, workspace_context

        return workspace_context(
            self.workspace_id if self.workspace_id is not None else current_workspace_id()
        )

    @property
    def notebooks(self):
        with self._workspace_context():
            return get_notebook_manager()

    def resolve_capability(self, value: str | None) -> str:
        requested = str(value or "chat").strip() or "chat"
        manifests = self.capabilities.get_manifests()
        for manifest in manifests:
            if manifest["name"] == requested:
                return requested
            aliases = {str(alias).strip() for alias in manifest.get("cli_aliases", [])}
            if requested in aliases:
                return str(manifest["name"])
        available = ", ".join(sorted(manifest["name"] for manifest in manifests))
        raise ValueError(f"Unknown capability `{requested}`. Available: {available}")

    def get_capability_contracts(self) -> list[dict[str, Any]]:
        contracts = []
        for manifest in self.capabilities.get_manifests():
            contracts.append(
                {
                    **manifest,
                    "availability": self.get_capability_availability(manifest["name"]).__dict__,
                }
            )
        return contracts

    def get_capability_contract(self, value: str) -> dict[str, Any]:
        resolved = self.resolve_capability(value)
        for manifest in self.capabilities.get_manifests():
            if manifest["name"] == resolved:
                return {
                    **manifest,
                    "availability": self.get_capability_availability(resolved).__dict__,
                }
        raise ValueError(f"Capability not found: {resolved}")

    def get_capability_availability(self, capability: str) -> CapabilityAvailability:
        resolved = self.resolve_capability(capability)
        if resolved == "math_animator":
            available = importlib.util.find_spec("manim") is not None
            return CapabilityAvailability(
                name=resolved,
                available=available,
                install_hint=(
                    ""
                    if available
                    else "Install with `pip install -e '.[math-animator]'` "
                    "or `pip install -r requirements/math-animator.txt`."
                ),
            )
        return CapabilityAvailability(name=resolved, available=True)

    async def start_turn(
        self, request: TurnRequest | dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(request, dict):
            request = TurnRequest(**request)
        await self.container.start()
        resolved_capability = self.resolve_capability(request.capability)
        from deeptutor.services.workspace.context import current_workspace_id, workspace_context

        workspace_id = (
            request.workspace_id
            if "workspace_id" in request.model_fields_set
            else self.workspace_id
        )
        if workspace_id is None:
            workspace_id = current_workspace_id()
        with workspace_context(workspace_id):
            result = await self.turns.start_turn(
                {
                    **request.to_payload(),
                    "capability": resolved_capability,
                    "workspace_id": workspace_id,
                }
            )
        self._turn_workspaces[result[1]["id"]] = workspace_id
        return result

    async def stream_turn(self, turn_id: str, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        await self.container.start()
        from deeptutor.services.workspace.context import current_workspace_id, workspace_context

        with workspace_context(
            self._turn_workspaces.get(
                turn_id,
                self.workspace_id if self.workspace_id is not None else current_workspace_id(),
            )
        ):
            async for item in self.turns.subscribe_turn(turn_id, after_seq=after_seq):
                yield item

    async def cancel_turn(self, turn_id: str) -> bool:
        await self.container.start()
        from deeptutor.services.workspace.context import current_workspace_id, workspace_context

        with workspace_context(
            self._turn_workspaces.get(
                turn_id,
                self.workspace_id if self.workspace_id is not None else current_workspace_id(),
            )
        ):
            return await self.turns.cancel_turn(turn_id)

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Deliver the user's reply to a turn paused on ``ask_user``."""
        await self.container.start()
        from deeptutor.services.workspace.context import workspace_context

        with (
            workspace_context(self._turn_workspaces[turn_id])
            if turn_id in self._turn_workspaces
            else self._workspace_context()
        ):
            return await self.turns.submit_user_reply(turn_id, text=text, answers=answers)

    @_in_app_workspace
    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        await self.container.start()
        return await self.turns.regenerate_last_turn(session_id, overrides=overrides)

    @_in_app_workspace
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        await self.container.start()
        return await self.turns.list_sessions(limit=limit, offset=offset)

    @_in_app_workspace
    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        await self.container.start()
        return await self.turns.get_session(session_id)

    @_in_app_workspace
    async def rename_session(self, session_id: str, title: str) -> bool:
        await self.container.start()
        return await self.turns.rename_session(session_id, title)

    @_in_app_workspace
    async def delete_session(self, session_id: str) -> bool:
        await self.container.start()
        return await self.turns.delete_session(session_id)

    @_in_app_workspace
    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        await self.container.start()
        return await self.turns.check_active_turn(session_id)

    @_in_app_workspace
    def list_notebooks(self) -> list[dict[str, Any]]:
        return self.notebooks.list_notebooks()

    @_in_app_workspace
    def create_notebook(
        self,
        name: str,
        description: str = "",
        *,
        color: str = "#3B82F6",
        icon: str = "book",
    ) -> dict[str, Any]:
        return self.notebooks.create_notebook(
            name=name,
            description=description,
            color=color,
            icon=icon,
        )

    @_in_app_workspace
    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        return self.notebooks.get_notebook(notebook_id)

    @_in_app_workspace
    def add_record(self, **kwargs: Any) -> dict[str, Any]:
        return self.notebooks.add_record(**kwargs)

    @_in_app_workspace
    def update_record(
        self, notebook_id: str, record_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.notebooks.update_record(notebook_id, record_id, **kwargs)

    @_in_app_workspace
    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        return self.notebooks.remove_record(notebook_id, record_id)

    @_in_app_workspace
    def get_records_by_references(
        self, notebook_references: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.notebooks.get_records_by_references(notebook_references)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
