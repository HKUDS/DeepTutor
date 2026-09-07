"""Typed turn request value object shared by application and runtime layers."""

from __future__ import annotations

from typing import Any, Literal
import warnings

from pydantic import BaseModel, ConfigDict, Field, model_validator

_LEGACY_RUNTIME_CONFIG_KEYS: dict[str, str] = {
    "_persist_user_message": "persist_user_message",
    "_regenerate": "regenerate",
    "_regenerated_from_message_id": "regenerated_from_message_id",
    "_superseded_turn_id": "superseded_turn_id",
    "followup_question_context": "followup_question_context",
    "selection_tutor_context": "selection_tutor_context",
    "_course_id": "course_id",
    "subagent_consult_budget": "subagent_consult_budget",
    "auto_route": "auto_route",
}


class LLMSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    model_id: str


class OutgoingAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    url: str | None = None
    base64: str | None = None
    filename: str | None = None
    mime_type: str | None = None


class NotebookReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notebook_id: str
    record_ids: list[str] = Field(default_factory=list)


class BookReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str
    page_ids: list[str] = Field(default_factory=list)


class ReadingReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str
    revision: int = Field(ge=1)
    locators: list[int] = Field(default_factory=list)


class ReadingViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: int | None = Field(default=None, ge=0)
    selection: str | None = None


class TimedMediaViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_seconds: float = Field(ge=0)


class MasteryCardAnswer(BaseModel):
    """An answer submitted from a mastery question card.

    The card outlives the turn that posed it — posing a question ends that
    turn — so the answer arrives as the next turn's message. This says which
    question the message is answering, letting the runtime commit it to the
    engine before the tutor's first token instead of asking the model to
    recover the pairing from prose.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class MasteryCardSkip(BaseModel):
    """A question the learner dropped instead of answering.

    The same shape of problem as :class:`MasteryCardAnswer`: the card outlives
    the turn that posed it, so "not this one" also arrives as the next turn's
    message. Naming the question is what keeps the runtime from abandoning
    whatever happens to be open by the time the turn starts.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)


MemoryReference = Literal["recent", "profile", "scope", "preferences", "summary"]


class TurnRequest(BaseModel):
    """Validated turn input; ``config`` contains capability options only.

    The model keeps the historical keyword construction style. Runtime-only
    keys nested in ``config`` are translated for one major version so older
    clients continue to work while receiving a deprecation warning.
    """

    model_config = ConfigDict(extra="forbid")

    content: str
    capability: str | None = "chat"
    session_id: str | None = None
    tools: list[str] | None = None
    knowledge_bases: list[str] = Field(default_factory=list)
    language: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    notebook_references: list[NotebookReference] = Field(default_factory=list)
    history_references: list[str] = Field(default_factory=list)
    partner_group_references: list[dict[str, Any]] = Field(default_factory=list)
    question_notebook_references: list[int] = Field(default_factory=list)
    book_references: list[BookReference] = Field(default_factory=list)
    reading_references: list[ReadingReference] = Field(default_factory=list)
    memory_references: list[MemoryReference] = Field(default_factory=list)
    attachments: list[OutgoingAttachment] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    persona: str | None = None
    llm_selection: LLMSelection | None = None
    workspace_mode: str | None = None
    mastery_path_id: str | None = None
    #: What this mastery conversation is for — "outline" | "study" | "review".
    #: Durable session state (see
    #: :mod:`deeptutor.capabilities.mastery.mode`); an absent value is
    #: read as the ordinary study session every mastery conversation was
    #: before kinds existed.
    mastery_session_mode: str | None = None
    mastery_path_lease_managed: bool = False
    mastery_answer: MasteryCardAnswer | None = None
    mastery_skip: MasteryCardSkip | None = None
    reading_material_id: str | None = None
    reading_material_revision: int | None = Field(default=None, ge=1)
    reading_workspace_id: str | None = None
    reading_viewport: ReadingViewport | None = None
    timed_media_id: str | None = None
    timed_media_viewport: TimedMediaViewport | None = None
    parent_message_id: int | None = None

    # Runtime options are explicit and never passed to a capability schema.
    course_id: str | None = None
    persist_user_message: bool = True
    regenerate: bool = False
    regenerated_from_message_id: int | None = None
    superseded_turn_id: str | None = None
    followup_question_context: dict[str, Any] | None = None
    selection_tutor_context: dict[str, Any] | None = None
    subagent_consult_budget: int | None = Field(default=None, ge=0)
    auto_route: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_runtime_config(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        config = result.get("config")
        if config is None or not isinstance(config, dict):
            return result
        public_config = dict(config)
        translated: list[str] = []
        for legacy_key, field_name in _LEGACY_RUNTIME_CONFIG_KEYS.items():
            if legacy_key not in public_config:
                continue
            legacy_value = public_config.pop(legacy_key)
            if field_name not in result:
                result[field_name] = legacy_value
            translated.append(legacy_key)
        result["config"] = public_config
        if translated:
            warnings.warn(
                "Runtime turn options in config are deprecated; use explicit TurnRequest "
                f"fields instead ({', '.join(sorted(translated))})",
                DeprecationWarning,
                stacklevel=3,
            )
        return result

    def to_payload(self) -> dict[str, Any]:
        """Return an execution payload while preserving omitted-field semantics."""

        return self.model_dump(mode="python", exclude_unset=True)


__all__ = [
    "BookReference",
    "LLMSelection",
    "MasteryCardAnswer",
    "MasteryCardSkip",
    "MemoryReference",
    "NotebookReference",
    "OutgoingAttachment",
    "ReadingReference",
    "ReadingViewport",
    "TimedMediaViewport",
    "TurnRequest",
]
