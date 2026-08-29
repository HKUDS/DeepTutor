"""Extract MinerU's official legacy content-list example byte-for-byte."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

COMMIT = "61cc6886fe3edda8aa1c5b8bd2b6eaedddb8af99"
SOURCE_PATH = "docs/en/reference/output_files.md"
DEFAULT_REPOSITORY = Path("/home/ubuntu/sources/github.com/opendatalab/MinerU")
HERE = Path(__file__).resolve().parent
TARGET = HERE / "mineru-legacy-official-example"


def main(repository: Path = DEFAULT_REPOSITORY) -> None:
    if TARGET.exists():
        raise SystemExit(f"Refusing to overwrite existing fixture: {TARGET}")
    markdown = subprocess.check_output(
        ["git", "-C", str(repository), "show", f"{COMMIT}:{SOURCE_PATH}"], text=True
    )
    heading = "#### Content List (content_list.json)"
    section = markdown.split(heading, 1)[1]
    sample = section.split("##### Sample Data", 1)[1]
    payload = sample.split("```json", 1)[1].split("```", 1)[0].strip().encode("utf-8") + b"\n"
    json.loads(payload)
    TARGET.mkdir()
    output = TARGET / "content_list.json"
    output.write_bytes(payload)
    provenance = {
        "fixture_schema": 1,
        "kind": "official-legacy-schema-example",
        "repository": "https://github.com/opendatalab/MinerU.git",
        "commit": COMMIT,
        "source_path": SOURCE_PATH,
        "source_section": heading,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "note": "Exact official documentation example; not a live parser capture.",
    }
    (TARGET / "deeptutor-fixture-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
