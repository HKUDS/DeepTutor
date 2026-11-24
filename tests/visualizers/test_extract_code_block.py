"""Fence extraction must never leak fence markers into rendered payloads."""

from deeptutor.agents.visualize.utils import extract_code_block


def test_closed_fence_with_language():
    text = "Here you go:\n```html\n<html><body>hi</body></html>\n```\nEnjoy!"
    assert extract_code_block(text, "html") == "<html><body>hi</body></html>"


def test_unclosed_fence_returns_body_not_raw():
    text = "Sure!\n```html\n<html><body>partial"
    out = extract_code_block(text, "html")
    assert out == "<html><body>partial"
    assert "```" not in out


def test_unclosed_fence_any_language():
    text = "```svg\n<svg></svg>"
    out = extract_code_block(text)
    assert out == "<svg></svg>"


def test_no_fence_returns_trimmed_raw():
    text = "  <html><body>hi</body></html>  "
    assert extract_code_block(text, "html") == "<html><body>hi</body></html>"


def test_closing_fence_on_content_line():
    text = "```html\n<html></html>```"
    assert extract_code_block(text, "html") == "<html></html>"
