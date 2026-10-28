"""Setuptools filter: the root wheel owns only core files.

The source distribution retains all sources so the module wheel builder can
produce the complete family from the same revision.
"""

from functools import cache
import json
from pathlib import Path

from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


@cache
def ownership_prefixes():
    return tuple(
        (prefix, module["id"])
        for path in (ROOT / "deeptutor/modules/manifests").glob("*.json")
        for module in [json.loads(path.read_text(encoding="utf-8"))]
        for prefix in module["paths"]
    )


@cache
def owner(relative: str) -> str:
    candidates = [
        (len(prefix), name)
        for prefix, name in ownership_prefixes()
        if relative == prefix or relative.startswith(prefix + "/")
    ]
    return max(candidates)[1] if candidates else "core"


class CoreBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        return [
            row
            for row in super().find_package_modules(package, package_dir)
            if owner(Path(row[2]).resolve().relative_to(ROOT).as_posix()) == "core"
        ]

    def find_data_files(self, package, src_dir):
        return [
            path
            for path in super().find_data_files(package, src_dir)
            if owner(Path(path).resolve().relative_to(ROOT).as_posix()) == "core"
        ]
