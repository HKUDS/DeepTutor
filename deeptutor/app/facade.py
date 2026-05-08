"""Stable application-layer facade for DeepTutor entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from typing import Any, AsyncIterator

from deeptutor.runtime.registry.capability_registry import get_capability_registry
from deeptutor.services.notebook import get_notebook_manager
from deeptutor.services.session import get_session_store, get_turn_runtime_manager


@dataclass(slots=True)
class TurnRequest:
    """Stable turn payload used by adapters such as the CLI package."""

    content: str
    capability: str = "chat"
    session_id: str | None = None
    tools: list[str] = field(default_factory=list)
    knowledge_bases: list[str] = field(default_factory=list)
    language: str = "en"
    config: dict[str, Any] = field(default_factory=dict)
    notebook_references: list[dict[str, Any]] = field(default_factory=list)
    history_references: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "capability": self.capability,
            "session_id": self.session_id,
            "tools": list(self.tools),
            "knowledge_bases": list(self.knowledge_bases),
            "language": self.language,
            "config": dict(self.config),
            "notebook_references": list(self.notebook_references),
            "history_references": list(self.history_references),
            "attachments": list(self.attachments),
            "skills": list(self.skills),
        }


@dataclass(slots=True)
class CapabilityAvailability:
    """Availability result for optional capabilities."""

    name: str
    available: bool
    install_hint: str = ""


class DeepTutorApp:
    """Facade around runtime, session, notebook, and capability contracts."""

    def __init__(self) -> None:
        self.runtime = get_turn_runtime_manager()
        self.store = get_session_store()
        self.notebooks = get_notebook_manager()
        self.capabilities = get_capability_registry()

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
        resolved_capability = self.resolve_capability(request.capability)
        session, turn = await self.runtime.start_turn(
            {
                **request.to_payload(),
                "capability": resolved_capability,
            }
        )
        await self.store.update_session_preferences(
            session["id"],
            {
                "language": request.language,
                "notebook_references": request.notebook_references,
                "history_references": request.history_references,
            },
        )
        return session, turn

    async def stream_turn(self, turn_id: str, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        async for item in self.runtime.subscribe_turn(turn_id, after_seq=after_seq):
            yield item

    async def cancel_turn(self, turn_id: str) -> bool:
        return await self.runtime.cancel_turn(turn_id)

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await self.runtime.regenerate_last_turn(session_id, overrides=overrides)

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return await self.store.list_sessions(limit=limit, offset=offset)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self.store.get_session_with_messages(session_id)

    async def rename_session(self, session_id: str, title: str) -> bool:
        return await self.store.update_session_title(session_id, title)

    async def delete_session(self, session_id: str) -> bool:
        return await self.store.delete_session(session_id)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        return await self.store.get_active_turn(session_id)

    def list_notebooks(self) -> list[dict[str, Any]]:
        return self.notebooks.list_notebooks()

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

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        return self.notebooks.get_notebook(notebook_id)

    def add_record(self, **kwargs: Any) -> dict[str, Any]:
        return self.notebooks.add_record(**kwargs)

    def update_record(
        self, notebook_id: str, record_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.notebooks.update_record(notebook_id, record_id, **kwargs)

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        return self.notebooks.remove_record(notebook_id, record_id)

    def get_records_by_references(
        self, notebook_references: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.notebooks.get_records_by_references(notebook_references)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
