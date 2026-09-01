"""Shared language directives for prompt-driven LLM calls.

This helper centralizes the "stay in the requested language" instruction so
different modules can share the same behavior without depending on book-only
utilities.
"""

from __future__ import annotations

import re

_LANGUAGE_LABELS: dict[str, str] = {
    "zh": "中文（简体）",
    "zh-cn": "中文（简体）",
    "zh-tw": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "ru": "Русский",
    "pt": "Português",
    "it": "Italiano",
}

# Picker order for reply language. ``zh-cn`` is an alias of ``zh``, not a
# separate option. Any other BCP-47-shaped code is still accepted at write time.
RESPONSE_LANGUAGE_CHOICES: tuple[str, ...] = (
    "en",
    "zh",
    "zh-tw",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "ru",
    "pt",
    "it",
)

_RESPONSE_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8}){0,2}$")
_RESPONSE_LANGUAGE_CODE_MAX_LEN = 16


def is_response_language_code(language: str | None) -> bool:
    """True for a compact BCP-47-like code the reply-language setting can store."""
    if not isinstance(language, str):
        return False
    code = language.strip().lower()
    if not code or len(code) > _RESPONSE_LANGUAGE_CODE_MAX_LEN:
        return False
    return _RESPONSE_LANGUAGE_CODE_RE.fullmatch(code) is not None


def normalize_language(language: str | None) -> str:
    return (language or "en").strip().lower() or "en"


def prompt_locale(language: str | None) -> str:
    """Return the prompt-file locale (en/zh). Other codes reuse English YAML."""
    code = normalize_language(language)
    return "zh" if code.startswith("zh") else "en"


def language_label(language: str | None) -> str:
    code = normalize_language(language)
    if code in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[code]
    base = code.split("-", 1)[0]
    return _LANGUAGE_LABELS.get(base, language or "English")


def language_directive(language: str | None) -> str:
    """Return a strict reader-facing language instruction for prompts."""
    code = normalize_language(language)
    label = language_label(code)
    if code.startswith("zh"):
        return (
            "\n\n[语言要求 / Language] "
            f"请严格使用{label}撰写所有面向读者的文本（标题、正文、解释、提示、过渡句、"
            "题干、选项等），即使参考资料、JSON 字段名或英文术语出现在 prompt 中也"
            "不得切换语言；保留必要的专有名词原文（如人名、产品名、公式中的变量符号"
            f"等）即可，其余一律使用{label}。"
        )
    if code == "en":
        return (
            "\n\n[Language] Write ALL reader-facing text (titles, prose, "
            "explanations, hints, transitions, quiz stems, options, etc.) in "
            "English. Do NOT switch languages even if the source material, "
            "JSON keys, or examples in this prompt are in another language. "
            "Keep proper nouns (people, products, formula symbols) in their "
            "original form."
        )
    return (
        f"\n\n[Language] Write ALL reader-facing text strictly in {label}. "
        "Do NOT switch languages even if the source material, JSON keys, or "
        "examples in this prompt are in a different language. Keep proper "
        "nouns (people, products, formula symbols) in their original form."
    )


def append_language_directive(system_prompt: str | None, language: str | None) -> str:
    """Append the language directive to an existing system prompt."""
    base = (system_prompt or "").rstrip()
    directive = language_directive(language).strip()
    if not base:
        return directive
    return f"{base}\n\n{directive}"


__all__ = [
    "RESPONSE_LANGUAGE_CHOICES",
    "append_language_directive",
    "is_response_language_code",
    "language_directive",
    "language_label",
    "normalize_language",
    "prompt_locale",
]
