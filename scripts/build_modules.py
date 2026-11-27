#!/usr/bin/env python3
"""Build disjoint official wheels from one source revision.

Run with --output dist/modules. Optional --module selects individual wheels;
the default builds core, all modules, and the CLI compatibility metapackage.
This prepares local artifacts only; it never uploads or installs packages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_metadata import optional_dependencies, project_version
from build_support import owner


def build(output: Path, selected: list[str]) -> list[Path]:
    modules = {
        path.stem: json.loads(path.read_text())
        for path in (ROOT / "deeptutor/modules/manifests").glob("*.json")
    }
    version = project_version(ROOT)
    names = selected or [*modules, "cli"]
    output.mkdir(parents=True, exist_ok=True)
    files = [
        path
        for base in ("deeptutor", "deeptutor_cli", "deeptutor_web")
        for path in (ROOT / base).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and "tests" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    ownership = {path: owner(path.relative_to(ROOT).as_posix()) for path in files}
    built = []
    for name in names:
        if name not in {*modules, "cli"}:
            raise ValueError(f"Unknown module: {name}")
        with tempfile.TemporaryDirectory(prefix=f"deeptutor-build-{name}-") as directory:
            stage = Path(directory)
            module = modules.get(name)
            package_name = module["distribution"] if module else f"deeptutor-{name}"
            if module:
                for source in files:
                    if ownership[source] != name:
                        continue
                    dest = stage / source.relative_to(ROOT)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
            dependencies = list(module["requirements"]) if module else []
            if name != "core":
                dependencies += [f"deeptutor=={version}"]
                dependencies += [
                    f"{modules[dep]['distribution']}=={version}"
                    for dep in (module["requires"] if module else [])
                ]
            config = f"""[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"
[project]
name = {json.dumps(package_name)}
version = {json.dumps(version)}
description = {json.dumps("DeepTutor " + name + " module")}
requires-python = ">=3.11,<3.15"
dependencies = {json.dumps(dependencies)}
[tool.setuptools.packages.find]
where = ["."]
include = ["deeptutor*", "deeptutor_cli*", "deeptutor_web*"]
namespaces = true
[tool.setuptools.package-data]
"deeptutor_web" = ["**/*", ".next/**/*"]
"*" = ["*.json", "*.yaml", "*.yml", "*.md", "*.sh", "*.j2", "*.jinja", "*.ts", "*.tsx", "*.mjs", "*.js", "*.css", "*.html", "*.svg", "*.png", "*.woff2"]
"""
            if name == "core":
                config += '\n[project.scripts]\ndeeptutor = "deeptutor_cli.main:main"\n'
                config += "\n[project.optional-dependencies]\n"
                for key, values in optional_dependencies(ROOT).items():
                    config += f"{json.dumps(key)} = {json.dumps(values)}\n"
            for group, entries in (module or {}).get("entry_points", {}).items():
                config += f"\n[project.entry-points.{json.dumps(group)}]\n"
                for key, value in entries.items():
                    config += f"{json.dumps(key)} = {json.dumps(value)}\n"
            (stage / "MANIFEST.in").write_text(
                "recursive-include deeptutor_web *\nrecursive-include deeptutor_web/.next *\n"
            )
            (stage / "pyproject.toml").write_text(config)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(output.resolve()),
                    str(stage),
                ],
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            wheel = output / f"{package_name.replace('-', '_')}-{version}-py3-none-any.whl"
            if not wheel.is_file():
                raise RuntimeError(f"Expected wheel missing: {wheel}")
            built.append(wheel)
            print(wheel.name, flush=True)
    # One installed file has one owner; namespace parents need no duplicate init.
    owners = {}
    for wheel in built:
        with zipfile.ZipFile(wheel) as archive:
            for path in archive.namelist():
                if ".dist-info/" in path or path.endswith("/"):
                    continue
                if path in owners:
                    raise RuntimeError(f"Wheel overlap: {path} in {owners[path]} and {wheel.name}")
                owners[path] = wheel.name
    return built


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/modules")
    parser.add_argument("--module", action="append", default=[])
    args = parser.parse_args()
    build(args.output, args.module)
