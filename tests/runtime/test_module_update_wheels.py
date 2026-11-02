"""Exercise the update plan with disposable, dependency-pinned fixture wheels."""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import venv
import zipfile

import pytest

from deeptutor.runtime.update_worker import build_update_command
from deeptutor.services import app_update


def _wheel(root: Path, name: str, version: str, *, requires_core: bool = False) -> None:
    """Build a tiny synthetic distribution, not a replacement application build."""
    normalized = name.replace("-", "_")
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    if requires_core:
        metadata += f"Requires-Dist: deeptutor=={version}\n"
    info = f"{normalized}-{version}.dist-info"
    entries = {
        f"{info}/METADATA": metadata,
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/RECORD": "",
    }
    if name == "deeptutor":
        entries["deeptutor_fixture_core.py"] = f"VERSION = {version!r}\n"
    if name == "deeptutor-server":
        entries["deeptutor_fixture_server.py"] = (
            "from deeptutor_fixture_core import VERSION\n"
            f"assert VERSION == {version!r}\nREADY = VERSION\n"
        )
    with zipfile.ZipFile(root / f"{normalized}-{version}-py3-none-any.whl", "w") as archive:
        for path, value in entries.items():
            archive.writestr(path, value)


@pytest.mark.integration
def test_local_wheel_update_keeps_modules_consistent_without_mutating_learning_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    for version in ("1.7.1", "1.7.2"):
        for name in ("deeptutor", "deeptutor-server", "deeptutor-parser-docling"):
            _wheel(wheelhouse, name, version, requires_core=name != "deeptutor")
    environment = tmp_path / "disposable-venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {
        **os.environ,
        "PIP_NO_INDEX": "1",
        "PIP_FIND_LINKS": str(wheelhouse),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    # Avoid inheriting a developer's editable package or a package-source override.
    env.pop("PYTHONPATH", None)
    env.pop("PIP_TARGET", None)
    env.pop("PIP_PREFIX", None)

    def run(*args):
        return subprocess.run(
            [str(python), *args],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )

    run(
        "-m",
        "pip",
        "install",
        "deeptutor==1.7.1",
        "deeptutor-server==1.7.1",
        "deeptutor-parser-docling==1.7.1",
    )
    script = "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"
    before = json.loads(run("-c", script).stdout)

    def version(name):
        if name not in before:
            raise importlib.metadata.PackageNotFoundError(name)
        return before[name]

    monkeypatch.setattr(app_update.importlib.metadata, "version", version)
    packages = app_update.installed_update_packages("1.7.1")
    learning_data = tmp_path / "learner.json"
    learning_data.write_bytes(b'{"progress":"keep","enabled":{"server":false}}')
    original = learning_data.read_bytes()
    command = build_update_command("1.7.2", packages)
    run(*command[1:])
    after = json.loads(run("-c", script).stdout)
    assert {name: after[name] for name in ("deeptutor", *packages)} == {
        name: "1.7.2" for name in ("deeptutor", *packages)
    }
    assert "deeptutor-web" not in after
    assert run("-m", "pip", "check").stdout.strip() == "No broken requirements found."
    assert (
        run("-c", "from deeptutor_fixture_server import READY; print(READY)").stdout.strip()
        == "1.7.2"
    )
    assert learning_data.read_bytes() == original
