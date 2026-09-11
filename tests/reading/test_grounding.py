from deeptutor.reading._grounding import grounding_context, selection_range


def test_selection_range_maps_collapsed_whitespace_back_to_source() -> None:
    text = "before\n\tverified   phrase after"

    bounds = selection_range(text, "verified phrase")

    assert bounds is not None
    assert text[bounds[0] : bounds[1]] == "verified   phrase"


def test_grounding_context_keeps_a_late_selection_inside_the_bound() -> None:
    text = "prefix " * 2_000 + "verified phrase" + " suffix" * 2_000

    context = grounding_context(text, "verified phrase")

    assert len(context) == 6_000
    assert "verified phrase" in context
