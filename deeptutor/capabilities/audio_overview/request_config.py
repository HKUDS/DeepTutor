"""Validated request config for the KB audio overview capability."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AudioOverviewRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(default="", max_length=500)
    target_minutes: int = Field(default=5, ge=1, le=15)
    host_voice: str = Field(default="alloy", min_length=1, max_length=64)
    expert_voice: str = Field(default="nova", min_length=1, max_length=64)
    max_context_chunks: int = Field(default=6, ge=1, le=12)


__all__ = ["AudioOverviewRequestConfig"]
