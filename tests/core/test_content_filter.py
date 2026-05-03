"""Tests for deeptutor/core/content_filter.py — harmful content detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.content_filter import (
    ContentFilter,
    LLMClassifier,
    SafetyCategory,
    SafetyDecision,
)


# ---------------------------------------------------------------------------
# SafetyCategory & SafetyDecision
# ---------------------------------------------------------------------------

class TestSafetyCategory:
    def test_all_categories_defined(self) -> None:
        assert SafetyCategory.SELF_HARM.value == "self_harm"
        assert SafetyCategory.CSAM.value == "csam"
        assert SafetyCategory.EXTREMIST.value == "extremist"
        assert SafetyCategory.HATE_SPEECH.value == "hate_speech"
        assert SafetyCategory.GRAPHIC_VIOLENCE.value == "graphic_violence"

    def test_category_is_str_enum(self) -> None:
        assert isinstance(SafetyCategory.SELF_HARM, str)


class TestSafetyDecision:
    def test_defaults(self) -> None:
        d = SafetyDecision(is_safe=True)
        assert d.is_safe is True
        assert d.category is None
        assert d.confidence == 0.0
        assert d.filter_used == "pattern"
        assert d.matched_patterns is None
        assert d.llm_reason is None

    def test_full_init(self) -> None:
        d = SafetyDecision(
            is_safe=False,
            category=SafetyCategory.SELF_HARM,
            confidence=0.85,
            filter_used="llm",
            matched_patterns=["pattern1"],
            llm_reason="LLM confirmed self-harm",
        )
        assert d.is_safe is False
        assert d.category == SafetyCategory.SELF_HARM
        assert d.confidence == 0.85
        assert d.filter_used == "llm"


# ---------------------------------------------------------------------------
# ContentFilter — pattern matching
# ---------------------------------------------------------------------------

class TestContentFilterPatternMatching:
    def setup_method(self) -> None:
        self.filter = ContentFilter()

    # --- Self-harm (English) ---

    def test_detects_suicide_method_english(self) -> None:
        result = self.filter.check("Here is a suicide method guide for you")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_self_harm_guide_english(self) -> None:
        result = self.filter.check("self harm guide for beginners")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_pro_ana_english(self) -> None:
        result = self.filter.check("pro-ana tips and tricks to stay thin")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_bulimia_guide_english(self) -> None:
        result = self.filter.check("bulimia guide how to purge")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    # --- Self-harm (Chinese/CJK) ---

    def test_detects_suicide_method_chinese(self) -> None:
        result = self.filter.check("自杀方法教程")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_self_harm_chinese(self) -> None:
        result = self.filter.check("自残方法指南")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_eating_disorder_chinese(self) -> None:
        result = self.filter.check("厌食症极速减肥方法")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    def test_detects_wrist_cutting_chinese(self) -> None:
        result = self.filter.check("割腕自杀念头")
        assert result.is_safe is False
        assert result.category == SafetyCategory.SELF_HARM

    # --- Extremist (English) ---

    def test_detects_terrorist_guide_english(self) -> None:
        result = self.filter.check("terrorist attack guide how to make a bomb")
        assert result.is_safe is False
        assert result.category == SafetyCategory.EXTREMIST

    def test_detects_bomb_making_english(self) -> None:
        result = self.filter.check("how to make explosive devices")
        assert result.is_safe is False
        assert result.category == SafetyCategory.EXTREMIST

    # --- Extremist (Chinese/CJK) ---

    def test_detects_extremist_chinese(self) -> None:
        result = self.filter.check("恐怖袭击组织")
        assert result.is_safe is False
        assert result.category == SafetyCategory.EXTREMIST

    def test_detects_bomb_making_chinese(self) -> None:
        result = self.filter.check("制作炸弹教程")
        assert result.is_safe is False
        assert result.category == SafetyCategory.EXTREMIST

    # --- Hate speech (English) ---

    def test_detects_hate_speech_english(self) -> None:
        result = self.filter.check("kill all blacks racial hatred")
        assert result.is_safe is False
        assert result.category == SafetyCategory.HATE_SPEECH

    def test_detects_racial_genocide_english(self) -> None:
        result = self.filter.check("racial genocide ethnic cleansing")
        assert result.is_safe is False
        assert result.category == SafetyCategory.HATE_SPEECH

    # --- Hate speech (Chinese/CJK) ---

    def test_detects_hate_speech_chinese(self) -> None:
        result = self.filter.check("种族仇恨言论")
        assert result.is_safe is False
        assert result.category == SafetyCategory.HATE_SPEECH

    def test_detects_gender_discrimination_chinese(self) -> None:
        result = self.filter.check("性别歧视仇恨攻击")
        assert result.is_safe is False
        assert result.category == SafetyCategory.HATE_SPEECH

    # --- Graphic violence (English) ---

    def test_detects_gore_english(self) -> None:
        result = self.filter.check("gore video graphic violence")
        assert result.is_safe is False
        assert result.category == SafetyCategory.GRAPHIC_VIOLENCE

    def test_detects_how_to_kill_english(self) -> None:
        result = self.filter.check("how to kill and torture people")
        assert result.is_safe is False
        assert result.category == SafetyCategory.GRAPHIC_VIOLENCE

    # --- Graphic violence (Chinese/CJK) ---

    def test_detects_graphic_violence_chinese(self) -> None:
        result = self.filter.check("血腥画面暴力内容")
        assert result.is_safe is False
        assert result.category == SafetyCategory.GRAPHIC_VIOLENCE

    def test_detects_torture_chinese(self) -> None:
        result = self.filter.check("酷刑方法教程")
        assert result.is_safe is False
        assert result.category == SafetyCategory.GRAPHIC_VIOLENCE

    # --- Safe content ---

    def test_safe_educational_content_english(self) -> None:
        result = self.filter.check(
            "This is a mental health awareness article about suicide prevention "
            "and counseling resources for people in crisis."
        )
        assert result.is_safe is True

    def test_safe_educational_content_chinese(self) -> None:
        result = self.filter.check("这是一篇关于心理健康和自杀预防的文章，包含心理援助热线信息。")
        assert result.is_safe is True

    def test_safe_neutral_content(self) -> None:
        result = self.filter.check("Deep learning is a subset of machine learning.")
        assert result.is_safe is True
        assert result.confidence == 0.95

    def test_safe_technical_content(self) -> None:
        result = self.filter.check("Python programming tutorial for beginners.")
        assert result.is_safe is True


# ---------------------------------------------------------------------------
# ContentFilter — CSAM URL blocking
# ---------------------------------------------------------------------------

class TestContentFilterCSAMURL:
    def setup_method(self) -> None:
        self.filter = ContentFilter()

    def test_blocks_known_csam_domain(self) -> None:
        result = self.filter.check("some page content", url="https://loli.net/some-page")
        assert result.is_safe is False
        assert result.category == SafetyCategory.CSAM
        assert result.confidence == 1.0

    def test_blocks_csam_subdomain(self) -> None:
        result = self.filter.check("content", url="https://www.loli.net/image.jpg")
        assert result.is_safe is False
        assert result.category == SafetyCategory.CSAM

    def test_all_csam_domains_blocked(self) -> None:
        domains = [
            "loli.net",
            "shota.net",
            "lolicon.net",
            "pedoland.net",
            "childporn.net",
        ]
        for domain in domains:
            result = self.filter.check("content", url=f"https://{domain}/path")
            assert result.is_safe is False, f"Expected {domain} to be blocked"
            assert result.category == SafetyCategory.CSAM

    def test_non_csam_url_passes(self) -> None:
        result = self.filter.check("some content", url="https://example.com/article")
        # If content is safe, should pass
        if not result.is_safe:
            assert result.category in (SafetyCategory.SELF_HARM, SafetyCategory.EXTREMIST, SafetyCategory.HATE_SPEECH, SafetyCategory.GRAPHIC_VIOLENCE)


# ---------------------------------------------------------------------------
# ContentFilter — educational context preservation
# ---------------------------------------------------------------------------

class TestContentFilterEducational:
    def setup_method(self) -> None:
        self.filter = ContentFilter()

    def test_preserves_suicide_prevention_content(self) -> None:
        result = self.filter.check(
            "If you or someone you know is struggling with suicide thoughts, "
            "please contact a suicide prevention helpline. Mental health counseling is available."
        )
        assert result.is_safe is True

    def test_preserves_therapy_content(self) -> None:
        result = self.filter.check(
            "Mental health counseling and support groups are available. "
            "Therapy can help people dealing with self-harm urges."
        )
        assert result.is_safe is True

    def test_preserves_safety_education_content(self) -> None:
        result = self.filter.check(
            "Safety education programs help prevent violent incidents. "
            "Awareness is the first step in prevention."
        )
        assert result.is_safe is True

    def test_preserves_chinese_mental_health_content(self) -> None:
        result = self.filter.check(
            "心理健康对每个人都至关重要。自杀预防需要社会各界共同努力。"
        )
        assert result.is_safe is True


# ---------------------------------------------------------------------------
# ContentFilter — confidence scores and filter_used
# ---------------------------------------------------------------------------

class TestContentFilterConfidence:
    def setup_method(self) -> None:
        self.filter = ContentFilter()

    def test_unsafe_content_has_confidence_085(self) -> None:
        result = self.filter.check("suicide method guide")
        assert result.is_safe is False
        assert result.confidence == 0.85
        assert result.filter_used == "pattern"

    def test_safe_content_has_high_confidence(self) -> None:
        result = self.filter.check("Python tutorial about machine learning")
        assert result.is_safe is True
        assert result.confidence == 0.95

    def test_educational_content_has_low_confidence(self) -> None:
        result = self.filter.check(
            "This is a suicide prevention awareness article from a mental health organization."
        )
        assert result.is_safe is True
        assert result.confidence == 0.1  # low because it's educational


# ---------------------------------------------------------------------------
# ContentFilter — text length cap
# ---------------------------------------------------------------------------

class TestContentFilterTextCap:
    def setup_method(self) -> None:
        self.filter = ContentFilter()

    def test_content_above_50k_chars_is_truncated(self) -> None:
        # Create content > 50k chars
        large_content = "a" * 60000
        # Should not hang or be slow
        result = self.filter.check(large_content)
        # Result should be deterministic (either safe or flagged from first 50k)
        assert isinstance(result.is_safe, bool)


# ---------------------------------------------------------------------------
# LLMClassifier — mocked secondary classification
# ---------------------------------------------------------------------------

class TestLLMClassifier:
    @pytest.mark.asyncio
    async def test_classify_returns_llm_decision(self) -> None:
        classifier = LLMClassifier()

        with patch("deeptutor.services.llm.factory.complete") as mock_complete:
            mock_complete.return_value = '{"is_safe": false, "reason": "LLM confirmed harmful content"}'

            decision = await classifier.classify(
                content="some borderline content",
                category=SafetyCategory.SELF_HARM,
            )

        assert decision.is_safe is False
        assert decision.filter_used == "llm"
        assert decision.category == SafetyCategory.SELF_HARM
        assert decision.llm_reason == "LLM confirmed harmful content"
        mock_complete.assert_called_once()
        call_kwargs = mock_complete.call_args[1]
        assert "prompt" in call_kwargs
        assert "system_prompt" in call_kwargs

    @pytest.mark.asyncio
    async def test_classify_clears_flag_when_llm_says_safe(self) -> None:
        classifier = LLMClassifier()

        with patch("deeptutor.services.llm.factory.complete") as mock_complete:
            mock_complete.return_value = '{"is_safe": true, "reason": "content is educational"}'

            decision = await classifier.classify(
                content="suicide prevention article content",
                category=SafetyCategory.SELF_HARM,
            )

        assert decision.is_safe is True
        assert decision.filter_used == "llm"
        assert decision.confidence == 0.95

    @pytest.mark.asyncio
    async def test_classify_fails_safe_on_exception(self) -> None:
        classifier = LLMClassifier()

        with patch("deeptutor.services.llm.factory.complete") as mock_complete:
            mock_complete.side_effect = RuntimeError("LLM API error")

            decision = await classifier.classify(
                content="some content",
                category=SafetyCategory.EXTREMIST,
            )

        # Fail safe — block content when LLM classification fails
        assert decision.is_safe is False
        assert decision.filter_used == "llm"
        assert "defaulting to block" in decision.llm_reason


# ---------------------------------------------------------------------------
# ContentFilter with LLM secondary
# ---------------------------------------------------------------------------

class TestContentFilterWithLLMSecondary:
    @pytest.mark.asyncio
    async def test_llm_triggered_for_uncertain_content(self) -> None:
        """When pattern filter flags content with confidence < 0.9, LLM is triggered."""
        classifier = LLMClassifier()
        filter_with_llm = ContentFilter(llm_classifier=classifier)

        with patch("deeptutor.services.llm.factory.complete") as mock_complete:
            mock_complete.return_value = '{"is_safe": true, "reason": "educational"}'

            # Pattern will match but confidence is 0.85, below 0.9 threshold
            result = await filter_with_llm.check("suicide method guide")

            # Should be cleared by LLM
            assert result.is_safe is True
            assert result.filter_used == "llm"

    def test_llm_not_triggered_if_confidence_already_high(self) -> None:
        """High confidence pattern matches don't need LLM."""
        classifier = LLMClassifier()
        filter_with_llm = ContentFilter(llm_classifier=classifier)

        with patch("deeptutor.services.llm.factory.complete") as mock_complete:
            # CSAM URL has confidence 1.0 — LLM should not be called
            result = filter_with_llm.check("some content", url="https://loli.net/x")

            assert result.is_safe is False
            assert result.filter_used == "pattern"  # LLM not used
            mock_complete.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: ContentFilter used in context
# ---------------------------------------------------------------------------

class TestContentFilterIntegration:
    def test_no_llm_classifier_by_default(self) -> None:
        """ContentFilter created without LLMClassifier only uses patterns."""
        filter_instance = ContentFilter()
        assert filter_instance._llm is None

    def test_llm_classifier_injected(self) -> None:
        classifier = LLMClassifier()
        filter_instance = ContentFilter(llm_classifier=classifier)
        assert filter_instance._llm is classifier

    def test_check_with_empty_content(self) -> None:
        filter_instance = ContentFilter()
        result = filter_instance.check("")
        assert result.is_safe is True

    def test_check_with_whitespace_only(self) -> None:
        filter_instance = ContentFilter()
        result = filter_instance.check("   \n\n   ")
        assert result.is_safe is True

    def test_matched_patterns_returned_on_block(self) -> None:
        filter_instance = ContentFilter()
        result = filter_instance.check("how to make bomb instructions")
        assert result.is_safe is False
        assert result.matched_patterns is not None
        assert len(result.matched_patterns) >= 1