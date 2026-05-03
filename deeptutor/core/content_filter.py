"""
Content Filter — Harmful content detection for external web sources.

Two-tier approach:
  1. Primary: Fast regex-based pattern filter for English and CJK content
  2. Secondary: LLM classifier (triggered only when primary flags content)

Handles: self-harm, CSAM, extremist content, hate speech, graphic violence.
Educational content about these topics is preserved (context-aware).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SafetyCategory(str, Enum):
    """Harmful content categories."""

    SELF_HARM = "self_harm"
    CSAM = "csam"
    EXTREMIST = "extremist"
    HATE_SPEECH = "hate_speech"
    GRAPHIC_VIOLENCE = "graphic_violence"


@dataclass
class SafetyDecision:
    """Result of content safety evaluation."""

    is_safe: bool
    category: SafetyCategory | None = None
    confidence: float = 0.0
    filter_used: str = "pattern"  # "pattern" | "llm"
    matched_patterns: list[str] | None = None
    llm_reason: str | None = None


# CJK-aware regex patterns for harmful content
# Each entry: (category, list of compiled patterns)
_HARMFUL_PATTERNS: list[tuple[SafetyCategory, re.Pattern[str]]] = [
    # Self-harm — English
    (
        SafetyCategory.SELF_HARM,
        re.compile(
            r"\b(suicide\s*(method|guide|how\s*to|instructions?|ways?))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.SELF_HARM,
        re.compile(
            r"\b(self\s*(harm|injury|harm\s*guide)|cutting\s*(self|how\s*to))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.SELF_HARM,
        re.compile(
            r"\b(pro\s*[-]?ana|pro\s*[-]?mia|thinspo|anorexia\s*(tips?|guide))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.SELF_HARM,
        re.compile(
            r"\b(purge\s*(how\s*to|method)|bulimia\s*(tips?|guide))\b",
            re.IGNORECASE,
        ),
    ),
    # Self-harm — Chinese/CJK
    (
        SafetyCategory.SELF_HARM,
        re.compile(r"自杀\s*(方法|教程|指南|步骤)|自残\s*(方法|教程)", re.IGNORECASE),
    ),
    (
        SafetyCategory.SELF_HARM,
        re.compile(r"厌食症|催吐\s*(方法|教程)|减肥\s*(极速|极端)", re.IGNORECASE),
    ),
    (
        SafetyCategory.SELF_HARM,
        re.compile(r"割腕|自杀念头|自我伤害", re.IGNORECASE),
    ),
    # Extremist — English
    (
        SafetyCategory.EXTREMIST,
        re.compile(
            r"\b(terrorist\s*(attack|guide|how\s*to|instructions?))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.EXTREMIST,
        re.compile(
            r"\b(how\s*to\s*make\s*(bomb|explosive|weapon))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.EXTREMIST,
        re.compile(
            r"\b(isis|al\s*qaeda|hamas)\s*(attack|recruit|guide)\b",
            re.IGNORECASE,
        ),
    ),
    # Extremist — Chinese/CJK
    (
        SafetyCategory.EXTREMIST,
        re.compile(r"恐怖\s*(袭击|组织|分子)|极端主义|圣战\s*(视频|手册)", re.IGNORECASE),
    ),
    (
        SafetyCategory.EXTREMIST,
        re.compile(r"制作\s*(炸弹|爆炸物|武器)\s*(教程|方法)", re.IGNORECASE),
    ),
    # Hate speech — English
    (
        SafetyCategory.HATE_SPEECH,
        re.compile(
            r"\b(kill\s+all\s+(blacks|whites|jews|muslims|asians))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.HATE_SPEECH,
        re.compile(
            r"\b(racial\s*(hatred|genocide)|ethnic\s*cleansing)\b",
            re.IGNORECASE,
        ),
    ),
    # Hate speech — Chinese/CJK
    (
        SafetyCategory.HATE_SPEECH,
        re.compile(r"种族\s*(仇恨|灭绝)|种族歧视|仇恨\s*(言论|攻击)", re.IGNORECASE),
    ),
    (
        SafetyCategory.HATE_SPEECH,
        re.compile(r"性别\s*(歧视|仇恨)|仇恨\s*(女性|男性)", re.IGNORECASE),
    ),
    # Graphic violence — English
    (
        SafetyCategory.GRAPHIC_VIOLENCE,
        re.compile(
            r"\b(gore\s*(video|porn|images?)|graphic\s*(violence|gore))\b",
            re.IGNORECASE,
        ),
    ),
    (
        SafetyCategory.GRAPHIC_VIOLENCE,
        re.compile(
            r"\b(how\s*to\s*kill|how\s*to\s*torture|how\s*to\s*mutilate)\b",
            re.IGNORECASE,
        ),
    ),
    # Graphic violence — Chinese/CJK
    (
        SafetyCategory.GRAPHIC_VIOLENCE,
        re.compile(r"血腥\s*(画面|视频|图片)|暴力\s*(内容|场面)", re.IGNORECASE),
    ),
    (
        SafetyCategory.GRAPHIC_VIOLENCE,
        re.compile(r"分尸|酷刑\s*(方法|教程)|残害\s*(尸体|尸体)", re.IGNORECASE),
    ),
]

# Educational context patterns — content about these topics is usually safe
_EDUCATIONAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(mental\s*health\s*awareness|suicide\s*prevention)", re.IGNORECASE),
    re.compile(r"\b(counseling|therapy|help\s*line|support\s*group)\b", re.IGNORECASE),
    re.compile(r"\b(safety\s*education|awareness\s*program|prevent)\b", re.IGNORECASE),
    re.compile(r"(心理健康|自杀预防|心理援助热线|心理咨询)", re.IGNORECASE),
    re.compile(r"(安全教育|预防宣传|互助小组)", re.IGNORECASE),
]

# CSAM — URL/domain level blocking (no content pattern matching)
_CSAM_DOMAINS: frozenset[str] = frozenset([
    "loli.net",
    "shota.net",
    "lolicon.net",
    "pedoland.net",
    "childporn.net",
])


class ContentFilter:
    """Two-tier content filter for harmful content detection."""

    def __init__(self, llm_classifier: LLMClassifier | None = None) -> None:
        """
        Args:
            llm_classifier: Optional LLM-based classifier for secondary detection.
                           If None, only pattern-based filtering is used.
        """
        self._llm = llm_classifier

    def check(self, content: str, url: str | None = None) -> SafetyDecision:
        """
        Evaluate content for harmful material.

        Args:
            content: Text content to evaluate.
            url: Optional URL for domain-level blocking (CSAM).

        Returns:
            SafetyDecision with is_safe=True if content passes.
        """
        # Fast path: URL-based CSAM blocking
        if url and self._is_csam_url(url):
            return SafetyDecision(
                is_safe=False,
                category=SafetyCategory.CSAM,
                confidence=1.0,
                filter_used="pattern",
                matched_patterns=[f"blocked_domain:{url}"],
            )

        # Strip excessive whitespace for cleaner matching
        text = " ".join(content.split())[:50000]  # Cap at 50k chars for perf

        # Educational context check — if content appears educational, skip blocking
        if self._is_educational_content(text):
            return SafetyDecision(is_safe=True, confidence=0.1, filter_used="pattern")

        # Pattern-based detection
        decision = self._pattern_check(text)
        if decision.is_safe:
            return decision

        # Secondary: LLM classifier for uncertain cases
        if self._llm is not None and decision.confidence < 0.9:
            return self._llm.classify(text, decision.category)

        return decision

    def _is_csam_url(self, url: str) -> bool:
        """Check if URL matches known CSAM domains."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in _CSAM_DOMAINS)

    def _is_educational_content(self, text: str) -> bool:
        """Check if text appears to be educational / safety awareness content."""
        return any(p.search(text) for p in _EDUCATIONAL_PATTERNS)

    def _pattern_check(self, text: str) -> SafetyDecision:
        """Run pattern-based detection. Returns first match."""
        for category, pattern in _HARMFUL_PATTERNS:
            if pattern.search(text):
                return SafetyDecision(
                    is_safe=False,
                    category=category,
                    confidence=0.85,
                    filter_used="pattern",
                    matched_patterns=[pattern.pattern],
                )
        return SafetyDecision(is_safe=True, confidence=0.95, filter_used="pattern")


