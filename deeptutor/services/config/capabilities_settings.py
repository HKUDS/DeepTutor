"""Read/write the per-capability tunables surfaced by the Settings UI.

This is the source of truth for the ``/api/v1/capabilities/settings``
endpoint. It bridges two on-disk files:

* ``data/user/settings/agents.yaml`` — per-capability LLM params
  (``temperature``, stage ``max_tokens``). Owned by
  :func:`get_chat_params` / :func:`get_agent_params` in
  :mod:`deeptutor.services.config.loader`.
* ``data/user/settings/main.yaml`` — per-capability runtime knobs that
  aren't LLM params (research's ``researching.*`` and question's
  ``exploring.*`` subtrees).

The schema we expose to the UI is a single dict so the frontend can
render one form. Saving splits the payload back into the right files.

We deliberately do not include capabilities whose pipelines do not
actually read the corresponding YAML keys today — surfacing knobs that
don't do anything would be misleading. As we lift more hardcoded
constants into settings, capabilities can be added here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from deeptutor.services.config.loader import (
    DEFAULT_CHAT_PARAMS,
    PROJECT_ROOT,
    get_runtime_settings_dir,
)
from deeptutor.utils.config_manager import ConfigManager

# ── Schema definition ────────────────────────────────────────────────────


# The keys here drive both the GET response shape and the PUT validation.
# Each capability lists its (file, sub-path) reads so we know how to
# round-trip values without disturbing unrelated YAML keys.
_AGENTS_YAML_CAPABILITY_SECTIONS: dict[str, tuple[str, ...]] = {
    "solve": ("capabilities", "solve"),
    "research": ("capabilities", "research"),
    "question": ("capabilities", "question"),
    "co_writer": ("capabilities", "co_writer"),
    "vision_solver": ("plugins", "vision_solver"),
    "math_animator": ("plugins", "math_animator"),
}

_SIMPLE_LLM_DEFAULTS: dict[str, dict[str, Any]] = {
    "solve": {"temperature": 0.3, "max_tokens": 8192},
    "research": {"temperature": 0.5, "max_tokens": 16834},
    "question": {"temperature": 0.7, "max_tokens": 4096},
    "co_writer": {"temperature": 0.6, "max_tokens": 4096},
    "vision_solver": {"temperature": 0.3, "max_tokens": 12000},
    "math_animator": {"temperature": 0.2, "max_tokens": 16834},
}

# main.yaml subtrees that capabilities read at runtime (besides LLM params).
_MAIN_YAML_RUNTIME_DEFAULTS: dict[str, dict[str, Any]] = {
    "solve": {
        # Total LLM-round budget for one solve turn (plan + tool + finish all
        # count as rounds in the flat agent loop). Higher than chat's default
        # (each plan step costs several rounds) but kept moderate so a churning
        # turn finishes naturally instead of running long enough to hit an LLM
        # timeout — raise it in settings if you want deeper solving.
        "max_rounds": 12,
        "max_replans": 2,
    },
    "research": {
        "researching": {
            "note_agent_mode": "auto",
            "tool_timeout": 60,
            "tool_max_retries": 3,
            "paper_search_years_limit": 5,
        },
    },
    "question": {
        "exploring": {
            "max_iterations": 7,
            "tool_summarizer": {
                "enabled": True,
                "max_tokens": 1024,
            },
        },
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _agents_yaml_path() -> Path:
    return get_runtime_settings_dir(PROJECT_ROOT) / "agents.yaml"


def _read_agents_yaml() -> dict[str, Any]:
    path = _agents_yaml_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_agents_yaml(data: dict[str, Any]) -> None:
    path = _agents_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _get_at(d: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    """Walk a nested dict by path, returning {} if any segment is missing."""
    node: Any = d
    for key in path:
        if not isinstance(node, dict):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, dict) else {}


def _set_at(d: dict[str, Any], path: tuple[str, ...], value: dict[str, Any]) -> None:
    """Insert ``value`` at ``path`` in ``d``, creating intermediate dicts."""
    node = d
    for key in path[:-1]:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            node[key] = nxt
        node = nxt
    node[path[-1]] = value


def _deep_merge(into: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Merge ``src`` into ``into`` recursively (keys in src win)."""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _deep_merge(into[key], value)
        else:
            into[key] = value
    return into


