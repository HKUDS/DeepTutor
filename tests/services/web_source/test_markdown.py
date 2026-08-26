"""Tests for web snapshot Markdown cleanup."""

from deeptutor.services.web_source.markdown import strip_leading_snapshot_provenance


def test_strips_only_leading_source_comments() -> None:
    markdown = (
        "\n"
        "<!-- source: https://docs.example.com/page -->\n"
        "<!-- source: https://docs.example.com/canonical -->\n"
        "# Documentation\n"
    )

    assert strip_leading_snapshot_provenance(markdown) == "# Documentation\n"


def test_preserves_body_and_code_comments() -> None:
    markdown = (
        "# Documentation\n\n"
        "<!-- source: https://docs.example.com/inside-body -->\n\n"
        "```html\n<!-- source: https://docs.example.com/in-code -->\n```\n"
    )

    assert strip_leading_snapshot_provenance(markdown) == markdown
