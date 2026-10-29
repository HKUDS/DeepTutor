"""The module manifest is shared by packaging, runtime assembly and clients.

Reading the catalog never imports a feature or creates its services. Package
ownership is distinct from deployment selection and from execution readiness.
User authorization remains the responsibility of existing scoped adapters.
"""

from __future__ import annotations

from functools import cache
from importlib import metadata
import json
from pathlib import Path
import shutil
from typing import Any

from packaging.requirements import Requirement


class ModuleUnavailable(ValueError):
    pass


@cache
def manifests() -> dict[str, dict[str, Any]]:
    result = {}
    for path in sorted(Path(__file__).with_name("manifests").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row["schema_version"] != 1 or row["id"] != path.stem:
            raise ValueError(f"Invalid module manifest: {path.name}")
        result[row["id"]] = row
    owners: dict[tuple[str, str], str] = {}
    for name, row in result.items():
        for dependency in [*row["requires"], *row["optional"]]:
            if dependency not in result or dependency == name:
                raise ValueError(f"Invalid module dependency: {name} -> {dependency}")
        for kind in ("tools", "capabilities", "loops"):
            for spec in row[kind].values():
                for dependency in spec.get("requires", []):
                    if dependency not in {*row["requires"], *row["optional"]}:
                        raise ValueError(
                            f"Undeclared contribution dependency: {name} -> {dependency}"
                        )
        for kind in ("capabilities", "loops", "tools", "paths"):
            for key in row[kind]:
                identity = (kind, key)
                if identity in owners:
                    raise ValueError(
                        f"Duplicate {kind} owner for {key}: {owners[identity]}, {name}"
                    )
                owners[identity] = name
        for prefix in row["paths"]:
            if prefix.startswith("/") or ".." in prefix.split("/"):
                raise ValueError(f"Invalid module path: {prefix}")
        for route in row["routes"]:
            if route["auth"] not in {"public", "authenticated", "learning", "admin"}:
                raise ValueError(f"Invalid route authorization policy: {name}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"Cyclic module dependency: {name}")
        if name in visited:
            return
        if name not in result:
            raise ValueError(f"Unknown required module: {name}")
        visiting.add(name)
        for dependency in result[name]["requires"]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in result:
        visit(name)
    return result


@cache
def source_checkout() -> bool:
    root = Path(__file__).resolve().parents[2]
    # Docker and source archives deliberately omit Git metadata. Published
    # wheels contain neither the project file nor the source build script.
    return (root / "pyproject.toml").is_file() and (root / "scripts/build_modules.py").is_file()


def state_path() -> Path:
    from deeptutor.runtime.home import get_runtime_data_root

    return get_runtime_data_root() / "system" / "modules.json"


def selection() -> dict[str, bool]:
    path = state_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("enabled"), dict):
        raise ValueError(f"Invalid module state: {path}")
    enabled = raw["enabled"]
    if any(name not in manifests() or type(value) is not bool for name, value in enabled.items()):
        raise ValueError(f"Invalid module selection: {path}")
    return enabled


def installed(name: str) -> bool:
    if name == "core":
        return True
    if source_checkout():
        return True
    try:
        metadata.distribution(manifests()[name]["distribution"])
        return True
    except metadata.PackageNotFoundError:
        return False


def module_enabled(name: str, *, selected: dict[str, bool] | None = None) -> bool:
    if name not in manifests():
        raise ValueError(f"Unknown module: {name}")
    if name == "core":
        return True
    selected = selection() if selected is None else selected
    if not installed(name) or not selected.get(name, True):
        return False
    if not source_checkout():
        from deeptutor.__version__ import __version__

        if metadata.version(manifests()[name]["distribution"]) != __version__:
            return False
    return all(module_enabled(dep, selected=selected) for dep in manifests()[name]["requires"])


def require_module(name: str) -> None:
    if not module_enabled(name):
        raise ModuleUnavailable(
            f"Module '{name}' is unavailable. Run `deeptutor module install {name}` "
            f"and `deeptutor module enable {name}`."
        )


@cache
def module_for_path(path: str) -> str:
    """Longest explicit path owns the file; unassigned shared code is core."""
    path = path.replace("\\", "/")
    candidates = [
        (len(prefix), name)
        for name, row in manifests().items()
        for prefix in row["paths"]
        if path == prefix or path.startswith(prefix + "/")
    ]
    return max(candidates)[1] if candidates else "core"


def contribution_owner(kind: str, name: str) -> str:
    for module, row in manifests().items():
        if name in row[kind]:
            return module
    return "core"


def contribution_enabled(kind: str, name: str) -> bool:
    owner = contribution_owner(kind, name)
    spec = manifests()[owner][kind].get(name, {})
    return module_enabled(owner) and all(
        module_enabled(dependency) for dependency in spec.get("requires", [])
    )


def dependency_order(names: list[str]) -> list[str]:
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name not in manifests():
            raise ValueError(f"Unknown module: {name}")
        if name in ordered:
            return
        for dependency in manifests()[name]["requires"]:
            visit(dependency)
        ordered.append(name)

    for name in names:
        visit(name)
    return ordered


def dependents(name: str, *, enabled_only: bool = False) -> list[str]:
    return [
        key
        for key in manifests()
        if key != name
        and name in dependency_order([key])
        and (module_enabled(key) if enabled_only else installed(key))
    ]


def module_statuses() -> list[dict[str, Any]]:
    from deeptutor.__version__ import __version__

    selected = selection()
    rows = []
    for name, manifest in manifests().items():
        present = installed(name)
        enabled = module_enabled(name, selected=selected)
        issues = []
        for dependency in manifest["requires"]:
            if not module_enabled(dependency, selected=selected):
                issues.append(f"Required module unavailable: {dependency}")
        if present:
            if not source_checkout() and name != "core":
                version = metadata.version(manifest["distribution"])
                if version != __version__:
                    issues.append(f"Module version {version} must match core {__version__}")
            for raw in manifest["requirements"]:
                requirement = Requirement(raw)
                if requirement.marker and not requirement.marker.evaluate():
                    continue
                try:
                    version = metadata.version(requirement.name)
                    if version not in requirement.specifier:
                        issues.append(f"Requires {raw}; installed {version}")
                except metadata.PackageNotFoundError:
                    issues.append(f"Missing package: {raw}")
            for executable in manifest["executables"]:
                if shutil.which(executable) is None:
                    issues.append(f"Missing executable: {executable}")
        rows.append(
            {
                "id": name,
                "distribution": manifest["distribution"],
                "installed": present,
                "enabled": enabled,
                "ready": enabled and not issues,
                "issues": issues,
                "requires": manifest["requires"],
                "navigation": manifest["navigation"],
                "capabilities": list(manifest["capabilities"]),
                "source": source_checkout(),
            }
        )
    by_id = {row["id"]: row for row in rows}
    for name in dependency_order(list(by_id)):
        row = by_id[name]
        for dependency in row["requires"]:
            if by_id[dependency]["enabled"] and not by_id[dependency]["ready"]:
                row["issues"].append(f"Required module not ready: {dependency}")
                row["ready"] = False
    return rows
