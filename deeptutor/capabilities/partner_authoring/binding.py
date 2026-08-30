"""Objective intent gate for chat-native Partner profile authoring."""

from __future__ import annotations

import re

from deeptutor.core.context import UnifiedContext

PARTNER_AUTHORING_CAPABILITY_NAME = "partner_authoring"

_ACTION = re.compile(
    r"(创建|新建|生成|设计|定制|做一个|来一个|来个|想要|需要|帮我做|帮我建|加一个)"
    r"|(\bcreate\b|\bmake\b|\bbuild\b|\bdesign\b|\bgenerate\b|\bwant\b|\bneed\b|\badd\b)",
    re.IGNORECASE,
)
_OBJECT = re.compile(
    r"(partner|伙伴|学习搭子|陪伴者|陪练|助教|导师|教练|学伴|智能体|角色)"
    r"|(\bcompanion\b|\btutor\b|\bmentor\b|\bcoach\b|\bstudy buddy\b)",
    re.IGNORECASE,
)


def is_partner_authoring_turn(context: UnifiedContext) -> bool:
    # Home/product Chat owns the review card and confirmation flow. A Partner
    # (including one running inside a Group) must not create drafts inside its
    # synthetic workspace merely because someone talks about another Partner.
    if context.metadata.get("source") == "partner":
        return False
    if context.active_capability == PARTNER_AUTHORING_CAPABILITY_NAME:
        return True
    text = str(context.user_message or "")
    return bool(_ACTION.search(text) and _OBJECT.search(text))


__all__ = ["PARTNER_AUTHORING_CAPABILITY_NAME", "is_partner_authoring_turn"]