def _coerce_float(raw: Any, default: float, *, lo: float = 0.0, hi: float = 2.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _coerce_int(raw: Any, default: int, *, lo: int = 1, hi: int = 200_000) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _coerce_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        if raw.lower() in {"true", "1", "yes", "on"}:
            return True
        if raw.lower() in {"false", "0", "no", "off"}:
            return False
    return default


# ── Schema build / read ──────────────────────────────────────────────────


# Only the chat sub-sections actually read by ``AgenticChatPipeline.__init__``.
_CHAT_STAGES_IN_USE: tuple[str, ...] = (
    "exploring",
    "responding",
)

# Targeting-era chat keys no longer read by the pipeline; dropped on write.
_CHAT_LEGACY_KEYS: tuple[str, ...] = (
    "max_iterations",
    "max_explore_rounds",
    "max_act_rounds",
    "max_tool_steps",
    "targeting",
    "explore",
    "act",
)


def _build_chat_block(agents_cfg: dict[str, Any]) -> dict[str, Any]:
    """Read agents.yaml.capabilities.chat into the UI schema with defaults."""
    chat_cfg: dict[str, Any] = _get_at(agents_cfg, ("capabilities", "chat"))
    merged: dict[str, Any] = {}
    _deep_merge(merged, DEFAULT_CHAT_PARAMS)
    _deep_merge(merged, chat_cfg)
    return {
        "temperature": _coerce_float(merged.get("temperature"), DEFAULT_CHAT_PARAMS["temperature"]),
        "max_rounds": _coerce_int(
            merged.get("max_rounds"), DEFAULT_CHAT_PARAMS["max_rounds"], lo=1, hi=50
        ),
        "stage_budgets": {
            stage: _coerce_int(
                (merged.get(stage) or {}).get("max_tokens"),
                DEFAULT_CHAT_PARAMS[stage]["max_tokens"],
                lo=1,
                hi=200_000,
            )
            for stage in _CHAT_STAGES_IN_USE
        },
    }


def _build_simple_llm_block(agents_cfg: dict[str, Any], capability: str) -> dict[str, Any]:
    defaults = _SIMPLE_LLM_DEFAULTS[capability]
    section = _get_at(agents_cfg, _AGENTS_YAML_CAPABILITY_SECTIONS[capability])
    return {
        "temperature": _coerce_float(section.get("temperature"), defaults["temperature"]),
        "max_tokens": _coerce_int(section.get("max_tokens"), defaults["max_tokens"]),
    }


def _build_main_runtime_block(main_cfg: dict[str, Any], capability: str) -> dict[str, Any]:
    defaults = _MAIN_YAML_RUNTIME_DEFAULTS.get(capability)
    if defaults is None:
        return {}
    if capability == "solve":
        solve_cfg = _get_at(main_cfg, ("capabilities", "solve"))
        # The pre-flat-loop ``max_iterations_per_step`` key was inert, so a stale
        # value is intentionally ignored — only the new ``max_rounds`` counts,
        # otherwise everyone would silently inherit the old (too-low) number.
        return {
            "max_rounds": _coerce_int(
                solve_cfg.get("max_rounds"),
                defaults["max_rounds"],
                lo=1,
                hi=50,
            ),
            "max_replans": _coerce_int(
                solve_cfg.get("max_replans"),
                defaults["max_replans"],
                lo=0,
                hi=10,
            ),
        }
    if capability == "research":
        researching_cfg = _get_at(main_cfg, ("capabilities", "research", "researching"))
        d = defaults["researching"]
        return {
            "researching": {
                "note_agent_mode": str(
                    researching_cfg.get("note_agent_mode") or d["note_agent_mode"]
                ),
                "tool_timeout": _coerce_int(
                    researching_cfg.get("tool_timeout"), d["tool_timeout"], lo=1, hi=600
                ),
                "tool_max_retries": _coerce_int(
                    researching_cfg.get("tool_max_retries"), d["tool_max_retries"], lo=0, hi=10
                ),
                "paper_search_years_limit": _coerce_int(
                    researching_cfg.get("paper_search_years_limit"),
                    d["paper_search_years_limit"],
                    lo=1,
                    hi=50,
                ),
            },
        }
    if capability == "question":
        exploring_cfg = _get_at(main_cfg, ("capabilities", "question", "exploring"))
        d = defaults["exploring"]
        summarizer_cfg = (
            exploring_cfg.get("tool_summarizer")
            if isinstance(exploring_cfg.get("tool_summarizer"), dict)
            else {}
        )
        return {
            "exploring": {
                "max_iterations": _coerce_int(
                    exploring_cfg.get("max_iterations"), d["max_iterations"], lo=1, hi=50
                ),
                "tool_summarizer": {
                    "enabled": _coerce_bool(
                        summarizer_cfg.get("enabled"), d["tool_summarizer"]["enabled"]
                    ),
                    "max_tokens": _coerce_int(
                        summarizer_cfg.get("max_tokens"), d["tool_summarizer"]["max_tokens"]
                    ),
                },
            },
        }
    return {}


def capabilities_settings_dict() -> dict[str, Any]:
    """Return the full schema as a JSON-safe dict (defaults merged in)."""
    agents_cfg = _read_agents_yaml()
    main_cfg = ConfigManager().load_config()

    result: dict[str, Any] = {"chat": _build_chat_block(agents_cfg)}
    for cap in _AGENTS_YAML_CAPABILITY_SECTIONS:
        block = _build_simple_llm_block(agents_cfg, cap)
        block.update(_build_main_runtime_block(main_cfg, cap))
        result[cap] = block
    return result


# ── Write path ───────────────────────────────────────────────────────────


def _apply_chat_into_agents_yaml(agents_cfg: dict[str, Any], block: dict[str, Any]) -> None:
    current = _get_at(agents_cfg, ("capabilities", "chat"))
    new_chat: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    new_chat.pop("answer_now", None)
    for legacy_key in _CHAT_LEGACY_KEYS:
        new_chat.pop(legacy_key, None)
    if "temperature" in block:
        new_chat["temperature"] = _coerce_float(
            block.get("temperature"), DEFAULT_CHAT_PARAMS["temperature"]
        )
    if "max_rounds" in block:
        new_chat["max_rounds"] = _coerce_int(
            block.get("max_rounds"), DEFAULT_CHAT_PARAMS["max_rounds"], lo=1, hi=50
        )
    stage_budgets = block.get("stage_budgets") or {}
    if isinstance(stage_budgets, dict):
        for stage, default_sub in DEFAULT_CHAT_PARAMS.items():
            if not isinstance(default_sub, dict):
                continue
            if stage in stage_budgets:
                existing = new_chat.get(stage) if isinstance(new_chat.get(stage), dict) else {}
                existing = dict(existing)
                existing["max_tokens"] = _coerce_int(
                    stage_budgets[stage], default_sub["max_tokens"], lo=1, hi=200_000
                )
                new_chat[stage] = existing
    _set_at(agents_cfg, ("capabilities", "chat"), new_chat)


def _apply_simple_llm_into_agents_yaml(
    agents_cfg: dict[str, Any], capability: str, block: dict[str, Any]
) -> None:
    defaults = _SIMPLE_LLM_DEFAULTS[capability]
    section_path = _AGENTS_YAML_CAPABILITY_SECTIONS[capability]
    current = _get_at(agents_cfg, section_path)
    new_section: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    if "temperature" in block:
        new_section["temperature"] = _coerce_float(
            block.get("temperature"), defaults["temperature"]
        )
    if "max_tokens" in block:
        new_section["max_tokens"] = _coerce_int(block.get("max_tokens"), defaults["max_tokens"])
    _set_at(agents_cfg, section_path, new_section)


def _apply_main_runtime(
    main_payload: dict[str, Any], capability: str, block: dict[str, Any]
) -> None:
    defaults = _MAIN_YAML_RUNTIME_DEFAULTS.get(capability)
    if defaults is None:
        return
    if capability == "solve":
        solve_section: dict[str, Any] = {}
        if "max_rounds" in block:
            solve_section["max_rounds"] = _coerce_int(
                block.get("max_rounds"),
                defaults["max_rounds"],
                lo=1,
                hi=50,
            )
        if "max_replans" in block:
            solve_section["max_replans"] = _coerce_int(
                block.get("max_replans"),
                defaults["max_replans"],
                lo=0,
                hi=10,
            )
        if solve_section:
            main_payload.setdefault("capabilities", {})["solve"] = solve_section
    if capability == "research" and isinstance(block.get("researching"), dict):
        d = defaults["researching"]
        r = block["researching"]
        main_payload.setdefault("capabilities", {}).setdefault("research", {})["researching"] = {
            "note_agent_mode": str(r.get("note_agent_mode") or d["note_agent_mode"]),
            "tool_timeout": _coerce_int(r.get("tool_timeout"), d["tool_timeout"], lo=1, hi=600),
            "tool_max_retries": _coerce_int(
                r.get("tool_max_retries"), d["tool_max_retries"], lo=0, hi=10
            ),
            "paper_search_years_limit": _coerce_int(
                r.get("paper_search_years_limit"), d["paper_search_years_limit"], lo=1, hi=50
            ),
        }
    if capability == "question" and isinstance(block.get("exploring"), dict):
        d = defaults["exploring"]
        e = block["exploring"]
        sm = e.get("tool_summarizer") if isinstance(e.get("tool_summarizer"), dict) else {}
        main_payload.setdefault("capabilities", {}).setdefault("question", {})["exploring"] = {
            "max_iterations": _coerce_int(
                e.get("max_iterations"), d["max_iterations"], lo=1, hi=50
            ),
            "tool_summarizer": {
                "enabled": _coerce_bool(sm.get("enabled"), d["tool_summarizer"]["enabled"]),
                "max_tokens": _coerce_int(sm.get("max_tokens"), d["tool_summarizer"]["max_tokens"]),
            },
        }


def save_capabilities_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge ``payload`` into both YAML files and return the new state.

    Unknown keys are dropped; values are coerced + clamped via the helpers
    above so the YAML cannot pick up junk.
    """
    agents_cfg = _read_agents_yaml()
    main_payload: dict[str, Any] = {}

    if isinstance(payload.get("chat"), dict):
        _apply_chat_into_agents_yaml(agents_cfg, payload["chat"])

    for cap in _AGENTS_YAML_CAPABILITY_SECTIONS:
        block = payload.get(cap)
        if not isinstance(block, dict):
            continue
        _apply_simple_llm_into_agents_yaml(agents_cfg, cap, block)
        _apply_main_runtime(main_payload, cap, block)

    _write_agents_yaml(agents_cfg)
    if main_payload:
        ConfigManager().save_config(main_payload)
    return capabilities_settings_dict()


def get_solve_params() -> dict[str, Any]:
    """Runtime solve params, read through the same coerce path as the UI.

    Combines the two storage locations the solve settings page writes to:
    ``temperature`` / ``max_tokens`` (agents.yaml) and ``max_rounds`` /
    ``max_replans`` (main config). This is the single source the deep-solve
    capability forwards into the chat agent loop, so the settings page actually
    drives the loop instead of being inert.
    """
    agents_cfg = _read_agents_yaml()
    main_cfg = ConfigManager().load_config()
    llm = _build_simple_llm_block(agents_cfg, "solve")
    runtime = _build_main_runtime_block(main_cfg, "solve")
    return {**llm, **runtime}


__all__ = [
    "capabilities_settings_dict",
    "get_solve_params",
    "save_capabilities_settings",
]
