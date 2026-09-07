"""
Unified Context
===============

A single data object that flows through the orchestrator into every
tool / capability / plugin invocation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Attachment:
    """A file or image attached to the user message."""

    type: str  # "image" | "file" | "pdf"
    url: str = ""
    base64: str = ""
    filename: str = ""
    mime_type: str = ""
    # Stable per-attachment identifier; doubles as the directory segment
    # under which the original bytes live in the AttachmentStore.
    id: str = ""
    # Plain-text rendering of binary documents (PDF/DOCX/XLSX/PPTX).
    # Populated by ``extract_documents_from_records`` so the frontend can
    # show "what the LLM saw" when previewing office files.
    extracted_text: str = ""


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeContext:
    """Resolved content workspace frozen for one turn.

    Physical paths are runtime-only.  They must never be copied into model
    messages, persisted message metadata, or public URLs.
    """

    workspace_id: str = ""
    root: str = ""
    output_dir: str = ""
    logical_output_dir: str = "outputs"
    security_level: str = "off"


@dataclass
class TurnRuntimeContext:
    """Non-serializable execution state owned by the runtime adapter."""

    turn_id: str = ""
    wait_for_user_reply: Callable[[], Awaitable[dict[str, Any] | None]] | None = None
    provider_response_state: dict[str, Any] | None = None
    subagent_consult_budget: int | None = None
    min_loop_rounds: int = 0
    workspace: WorkspaceRuntimeContext | None = None


@dataclass
class InteractionState:
    """Mutable state exchanged between the loop and interactive tools."""

    end_loop: bool = False
    user_answers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CapabilityOutput:
    """Structured terminal output published by a turn capability."""

    agent_output: str = ""
    event_metadata: dict[str, Any] = field(default_factory=dict)
    answer_published: bool = False


@dataclass
class UnifiedContext:
    """
    Everything a capability or tool needs to process a single user turn.

    Attributes:
        session_id: Persistent conversation identifier.
        user_message: The current user input.
        conversation_history: Previous messages in OpenAI format.
        enabled_tools: Tool names the user has toggled on (Level 1).
            ``None`` means "not specified", while ``[]`` means
            "explicitly disable all optional tools".
        allowed_builtin_tools: Whitelist gating the built-in auto-mounted tools
            (rag / read_memory / web_fetch / …). ``None`` (the product-chat
            default) means "no gating" — every built-in mounts under its usual
            context condition. A list restricts which built-ins may mount;
            partners set this so an owner can deny built-ins per companion.
        active_capability: Capability name selected by the user, or None for plain chat.
        knowledge_bases: KB names to use for RAG.
        attachments: Images / files sent with the message.
        config_overrides: Per-request config tweaks (e.g. temperature).
        language: UI / response language ("en" | "zh").
        memory_context: Memory snapshot text injected into the system prompt.
        persona_context: Selected persona's instructions, eagerly injected
            into the system prompt (a persona must shape the voice from the
            first token; empty when no persona is active).
        sidebar_context: High-priority grounding for an isolated sidebar tutor
            (for example, the exact passage selected in another chat).
        skills_manifest: System-prompt Skills block — one line per
            capability skill visible to this user, plus any ``always``
            skills' full bodies. The model pulls full skill content on
            demand via the ``read_skill`` tool.
        source_manifest: Plain-text manifest of attached sources (one line per
            source: id/name/type/preview). Empty when no sources are attached.
            Consumed by the chat capability to render an "Attached Sources"
            section in the system prompt and to enable the ``read_source`` tool.
        runtime: Private, non-serializable callbacks and provider state.
        interaction: Mutable user/loop interaction state.
        capability_output: Structured terminal capability output.
        extension_state: Per-extension namespaces for mutable plugin state.
        metadata: Serializable compatibility metadata. New mutable extension
            state must use ``extension_state`` instead.
    """

    session_id: str = ""
    user_message: str = ""
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    enabled_tools: list[str] | None = None
    allowed_builtin_tools: list[str] | None = None
    active_capability: str | None = None
    knowledge_bases: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    language: str = "en"
    memory_context: str = ""
    persona_context: str = ""
    sidebar_context: str = ""
    skills_manifest: str = ""
    source_manifest: str = ""
    runtime: TurnRuntimeContext = field(default_factory=TurnRuntimeContext)
    interaction: InteractionState = field(default_factory=InteractionState)
    capability_output: CapabilityOutput = field(default_factory=CapabilityOutput)
    extension_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def extension(self, namespace: str) -> dict[str, Any]:
        """Return an isolated mutable namespace for a loop extension."""

        normalized = str(namespace or "").strip()
        if not normalized:
            raise ValueError("Extension namespace must not be empty")
        return self.extension_state.setdefault(normalized, {})


__all__ = [
    "Attachment",
    "CapabilityOutput",
    "InteractionState",
    "TurnRuntimeContext",
    "UnifiedContext",
    "WorkspaceRuntimeContext",
]
