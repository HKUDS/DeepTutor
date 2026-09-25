"""Objective intent gate for chat-native Partner profile authoring."""

from __future__ import annotations

import re

from deeptutor.core.context import UnifiedContext

PARTNER_AUTHORING_CAPABILITY_NAME = "partner_authoring"

# The action has to lead into the Partner object within one clause. Matching the two words
# anywhere in the message fired on turns that only mention a Partner ("I want to file an issue
# about the Partner bug"), and finish_instruction then forces a draft the user never asked for.
_ZH_ACTION = (
    r"(?:创建|新建|生成|设计|定制|帮我做|帮我建|做一个|来一个|来个|加一个"
    r"|(?:想要|需要)(?:一个|一位|个|位))"
)
_ZH_OBJECT = r"(?:partner|伙伴|学习搭子|陪伴者|陪练|助教|导师|教练|学伴|智能体|角色)"
# Stops at clause punctuation and at words that make the object a topic rather than the target.
_ZH_GAP = r"(?:(?!关于|有关|提到|讨论)[^。！？!?；;，,、\n]){0,16}?"
_EN_ACTION = (
    r"(?:\b(?:create|make|build|design|generate|add|set\s+up)\b(?:\s+(?:me|us))?"
    r"|\b(?:want|need)\b)"
)
_EN_DETERMINER = r"\s+(?:a|an|another|one|my\s+own|our\s+own|a\s+new|new)\b"
_EN_GAP = r"(?:\s+(?!(?:about|with|for|of|from|in|on|to|that|which)\b)[\w'-]+){0,3}?"
_EN_OBJECT = r"\s+(?:partners?|companions?|tutors?|mentors?|coach(?:es)?|study\s+budd(?:y|ies))\b"

_AUTHORING_REQUEST = re.compile(
    rf"{_ZH_ACTION}{_ZH_GAP}{_ZH_OBJECT}|{_EN_ACTION}{_EN_DETERMINER}{_EN_GAP}{_EN_OBJECT}",
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
    return _AUTHORING_REQUEST.search(text) is not None


__all__ = ["PARTNER_AUTHORING_CAPABILITY_NAME", "is_partner_authoring_turn"]
