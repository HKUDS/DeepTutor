"""Make a container's declared optional dependencies true again at every start.

A Docker container is disposable, so `docker exec … pip install ".[partners]"`
survives exactly until the next `docker compose down` (#762). The fix is to
stop treating extras as something you *do* to a running container and make them
something the deployment *declares*: set ``DEEPTUTOR_EXTRAS`` in the Compose
file, and every container that starts from it has them.

Two things keep this cheap enough to run on the startup path:

* it reads the extra's requirement list out of ``pyproject.toml`` and installs
  those, rather than reinstalling ``deeptutor`` itself to pull them in;
* an extra whose requirements are already importable-and-satisfied costs one
  metadata lookup per requirement, so a warm container starts as fast as it did
  before.

Never fatal. A missing wheel or an offline registry degrades the same feature
that was already unavailable — it must not take a working deployment offline
with it, so failures are reported and the process still exits 0.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tomllib

# Compose values arrive as one string; accept the spellings people actually
# write ("a,b", "a, b", "a b") rather than making the separator a gotcha.
_SPLIT_RE = re.compile(r"[,\s]+")


def parse_names(raw: str) -> list[str]:
    """Split a declaration into names, de-duplicated and order-preserving."""
    seen: dict[str, None] = {}
    for name in _SPLIT_RE.split(raw or ""):
        cleaned = name.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def load_extras(pyproject: Path) -> dict[str, list[str]]:
    """``{extra: [requirement, …]}`` as declared by the project."""
    with open(pyproject, "rb") as handle:
        data = tomllib.load(handle)
    optional = data.get("project", {}).get("optional-dependencies", {})
    return {
        str(name): [str(req) for req in reqs]
        for name, reqs in optional.items()
        if isinstance(reqs, list)
    }


def missing_requirements(requirements: list[str]) -> list[str]:
    """The subset not already satisfied in this interpreter.

    A requirement we cannot parse counts as missing: handing it to pip and
    letting pip decide is right more often than silently skipping it.
    """
    from importlib.metadata import PackageNotFoundError, version

    from packaging.requirements import Requirement

    missing: list[str] = []
    for raw in requirements:
        try:
            requirement = Requirement(raw)
        except Exception:
            missing.append(raw)
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            missing.append(raw)
            continue
        if requirement.specifier and installed not in requirement.specifier:
            missing.append(raw)
    return missing


def resolve(extras: dict[str, list[str]], names: list[str]) -> tuple[list[str], list[str]]:
    """``(requirements to install, unknown extra names)``."""
    wanted: list[str] = []
    unknown: list[str] = []
    for name in names:
        # Extras normalise dashes and underscores; accept either spelling.
        key = next((k for k in extras if k.replace("_", "-") == name.replace("_", "-")), None)
        if key is None:
            unknown.append(name)
            continue
        wanted.extend(extras[key])
    return wanted, unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="?", default="", help="extras, comma- or space-separated")
    parser.add_argument("--pyproject", default="pyproject.toml", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be installed and change nothing",
    )
    args = parser.parse_args(argv)

    names = parse_names(args.names)
    if not names:
        return 0

    try:
        extras = load_extras(args.pyproject)
    except Exception as exc:
        print(f"   ⚠️ Could not read {args.pyproject}: {exc}")
        return 0

    requirements, unknown = resolve(extras, names)
    for name in unknown:
        print(f"   ⚠️ Unknown extra '{name}'. Available: {', '.join(sorted(extras))}")
    if not requirements:
        return 0

    missing = missing_requirements(requirements)
    if not missing:
        print(f"   ✅ Extras already satisfied: {', '.join(names)}")
        return 0

    if args.dry_run:
        print(f"   📦 Would install {len(missing)} package(s) for {', '.join(names)}:")
        for requirement in missing:
            print(f"      {requirement}")
        return 0

    print(f"   📦 Installing {len(missing)} package(s) for: {', '.join(names)}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-input", *missing],
        check=False,
    )
    if result.returncode != 0:
        print(f"   ⚠️ pip exited {result.returncode}; the extras above stay unavailable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
