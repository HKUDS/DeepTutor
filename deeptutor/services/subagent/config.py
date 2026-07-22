"""Subagent settings — the consult budget and per-backend permission knobs.

Stored as ``data/user/settings/subagent.json`` (same convention as the other
runtime settings files). Everything has a safe default so the feature works the
moment a CLI is detected, with no configuration step required.

* ``consult_budget`` — the user-facing "max rounds": the maximum number of times
  DeepTutor may put a question to the subagent in one turn. Enforced
  authoritatively inside the consult tool; the chat loop's own round budget is
  only a safety ceiling.
* per-backend ``permission_mode`` / ``sandbox`` / ``approval`` — how the local
  agent runs non-interactively. The defaults are chosen to never stall waiting
  for an approval prompt (a headless agent that blocks on approval would hang
  the turn forever, since we wait unconditionally). A cautious user can dial
  these back; ``extra_args`` is an escape hatch for anything not modelled here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

_SETTINGS_FILE = "subagent.json"

DEFAULT_CONSULT_BUDGET = 5
CONSULT_BUDGET_MIN = 1
CONSULT_BUDGET_MAX = 12


@dataclass(slots=True)
class BackendConfig:
    enabled: bool = True
    # Model + reasoning effort the agent runs with. Empty = the CLI's own
    # default. Set from the /settings page; the option lists are synced live
    # from the CLI (models/efforts change over time). CC: --model / --effort;
    # Codex: -m / -c model_reasoning_effort.
    model: str = ""
    effort: str = ""
    # Instruction injected so the agent knows it's being consulted
    # programmatically (be concise, self-contained, don't ask follow-ups).
    # CC: --append-system-prompt. Empty = none.
    system_prompt: str = ""
    # Claude Code: --permission-mode value. "bypassPermissions" never stalls and
    # lets the agent act autonomously on the user's own machine (the explicit
    # trust model of "connect my local CLI"). Codex ignores this field.
    permission_mode: str = "bypassPermissions"
    # Codex: --sandbox / approval_policy. "workspace-write" + "never" runs
    # autonomously within the working dir without blocking on approvals.
    sandbox: str = "workspace-write"
    approval: str = "never"
    # Codex: allow model-run shell commands network access (workspace-write is
    # offline by default). The built-in web_search tool is unaffected.
    network_access: bool = False
    # Codex: --ephemeral — don't persist the session under ~/.codex/sessions.
    ephemeral: bool = False
    # Forward image attachments from the chat turn to the agent (CC image input
    # / Codex -i). Off by default — the user opts in per backend.
    forward_images: bool = False
    extra_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SubagentSettings:
    consult_budget: int = DEFAULT_CONSULT_BUDGET
    backends: dict[str, BackendConfig] = field(default_factory=dict)

    def backend(self, kind: str) -> BackendConfig:
        return self.backends.get(kind, BackendConfig())

    def to_dict(self) -> dict[str, Any]:
        return {
            "consult_budget": self.consult_budget,
            "backends": {kind: _backend_to_dict(cfg) for kind, cfg in self.backends.items()},
        }


def _backend_to_dict(cfg: BackendConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "model": cfg.model,
        "effort": cfg.effort,
        "system_prompt": cfg.system_prompt,
        "permission_mode": cfg.permission_mode,
        "sandbox": cfg.sandbox,
        "approval": cfg.approval,
        "network_access": cfg.network_access,
        "ephemeral": cfg.ephemeral,
        "forward_images": cfg.forward_images,
        "extra_args": list(cfg.extra_args),
    }


def _coerce_budget(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONSULT_BUDGET
    return max(CONSULT_BUDGET_MIN, min(CONSULT_BUDGET_MAX, n))


def _coerce_backend(raw: Any) -> BackendConfig:
    base = BackendConfig()
    if not isinstance(raw, dict):
        return base
    extra = raw.get("extra_args")
    return BackendConfig(
        enabled=bool(raw.get("enabled", base.enabled)),
        model=str(raw.get("model") or "").strip(),
        effort=str(raw.get("effort") or "").strip(),
        system_prompt=str(raw.get("system_prompt") or ""),
        permission_mode=str(raw.get("permission_mode") or base.permission_mode),
        sandbox=str(raw.get("sandbox") or base.sandbox),
        approval=str(raw.get("approval") or base.approval),
        network_access=bool(raw.get("network_access", base.network_access)),
        ephemeral=bool(raw.get("ephemeral", base.ephemeral)),
        forward_images=bool(raw.get("forward_images", base.forward_images)),
        extra_args=[str(a) for a in extra] if isinstance(extra, list) else [],
    )


def _settings_path():
    return get_path_service().get_settings_file(_SETTINGS_FILE)


def settings_from_dict(raw: Any) -> SubagentSettings:
    """Coerce an arbitrary payload (file contents or an API body) into settings."""
    backends_raw = raw.get("backends") if isinstance(raw, dict) else None
    backends: dict[str, BackendConfig] = {}
    if isinstance(backends_raw, dict):
        for kind, cfg in backends_raw.items():
            backends[str(kind)] = _coerce_backend(cfg)
    return SubagentSettings(
        consult_budget=_coerce_budget(raw.get("consult_budget") if isinstance(raw, dict) else None),
        backends=backends,
    )


def load_subagent_settings() -> SubagentSettings:
    """Read ``subagent.json``, falling back to defaults on any problem."""
    path = _settings_path()
    if not path.exists():
        return SubagentSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to read %s; using defaults", path, exc_info=True)
        return SubagentSettings()
    return settings_from_dict(raw)


def save_subagent_settings(settings: SubagentSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def get_consult_budget() -> int:
    return load_subagent_settings().consult_budget


__all__ = [
    "BackendConfig",
    "SubagentSettings",
    "DEFAULT_CONSULT_BUDGET",
    "CONSULT_BUDGET_MIN",
    "CONSULT_BUDGET_MAX",
    "settings_from_dict",
    "load_subagent_settings",
    "save_subagent_settings",
    "get_consult_budget",
]
