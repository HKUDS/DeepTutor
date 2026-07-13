"""Subagent loop capability — consult the user's live local agent as a delegate.

Active whenever the user's selected knowledge base is a connected subagent
(resolved by :mod:`deeptutor.capabilities.subagent.binding`). As a
:class:`KnowledgeCapability` it owns the turn: the chat loop runs exclusively on
the single ``consult_subagent`` tool (plus the ``ask_user`` floor). The chat
model decides what to ask, asks the local Claude Code / Codex up to the consult
budget, watches its streamed run, and then answers the user in its own voice.

The connection (which backend, working dir), the per-backend config and the
turn-scoped budget/session state are injected into each tool call server-side;
the model never supplies them.
"""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.protocol import KnowledgeCapability, PromptBlock
from deeptutor.capabilities.subagent.binding import connection_for_turn
from deeptutor.capabilities.subagent.tools import SUBAGENT_TOOL_NAMES
from deeptutor.core.context import UnifiedContext

# Headroom over the consult budget so the loop always has rounds left to write
# the final answer after the last consult. Read by the pipeline via
# ``context.metadata["_min_loop_rounds"]`` (a generic seam, like solve's
# ``solve_max_replans``) so a high budget is never clipped by the default round
# budget.
_FINISH_HEADROOM = 2


class SubagentCapability(KnowledgeCapability):
    """Turn-scoped integration for a connected local subagent."""

    name = "subagent"
    owned_tools = SUBAGENT_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return connection_for_turn(context) is not None

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        conn = connection_for_turn(context)
        if conn is None:
            return None
        budget = _resolve_budget(context)
        # Ensure the loop has room for ``budget`` consults plus the answer. This
        # runs once during prompt assembly, before the loop reads its round
        # budget — see ``_FINISH_HEADROOM``.
        context.metadata["_min_loop_rounds"] = budget + _FINISH_HEADROOM
        return PromptBlock(
            "subagent", _system_text(language, conn["name"], budget, conn.get("kind", ""))
        )

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name not in SUBAGENT_TOOL_NAMES:
            return kwargs
        conn = connection_for_turn(context)
        if conn is None:
            return kwargs
        from deeptutor.services.subagent import load_subagent_settings
        from deeptutor.services.subagent.sessions import get_session, session_key

        settings = load_subagent_settings()
        # Turn-scoped, mutable: persists across the loop's rounds via the shared
        # context object — the consult counter and the backend session id that
        # threads context across the model's successive questions.
        state = context.metadata.setdefault(
            "_subagent_state",
            {"count": 0, "session_id": None, "name": conn["name"]},
        )
        # Persistent continuity: on the first consult of a turn, seed the session
        # id from the cross-turn registry so we resume the SAME local agent
        # session the user/DeepTutor built up earlier (and the sidebar shares).
        chat_sid = str(getattr(context, "session_id", "") or "")
        skey = session_key(chat_sid, conn["name"]) if chat_sid else ""
        if skey and not state.get("_seeded"):
            state["_seeded"] = True
            if not state.get("session_id"):
                state["session_id"] = get_session(skey)
        config = _effective_config(settings.backend(conn["kind"]))
        # Multimodal: forward the turn's image attachments only when the user
        # opted this backend in (/settings → forward_images). The tool
        # materializes them to files the CLI can ingest.
        images = (
            [a for a in (context.attachments or []) if getattr(a, "type", "") == "image"]
            if getattr(config, "forward_images", False)
            else []
        )
        updated = dict(kwargs)
        updated["_subagent"] = {
            "kind": conn["kind"],
            "cwd": conn.get("cwd") or "",
            "partner_id": conn.get("partner_id") or "",
            "name": conn["name"],
            "budget": _resolve_budget(context),
            "config": config,
            "state": state,
            "images": images,
            "session_key": skey,
        }
        return updated

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


