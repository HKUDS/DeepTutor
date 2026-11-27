"""Content routing must not reject UTF-8 split by the bounded text probe."""

from pathlib import Path

import pytest

from deeptutor.utils.file_types import DocumentType, FileTypeRouter


@pytest.mark.parametrize(
    ("character", "sampled_bytes"),
    [("é", 1), ("中", 1), ("中", 2), ("🙂", 1), ("🙂", 2), ("🙂", 3)],
)
def test_route_text_when_probe_ends_inside_utf8_character(
    tmp_path: Path,
    character: str,
    sampled_bytes: int,
) -> None:
    path = tmp_path / "chapter"
    data = b"a" * (8192 - sampled_bytes) + character.encode("utf-8") + b" remainder"
    path.write_bytes(data)
    assert character in data.decode("utf-8")

    assert FileTypeRouter.get_document_type(str(path)) is DocumentType.TEXT
    assert FileTypeRouter.classify_files([str(path)]).text_files == [str(path)]


@pytest.mark.parametrize(
    "data",
    [
        b"\x00binary",
        b"\xffinvalid",
        b"a" * 8191 + b"\xe4",
        b"a" * 8190 + b"\xf0\x9f",
        b"a" * 8189 + b"\xf0\x9f\x99",
        b"a" * 8191 + b"\xe4" + b"not a continuation",
    ],
    ids=[
        "nul",
        "invalid-start",
        "truncated-cjk",
        "truncated-emoji-2",
        "truncated-emoji-3",
        "invalid-continuation",
    ],
)
def test_text_probe_still_rejects_invalid_or_incomplete_utf8(
    tmp_path: Path,
    data: bytes,
) -> None:
    path = tmp_path / "binary"
    path.write_bytes(data)

    assert FileTypeRouter._is_text_file(str(path)) is False
