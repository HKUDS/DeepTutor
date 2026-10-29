"""Versioned package metadata shared by source and official wheel builds.

Keep this module standard-library-only: setuptools loads it before installing
runtime dependencies, and Docker also uses it to resolve source extras.
"""

import ast
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent


def project_version(root: Path = ROOT) -> str:
    source = ast.parse((root / "deeptutor/__version__.py").read_text(encoding="utf-8"))
    for node in source.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            return str(ast.literal_eval(node.value))
    raise ValueError("Missing DeepTutor version")


def optional_dependencies(root: Path = ROOT) -> dict[str, list[str]]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    templates = data["tool"]["deeptutor"]["optional-dependencies"]
    version = project_version(root)
    return {name: [raw.format(version=version) for raw in rows] for name, rows in templates.items()}


def source_optional_dependencies(root: Path = ROOT) -> dict[str, list[str]]:
    """Source deployments already own module code; install only its dependencies.

    Installing a feature wheel over a Docker/source tree would add a second
    code owner and require the unreleased version to exist on PyPI.
    """
    extras = optional_dependencies(root)
    modules = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in (root / "deeptutor/modules/manifests").glob("*.json")
    }
    distributions = {row["distribution"]: name for name, row in modules.items()}

    def expand_module(name: str) -> list[str]:
        row = modules[name]
        return [
            *row["requirements"],
            *(raw for dep in row["requires"] for raw in expand_module(dep)),
        ]

    def expand_extra(name: str) -> list[str]:
        result = []
        for raw in extras[name]:
            package = raw.split("==", 1)[0]
            if package in distributions:
                result.extend(expand_module(distributions[package]))
            elif package.startswith("deeptutor["):
                for dep in package[len("deeptutor[") : -1].split(","):
                    result.extend(expand_extra(dep))
            else:
                result.append(raw)
        return list(dict.fromkeys(result))

    return {name: expand_extra(name) for name in extras}
