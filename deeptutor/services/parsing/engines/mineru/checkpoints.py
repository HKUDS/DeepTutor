"""Workspace-scoped, integrity-checked archives for completed PDF slices.

Each archive is immutable and addressed by its full SHA-256. A tiny atomic
pointer is written only after extraction and merge validation. Concurrent jobs
may duplicate an upload, but cannot expose a partially written checkpoint.
No API tokens or signed URLs are added to checkpoint metadata. Archives may
include source copies supplied by the parser.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .config import MinerUConfig

_VERSION = "slices-v1"
_MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


def checkpoint_root() -> Path:
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_parse_cache_root() / ".mineru-segments"


def job_directory(source: Path, config: MinerUConfig) -> Path:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    identity = {
        "version": _VERSION,
        "source_sha256": digest.hexdigest(),
        "name": source.name,
        "endpoint": config.api_base_url.rstrip("/"),
        "model": config.model_version,
        "language": config.language,
        "formula": config.enable_formula,
        "table": config.enable_table,
        "ocr": config.is_ocr,
        "pages_per_part": config.max_pages_per_part,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return checkpoint_root() / key


class SliceCheckpoint:
    def __init__(self, job: Path, start: int, end: int):
        self.directory = job / f"{start}-{end}"
        self.pointer = self.directory / "ready.json"

    def load(self) -> bytes | None:
        try:
            if self.pointer.is_symlink() or self.directory.is_symlink():
                return None
            info = json.loads(self.pointer.read_text(encoding="utf-8"))
            digest = info["sha256"]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                return None
            archive = self.directory / f"{digest}.zip"
            if archive.is_symlink() or archive.stat().st_size > _MAX_ARCHIVE_BYTES:
                return None
            data = archive.read_bytes()
            if hashlib.sha256(data).hexdigest() == digest:
                return data
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def save(self, archive: bytes) -> None:
        if len(archive) > _MAX_ARCHIVE_BYTES:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(archive).hexdigest()
        self._write(self.directory / f"{digest}.zip", archive)
        self._write(self.pointer, json.dumps({"sha256": digest}).encode())

    @staticmethod
    def _write(target: Path, data: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
