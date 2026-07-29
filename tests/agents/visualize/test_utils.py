from deeptutor.agents.visualize.utils import validate_visualization


def test_html_validation_rejects_inline_javascript_syntax_errors() -> None:
    html = """<!doctype html><html><body><script>
    document.body.innerHTML = '<p>A'B</p>';
    </script></body></html>"""

    ok, error = validate_visualization(html, "html")

    assert not ok
    assert "Inline JavaScript syntax error" in error


def test_html_validation_accepts_valid_inline_javascript() -> None:
    html = """<!doctype html><html><body><script>
    document.body.innerHTML = \"<p>A'B</p>\";
    </script></body></html>"""

    ok, error = validate_visualization(html, "html")

    assert ok, error
