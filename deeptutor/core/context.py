"""
Unified Context
===============

A single data object that flows through the orchestrator into every
tool / capability / plugin invocation.
"""

from __future__ import annotations

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
        skills_manifest: System-prompt Skills block — one line per
            capability skill visible to this user, plus any ``always``
            skills' full bodies. The model pulls full skill content on
            demand via the ``read_skill`` tool.
        source_manifest: Plain-text manifest of attached sources (one line per
            source: id/name/type/preview). Empty when no sources are attached.
            Consumed by the chat capability to render an "Attached Sources"
            section in the system prompt and to enable the ``read_source`` tool.
        metadata: Catch-all for capability-specific extras.
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
    skills_manifest: str = ""
    source_manifest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
