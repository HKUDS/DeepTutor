"""Credential-free configuration contracts for native LightRAG roles.

Parsing these contracts never resolves a model or mutates the model catalog.
Runtime resolution stays in the LightRAG adapter so settings can be loaded even
when an optional provider is not installed.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "adaptive"]


class LightRagModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profile_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    reasoning_effort: ReasoningEffort | None = None


class LightRagRoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["inherit", "model"] = "inherit"
    selection: LightRagModelSelection | None = None
    reasoning_effort: ReasoningEffort | None = None
    max_async: int = Field(default=4, ge=1, le=32, strict=True)
    timeout: int = Field(default=240, ge=1, le=3600, strict=True)

    @model_validator(mode="after")
    def check_selection(self) -> Self:
        if (self.mode == "model") != (self.selection is not None):
            raise ValueError("Only an explicit model role requires a model selection.")
        if self.selection is not None and self.selection.reasoning_effort is not None:
            raise ValueError("Set role reasoning_effort on the role, not its model selection.")
        return self


class LightRagVisionModel(LightRagRoleModel):
    mode: Literal["disabled", "inherit", "model"] = "disabled"

    @model_validator(mode="after")
    def check_disabled(self) -> Self:
        if self.mode == "disabled" and self.reasoning_effort is not None:
            raise ValueError("A disabled vision role cannot override reasoning effort.")
        return self


class LightRagRoleModels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: LightRagModelSelection
    extract: LightRagRoleModel = Field(default_factory=LightRagRoleModel)
    keyword: LightRagRoleModel = Field(default_factory=LightRagRoleModel)
    query: LightRagRoleModel = Field(default_factory=LightRagRoleModel)
    vlm: LightRagVisionModel = Field(default_factory=LightRagVisionModel)

    def selection_for(self, role: str) -> LightRagModelSelection | None:
        override = getattr(self, role)
        if override.mode == "disabled":
            return None
        selected = override.selection or self.base
        if override.reasoning_effort is not None:
            selected = selected.model_copy(update={"reasoning_effort": override.reasoning_effort})
        return selected


class LightRagIndexingVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["disabled", "enabled"] = "disabled"
    selection: LightRagModelSelection | None = None

    @model_validator(mode="after")
    def check_selection(self) -> Self:
        if (self.mode == "enabled") != (self.selection is not None):
            raise ValueError("Only enabled vision indexing requires a model selection.")
        return self


class LightRagIndexingSelection(BaseModel):
    """Resolved create/rebuild overrides, without mutable engine inheritance."""

    model_config = ConfigDict(extra="forbid")

    extract: LightRagModelSelection
    vlm: LightRagIndexingVision = Field(default_factory=LightRagIndexingVision)
