from deeptutor.agents.visualize.utils import validate_visualization

VALID_MINDMAP = """mindmap
  root((Cell biology))
    Organelles
      Mitochondria
    Transport
"""


def test_mindmap_validation_accepts_hierarchical_root() -> None:
    ok, error = validate_visualization(VALID_MINDMAP, "mindmap")

    assert ok is True, error
    assert error == ""


def test_mindmap_validation_rejects_wrong_keyword() -> None:
    ok, error = validate_visualization("graph TD\n  A-->B", "mindmap")

    assert ok is False
    assert "start with the `mindmap` keyword" in error


def test_mindmap_validation_requires_exact_keyword_case() -> None:
    ok, error = validate_visualization(
        "Mindmap\n  Root\n    Child",
        "mindmap",
    )

    assert ok is False
    assert "start with the `mindmap` keyword" in error


def test_mindmap_validation_rejects_multiple_roots() -> None:
    ok, error = validate_visualization(
        "mindmap\n  Root A\n    Child\n  Root B\n    Child",
        "mindmap",
    )

    assert ok is False
    assert "exactly one non-empty root" in error


def test_mindmap_validation_rejects_root_without_children() -> None:
    ok, error = validate_visualization("mindmap\n  Root only", "mindmap")

    assert ok is False
    assert "at least one child branch" in error


def test_mindmap_validation_rejects_markdown_fence() -> None:
    ok, error = validate_visualization(f"```mermaid\n{VALID_MINDMAP}```", "mindmap")

    assert ok is False
    assert "without a Markdown fence" in error
