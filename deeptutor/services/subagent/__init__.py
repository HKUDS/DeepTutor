"""Subagent driver layer — drive a user's local agent CLI as a subagent.

DeepTutor runs on the same machine as the user's configured Claude Code / Codex,
so the backend can spawn those CLIs directly and stream back every native event.
This package is the decoupled core of that: backends that know one CLI each, a
shared streaming-subprocess primitive, and the value types that cross into the
chat capability. It knows nothing about the chat loop, KBs, or HTTP — those wire
in through the consult tool and the API.
"""

from __future__ import annotations

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import (
    CONSULT_BUDGET_MAX,
    CONSULT_BUDGET_MIN,
    DEFAULT_CONSULT_BUDGET,
    BackendConfig,
    SubagentSettings,
    get_consult_budget,
    load_subagent_settings,
    save_subagent_settings,
    settings_from_dict,
)
from deeptutor.services.subagent.partner import PARTNER_BACKEND_KIND
from deeptutor.services.subagent.registry import detect_all, get_backend, list_backend_kinds
from deeptutor.services.subagent.types import (
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

__all__ = [
    "OnEvent",
    "SubagentBackend",
    "BackendConfig",
    "SubagentSettings",
    "DEFAULT_CONSULT_BUDGET",
    "CONSULT_BUDGET_MIN",
    "CONSULT_BUDGET_MAX",
    "PARTNER_BACKEND_KIND",
    "get_consult_budget",
    "load_subagent_settings",
    "save_subagent_settings",
    "settings_from_dict",
    "detect_all",
    "get_backend",
    "list_backend_kinds",
    "ConsultResult",
    "DetectResult",
    "SubagentEvent",
]
