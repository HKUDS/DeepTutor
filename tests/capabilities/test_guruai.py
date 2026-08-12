from deeptutor.capabilities.guruai import (
    GuruExplainLoopCapability,
    GuruPracticeLoopCapability,
)
from deeptutor.capabilities.registry import active_loop_capabilities
from deeptutor.core.context import UnifiedContext


def _context(mode: str) -> UnifiedContext:
    return UnifiedContext(metadata={"guruai_mode": mode})


def test_guruai_explain_is_opt_in():
    context = _context("explain")
    names = {cap.name for cap in active_loop_capabilities(context)}
    assert "guruai_explain" in names
    assert GuruExplainLoopCapability().pre_loop_seed(context)


def test_guruai_practice_grade_is_opt_in():
    context = _context("practice_grade")
    names = {cap.name for cap in active_loop_capabilities(context)}
    assert "guruai_practice_grade" in names
    assert GuruPracticeLoopCapability().pre_loop_seed(context)


def test_guruai_is_off_by_default():
    context = _context("")
    names = {cap.name for cap in active_loop_capabilities(context)}
    assert "guruai_explain" not in names
    assert "guruai_practice_grade" not in names
