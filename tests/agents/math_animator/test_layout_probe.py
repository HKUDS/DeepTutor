"""The Manim dry-run geometry probe on tiny scenes (skipped without Manim)."""

from __future__ import annotations

import asyncio
import importlib.util

import pytest

from deeptutor.agents.math_animator.layout_probe import geometry_review, scene_name_of

needs_manim = pytest.mark.skipif(
    importlib.util.find_spec("manim") is None, reason="manim not installed"
)

HEAD = "from manim import *\n\nclass S(Scene):\n    def construct(self):\n"


def _review(body: str):
    return asyncio.run(geometry_review(HEAD + body))


def test_scene_name_of() -> None:
    assert scene_name_of(HEAD) == "S"
    assert scene_name_of("class Foo(MovingCameraScene):\n    pass") == "Foo"
    assert scene_name_of("x = 1") is None


@needs_manim
def test_clean_scene_passes() -> None:
    review = _review(
        "        a = Text('Title').to_edge(UP)\n"
        "        b = Text('Body').move_to(DOWN)\n"
        "        self.play(FadeIn(a), FadeIn(b))\n"
    )
    assert review is not None and review.passed, review and review.summary


@needs_manim
def test_overlap_and_off_frame_are_reported() -> None:
    review = _review(
        "        a = Text('Secant slope')\n"
        "        b = Text('Tangent').shift(RIGHT * 0.3)\n"
        "        c = Text('Far away').shift(RIGHT * 9)\n"
        "        line = Line(LEFT * 4, RIGHT * 4)\n"
        "        self.play(FadeIn(a), FadeIn(b), FadeIn(c), Create(line))\n"
    )
    assert review is not None and not review.passed
    joined = " ".join(review.issues)
    assert "overlaps text" in joined
    assert "cut off by the frame edge" in joined
    assert "cross the text" in joined


@needs_manim
def test_value_tracker_scene_does_not_break_the_probe() -> None:
    review = _review(
        "        t = ValueTracker(1)\n"
        "        n = always_redraw(lambda: DecimalNumber(t.get_value()).to_edge(UP))\n"
        "        self.add(n)\n"
        "        self.play(t.animate.set_value(3))\n"
    )
    assert review is not None and review.passed, review and review.summary
