"""Content-Disposition header values must stay single-line.

The ASCII fallback neutralized quotes and backslashes but left C0 control
characters (notably CR/LF) untouched, so a filename containing a newline
produced a header value with a raw ``\n`` in it — a malformed header /
response-splitting shape that the ASGI server rejects (500).
"""

from __future__ import annotations

from deeptutor.api.utils.http_headers import content_disposition


def test_control_characters_are_stripped_from_ascii_fallback() -> None:
    header = content_disposition("a\r\nb.pdf")

    assert "\n" not in header
    assert "\r" not in header


def test_plain_filename_is_unchanged() -> None:
    header = content_disposition("report.pdf")

    assert header == "inline; filename=\"report.pdf\"; filename*=UTF-8''report.pdf"
