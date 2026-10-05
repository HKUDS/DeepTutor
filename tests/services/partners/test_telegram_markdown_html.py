"""Fenced code blocks in the Telegram markdown -> HTML converter."""

from __future__ import annotations

import pytest

pytest.importorskip("telegram")

from deeptutor.partners.channels.telegram import (  # noqa: E402
    _markdown_to_telegram_html,
    _strip_md_block,
)


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "```c++\nint main() {}\n```",
            "<pre><code>int main() {}\n</code></pre>",
            id="info-string-with-symbols",
        ),
        pytest.param(
            "~~~python\n# setup\ndef __init__(self): pass\n~~~",
            "<pre><code># setup\ndef __init__(self): pass\n</code></pre>",
            id="tilde-fence",
        ),
        pytest.param(
            "````markdown\n```python\nx = 1\n```\n````\nAfter **bold**",
            "<pre><code>```python\nx = 1\n```\n</code></pre>\nAfter <b>bold</b>",
            id="longer-fence-around-example",
        ),
    ],
)
def test_fenced_code_is_rendered_as_code(markdown: str, expected: str) -> None:
    assert _markdown_to_telegram_html(markdown) == expected


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        pytest.param(
            "```python\nx = __y__\n```",
            "<pre><code>x = __y__\n</code></pre>",
            id="backtick-fence",
        ),
    ],
)
def test_backtick_fence_output_is_unchanged(markdown: str, expected: str) -> None:
    assert _markdown_to_telegram_html(markdown) == expected


def test_streaming_preview_strips_tilde_fences() -> None:
    assert _strip_md_block("~~~bash\nls\n~~~\nDone") == "ls\n\nDone"
