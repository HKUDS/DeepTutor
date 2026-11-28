"""Check the bundled Codex catalog version against official stable releases."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

# Load only the two metadata modules; maintenance does not need the app runtime.
import importlib.util
import types
import httpx

_root = Path(__file__).resolve().parents[1] / "deeptutor/services/codex_auth"
_package = types.ModuleType("_codex_metadata")
_package.__path__ = [str(_root)]
sys.modules[_package.__name__] = _package
for _name in ("constants", "client_version"):
    _spec = importlib.util.spec_from_file_location(f"_codex_metadata.{_name}", _root / f"{_name}.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)
from _codex_metadata.client_version import _source_version, max_stable_version
from _codex_metadata.constants import CODEX_CLIENT_VERSION


async def check_versions() -> tuple[dict, int]:
    async with httpx.AsyncClient() as http:
        npm, github = await asyncio.gather(
            _source_version(http, "npm"), _source_version(http, "github")
        )
    upstream = max_stable_version(npm, github)
    code = 1 if upstream is None else (
        0 if max_stable_version(CODEX_CLIENT_VERSION, upstream) == CODEX_CLIENT_VERSION else 2
    )
    return {"bundled": CODEX_CLIENT_VERSION, "npm": npm, "github": github,
            "upstream": upstream, "status": {0: "up-to-date", 1: "unavailable", 2: "drift"}[code]}, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()
    result, code = asyncio.run(check_versions())
    table = "| Bundled | npm | GitHub | Status |\n|---|---|---|---|\n"
    table += f"| {result['bundled']} | {result['npm']} | {result['github']} | {result['status']} |\n"
    print(json.dumps(result) if args.json else table)
    if args.github_summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(table)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
