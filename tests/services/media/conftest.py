"""Fixtures for the MED-01 media runtime tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.store import MediaStore


@pytest.fixture
def media_store(tmp_path: Path) -> MediaStore:
    """A MediaStore rooted in a throwaway temp dir with default limits."""
    return MediaStore(root=tmp_path / "media", limits=MediaLimits())


@pytest.fixture
def tiny_quota_store(tmp_path: Path) -> MediaStore:
    """A MediaStore with a small per-user quota for exhaustion/recovery tests."""
    return MediaStore(
        root=tmp_path / "media",
        limits=MediaLimits(max_user_bytes=150, grace_period_seconds=60.0),
    )