# Default instruction injected (CC --append-system-prompt) so a consulted agent
# behaves like a delegate, not an interactive session, when the user hasn't set
# their own in /settings.
_DEFAULT_CONSULT_INSTRUCTION = (
    "You are being consulted programmatically by DeepTutor on the user's behalf, "
    "not in an interactive terminal. Answer the question directly, concisely, and "
    "self-contained. Do not ask the user follow-up questions or wait for input; "
    "if something is ambiguous, state your assumption and proceed."
)


def _effective_config(config):
    """Fill product defaults the user hasn't overridden in /settings.

    Today: a default ``system_prompt`` so the consulted agent knows it's a
    delegate (applied by backends that support it, e.g. Claude Code).
    """
    if config.system_prompt.strip():
        return config
    from dataclasses import replace

    return replace(config, system_prompt=_DEFAULT_CONSULT_INSTRUCTION)


def _resolve_budget(context: UnifiedContext) -> int:
    """Consult budget for this turn: a per-turn override from the chat composer
    (``config.subagent_consult_budget``) if present, else the configured default.
    """
    from deeptutor.services.subagent import load_subagent_settings
    from deeptutor.services.subagent.config import CONSULT_BUDGET_MAX, CONSULT_BUDGET_MIN

    overrides = context.config_overrides if isinstance(context.config_overrides, dict) else {}
    raw = overrides.get("subagent_consult_budget")
    if raw is not None:
        try:
            return max(CONSULT_BUDGET_MIN, min(CONSULT_BUDGET_MAX, int(raw)))
        except (TypeError, ValueError):
            pass
    return load_subagent_settings().consult_budget


def _system_text(language: str, name: str, budget: int, kind: str = "") -> str:
    from deeptutor.services.subagent import PARTNER_BACKEND_KIND

    is_partner = kind == PARTNER_BACKEND_KIND
    zh = str(language or "en").lower().startswith("zh")
    if zh:
        if is_partner:
            framing = (
                f"本轮你已连接到用户的伙伴「{name}」——一个有自己人格、知识库与技能的助手。你可以通过 "
                f"`consult_subagent` 工具向它咨询，把它当作一位独立的同事来求助（例如借助它专属的知识库"
                f"或视角来回答）。你们的往来会作为一个完整会话归档到该伙伴的历史里，它的回复过程会实时展示给用户。"
            )
        else:
            framing = (
                f"本轮你已连接到用户本机的外部智能体「{name}」。你可以通过 `consult_subagent` "
                f"工具向它提问，把它当作一个能在用户机器上读写文件、运行命令的得力助手来委派任务"
                f"（例如排查代码库、复现问题、运行脚本）。它的完整运行过程会实时展示给用户。"
            )
        return (
            f"{framing}\n\n"
            f"- 本轮最多可向它提问 {budget} 次；每次结果会告诉你还剩几次。它会在本轮内记住你"
            f"之前的提问，所以可以层层追问。\n"
            f"- 当你掌握了足够信息后，停止调用该工具，用你自己的口吻直接回答用户——"
            f"不要假借它的身份或第一人称转述它的话。"
        )
    if is_partner:
        framing = (
            f"You are connected this turn to the user's partner “{name}” — a companion "
            f"with its own persona, library and skills. Consult it with the "
            f"`consult_subagent` tool as you would an independent colleague (e.g. for "
            f"its dedicated knowledge or perspective). Your exchange is archived as one "
            f"complete session in that partner's history, and its reply is shown to the "
            f"user live."
        )
    else:
        framing = (
            f"You are connected this turn to the user's local external agent “{name}”. "
            f"Consult it with the `consult_subagent` tool, delegating work it is better "
            f"placed to do on the user's machine — inspecting a codebase, reproducing a "
            f"bug, running commands. Its full run is shown to the user live."
        )
    return (
        f"{framing}\n\n"
        f"- You may consult it at most {budget} time(s) this turn; each result tells "
        f"you how many remain. It remembers your earlier questions this turn, so you "
        f"can drill down.\n"
        f"- Once you have enough, stop calling the tool and answer the user directly "
        f"in your own voice — never impersonate it or relay its words in the first "
        f"person."
    )


__all__ = ["SubagentCapability"]
