"""Additive chat capability that teaches the loop to author a Skill/Persona.

Create mode never replaces the ordinary chat tool surface — the user's web
search, attachments, KBs and model choice all behave exactly as in plain
chat — it only adds ``propose_creation`` and a kind-specific system prompt on
top. See :mod:`deeptutor.services.creations` for the kind adapters and the
draft store this capability and its tool share.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.creator.tools import CREATOR_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext

_ZH_LABELS = {"skill": "技能", "persona": "人设"}


class CreatorCapability:
    name = "creator"
    owned_tools = CREATOR_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        from deeptutor.services.creations import get_creation_kind

        # A partner turn runs inside a synthetic workspace with no review UI
        # to show a draft card in, so create mode never activates there even
        # if a stale ``create_target`` preference somehow reached the turn.
        if context.metadata.get("source") == "partner":
            return False
        return get_creation_kind(context.metadata.get("create_target")) is not None

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        _ = prompts
        from deeptutor.services.creations import CreationDraftStore, get_creation_kind

        kind = get_creation_kind(context.metadata.get("create_target"))
        if kind is None:
            return None
        lang = "zh" if str(language or "").lower().startswith("zh") else "en"
        prompt_file = resources.files(__package__).joinpath("prompts", lang, f"{kind.key}.md")
        text = prompt_file.read_text(encoding="utf-8").strip()

        tail: list[str] = []
        existing = kind.list_names(limit=60)
        if existing:
            names = ", ".join(f"`{name}`" for name in existing)
            tail.append(
                f"已使用的{_ZH_LABELS.get(kind.key, kind.label)}名称（避免冲突）：{names}"
                if lang == "zh"
                else f"Names already in use for this kind (avoid colliding): {names}"
            )
        latest = CreationDraftStore().latest_for_session(str(context.session_id or ""), kind.key)
        if latest is not None:
            if latest.status == "created":
                tail.append(
                    f"最近一次草稿已确认，保存为 `{latest.created_name}`；"
                    "如需修改，用同样的名字再次调用 propose_creation，确认会更新它而不是报冲突。"
                    if lang == "zh"
                    else (
                        f"The latest draft was approved and saved as `{latest.created_name}`; "
                        "to change it, propose again with the same name — approval will update "
                        "it instead of conflicting."
                    )
                )
            else:
                tail.append(
                    f"最近一次草稿名为 `{latest.name}`，尚未被用户确认。"
                    if lang == "zh"
                    else f"The latest draft is named `{latest.name}` and has not been approved yet."
                )
        if tail:
            text = text + "\n\n" + "\n".join(tail)
        return PromptBlock(self.name, text)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if tool_name == "propose_creation":
            kwargs["_creation_context"] = context
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        # Create mode never seeds the conversation with extra text; the
        # system block alone is enough to steer the loop.
        return ""


__all__ = ["CreatorCapability"]
