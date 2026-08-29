"""Capture a current authenticated MinerU v4 result without storing its token."""

from __future__ import annotations

from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from deeptutor.services.parsing.engines.mineru.cloud import parse_cloud
from deeptutor.services.parsing.engines.mineru.config import MinerUConfig

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "original.pdf"
TARGET = HERE / "mineru-v2-current"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if TARGET.exists():
        raise SystemExit(f"Refusing to overwrite existing capture: {TARGET}")
    token = getpass.getpass("MinerU API token (not stored): ").strip()
    if not token:
        raise SystemExit("No token entered")
    config = MinerUConfig(
        mode="cloud",
        api_token=token,
        model_version="pipeline",
        enable_formula=True,
        enable_table=True,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="deeptutor-mineru-capture-") as raw:
            parsed = parse_cloud(SOURCE, Path(raw), config)
            candidates = sorted(parsed.rglob("*_content_list.json"))
            if len(candidates) != 1:
                raise RuntimeError(f"Expected one content_list artifact, found {len(candidates)}")
            content_root = candidates[0].parent
            shutil.copytree(content_root, TARGET)
    finally:
        token = ""

    files = {
        path.relative_to(TARGET).as_posix(): _sha256(path)
        for path in sorted(TARGET.rglob("*"))
        if path.is_file()
    }
    provenance = {
        "capture_schema": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "service": "https://mineru.net/api/v4",
        "model_version": "pipeline",
        "authenticated": True,
        "source": {"path": "../original.pdf", "sha256": _sha256(SOURCE)},
        "artifacts": files,
    }
    (TARGET / "deeptutor-fixture-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Captured {len(files)} artifact(s) in {TARGET}")


if __name__ == "__main__":
    main()
