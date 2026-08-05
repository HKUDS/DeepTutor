"""Shared helpers for the MED-01/MED-02 media runtime tests.

Kept out of ``conftest.py`` because this repository runs pytest with
``--import-mode=importlib``, where conftest modules are not importable by name.
This module lives under the ``tests`` package (a PEP 420 namespace package with
the repo root on ``pythonpath``) so the test files can import it explicitly.
"""

from __future__ import annotations

import struct
import zlib

from deeptutor.services.media.models import ImageGenerationJob, MediaInput


def make_png(width: int = 8, height: int = 8, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    """Build a small, valid RGB PNG without external dependencies."""

    def chunk(typ: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + typ
            + payload
            + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(color) * width
    idat = zlib.compress(row * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_png_header_only(width: int = 8, height: int = 8) -> bytes:
    """A minimal PNG with a valid IHDR declaring *width* x *height*.

    No IDAT/IEND is included, so any full decode fails — but header-based
    dimension readers (and the pixel cap) can already act on it.  Used to
    exercise pixel-limit rejection *before* decompression.
    """

    def chunk(typ: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + typ
            + payload
            + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)


def make_media_input(*, width: int = 8, height: int = 8) -> MediaInput:
    return MediaInput(data=make_png(width, height), mime_type="image/png")


class FakeExecutor:
    """Stands in for a MED-02 provider adapter in the worker tests."""

    def __init__(
        self,
        inputs: list[MediaInput] | None = None,
        error: Exception | None = None,
        cancel_confirmed: bool | None = None,
    ) -> None:
        self.inputs = list(inputs or [])
        self.error = error
        self.cancel_confirmed = cancel_confirmed
        self.runs = 0
        self.poll_calls = 0
        self.cancel_calls = 0

    async def run(self, job: ImageGenerationJob) -> list[MediaInput]:
        self.runs += 1
        if self.error is not None:
            raise self.error
        return list(self.inputs)

    async def poll(self, job: ImageGenerationJob) -> None:
        self.poll_calls += 1

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        self.cancel_calls += 1
        if self.cancel_confirmed is None:
            raise NotImplementedError("provider does not support remote cancel")
        return self.cancel_confirmed