class LLMClassifier:
    """Secondary LLM-based classifier for borderline content."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def classify(
        self, content: str, category: SafetyCategory | None
    ) -> SafetyDecision:
        """
        Use LLM to classify content safety.

        Args:
            content: Text content to classify.
            category: Prior-raised category (or None for full scan).

        Returns:
            SafetyDecision with LLM verdict.
        """
        from deeptutor.services.llm.factory import complete

        prompt = (
            "You are a content safety classifier. Evaluate the following text.\n"
            f"Category to check: {category.value if category else 'any harmful content'}\n\n"
            "Text:\n"
            f"{content[:2000]}\n\n"
            "Respond with JSON: {\"is_safe\": bool, \"reason\": str}"
        )

        try:
            response = await complete(
                prompt=prompt,
                system_prompt="You are a content safety classifier. Output only JSON.",
                api_key=self._api_key,
                base_url=self._base_url,
            )
            import json
            data = json.loads(response)
            return SafetyDecision(
                is_safe=data.get("is_safe", True),
                category=category,
                confidence=0.95 if data.get("is_safe") else 0.9,
                filter_used="llm",
                llm_reason=data.get("reason", ""),
            )
        except Exception:
            # Fail safe: if LLM classification fails, block the content
            return SafetyDecision(
                is_safe=False,
                category=category,
                confidence=0.5,
                filter_used="llm",
                llm_reason="LLM classification failed — defaulting to block",
            )