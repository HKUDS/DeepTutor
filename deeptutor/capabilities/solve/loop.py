"""Deep Solve loop-capability hooks.

Solve runs as the chat agent loop with a deterministic spine: a committed plan,
a per-step done gate, and a bounded replan (the SolveSession + three owned
tools), while the actual problem-solving happens at the loop's exit using the
shared built-in tools. Active only when the turn is marked ``solve_mode`` by
:class:`deeptutor.capabilities.solve.capability.DeepSolveCapability`.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.capabilities.solve.session import DEFAULT_MAX_REPLANS, get_session
from deeptutor.capabilities.solve.tools import SOLVE_TOOL_NAMES
from deeptutor.core.context import UnifiedContext


class SolveLoopCapability:
    """Turn-scoped integration for deep problem solving.

    Reuses the full chat tool surface — every built-in, with the user's
    composer toggles respected (web_search / reason / geogebra_analysis mount
    iff the user enabled them, exactly as in chat) — and adds the solve spine
    (plan / finish-step / replan) on top.
    """

    name = "solve"
    owned_tools = SOLVE_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("solve_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("solve", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("deep_solve", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if self.is_active(context) and tool_name in SOLVE_TOOL_NAMES:
            session_id = str(context.metadata.get("solve_session_id") or "").strip()
            # Seed the replan budget from the solve settings (the solve
            # capability forwards ``max_replans`` into metadata); never the model.
            session = get_session(session_id)
            try:
                session.max_replans = int(
                    context.metadata.get("solve_max_replans", DEFAULT_MAX_REPLANS)
                )
            except (TypeError, ValueError):
                session.max_replans = DEFAULT_MAX_REPLANS
            updated = dict(kwargs)
            updated["_solve_session_id"] = session_id
            return updated
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["SolveLoopCapability"]
