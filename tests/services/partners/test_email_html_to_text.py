"""The HTML-to-text fallback must not leak <style>/<script> bodies to the model."""

from deeptutor.partners.channels.email import EmailChannel


def test_style_block_body_is_removed() -> None:
    text = EmailChannel._html_to_text("<style>.a{color:red;font-size:14px}</style><p>Hi there</p>")
    assert "color:red" not in text
    assert ".a{" not in text
    assert "Hi there" in text


def test_script_block_body_is_removed() -> None:
    text = EmailChannel._html_to_text("<script>alert(1)</script><p>Body</p>")
    assert "alert(1)" not in text
    assert "Body" in text


def test_plain_markup_is_still_rendered() -> None:
    text = EmailChannel._html_to_text("<p>First</p><p>Second</p>")
    assert "First" in text and "Second" in text
