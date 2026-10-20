"""Advisory focus remains scoped and does not infer learning evidence."""

from deeptutor.learning.models import LearnerProfile, TeachingObservation
from deeptutor.learning.teaching import teaching_guidance


def test_focus_uses_current_failed_strategy_without_mutating_profile():
    profile = LearnerProfile(
        teaching_observations={
            "current": TeachingObservation(
                knowledge_point_id="point",
                text="The relationship is unclear",
                basis="learner_report",
                evidence="I still do not see the connection",
                strategy="Names without an example",
                outcome="not_helped",
            ),
            "other": TeachingObservation(
                knowledge_point_id="other",
                text="Needs a diagram",
                strategy="A diagram",
                outcome="helped",
            ),
        }
    )
    before = profile.model_dump()
    focus = teaching_guidance(profile, "point", include_history=True)["teaching_focus"]
    assert focus["knowledge_point_id"] == "point"
    assert [item["key"] for item in focus["observations"]] == ["current"]
    assert focus["observations"][0]["strategy"] == "Names without an example"
    assert focus["observations"][0]["outcome"] == "not_helped"
    assert profile.model_dump() == before


def test_focus_does_not_invent_difficulty_or_understanding():
    focus = teaching_guidance(LearnerProfile(), "point")["teaching_focus"]
    assert focus["observations"] == []
    assert "unknown is not understanding" in focus["instruction"]


def test_preferences_remain_advisory_and_have_clear_boundaries():
    guidance = teaching_guidance(LearnerProfile(), "point")["teaching_guidance"]
    assert "current explicit request over older preferences" in guidance
    assert "pacing as a preference, not a rigid chunk counter" in guidance
    assert "requested display format" in guidance
    assert (
        "mode authorization, source trust, pending-question identity or mastery credit" in guidance
    )
