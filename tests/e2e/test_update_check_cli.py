from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _GitHubReleaseHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/pypi/"):
            body = {"releases": {"1.6.0": [{"yanked": False}]}}
        else:
            body = {
                "tag_name": "v1.6.0",
                "html_url": ("https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0"),
                "draft": False,
                "prerelease": False,
            }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.mark.parametrize(
    ("container_marker", "expected_mode"),
    [(False, "source_web"), (True, "docker")],
)
def test_user_can_check_for_updates_from_the_real_cli_process(
    tmp_path: Path,
    container_marker: bool,
    expected_mode: str,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHubReleaseHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        "\n".join(
            [
                "import os",
                "from deeptutor.update import HttpReleaseProvider",
                (
                    "HttpReleaseProvider.GITHUB_LATEST_URL = "
                    "os.environ['DEEPTUTOR_TEST_RELEASE_URL']"
                ),
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(PROJECT_ROOT)))
    env["DEEPTUTOR_TEST_RELEASE_URL"] = f"http://127.0.0.1:{server.server_port}/releases/latest"
    if container_marker:
        env["DEEPTUTOR_CONTAINER"] = "1"
    else:
        env.pop("DEEPTUTOR_CONTAINER", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", "update", "--check"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    assert f"Installation: {expected_mode}" in completed.stdout
    assert "Latest stable: 1.6.0" in completed.stdout
    if container_marker:
        assert "recreate the service on the host" in completed.stdout


def test_wheel_user_can_check_for_updates_from_the_real_cli_process(
    tmp_path: Path,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHubReleaseHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    installed = tmp_path / "site-packages"
    shutil.copytree(PROJECT_ROOT / "deeptutor", installed / "deeptutor")
    shutil.copytree(PROJECT_ROOT / "deeptutor_cli", installed / "deeptutor_cli")
    dist_info = installed / "deeptutor-1.5.4.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: deeptutor\nVersion: 1.5.4\n",
        encoding="utf-8",
    )

    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        "\n".join(
            [
                "import os",
                "from deeptutor.update import HttpReleaseProvider",
                ("HttpReleaseProvider.PYPI_URL = os.environ['DEEPTUTOR_TEST_PYPI_URL']"),
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(installed)))
    env["DEEPTUTOR_TEST_PYPI_URL"] = f"http://127.0.0.1:{server.server_port}/pypi/deeptutor/json"
    env.pop("DEEPTUTOR_CONTAINER", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", "update", "--check"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    assert "Installation: pypi" in completed.stdout
    assert "Latest stable: 1.6.0" in completed.stdout


def test_cli_only_user_can_check_for_updates_from_the_real_cli_process(
    tmp_path: Path,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHubReleaseHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    cli_project_uri = (PROJECT_ROOT / "packaging" / "deeptutor-cli").as_uri()
    (hook_dir / "sitecustomize.py").write_text(
        "\n".join(
            [
                "import importlib.metadata as metadata",
                "import json",
                "import os",
                "_real_distribution = metadata.distribution",
                "class _CliDistribution:",
                "    version = '1.5.4'",
                "    def read_text(self, name):",
                "        if name != 'direct_url.json':",
                "            return None",
                (
                    "        return json.dumps({'url': "
                    f"'{cli_project_uri}', "
                    "'dir_info': {'editable': True}})"
                ),
                "def _distribution(name):",
                "    normalized = name.lower().replace('_', '-')",
                "    if normalized == 'deeptutor':",
                "        raise metadata.PackageNotFoundError(name)",
                "    if normalized == 'deeptutor-cli':",
                "        return _CliDistribution()",
                "    return _real_distribution(name)",
                "metadata.distribution = _distribution",
                "from deeptutor.update import HttpReleaseProvider",
                (
                    "HttpReleaseProvider.GITHUB_LATEST_URL = "
                    "os.environ['DEEPTUTOR_TEST_RELEASE_URL']"
                ),
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(PROJECT_ROOT)))
    env["DEEPTUTOR_TEST_RELEASE_URL"] = f"http://127.0.0.1:{server.server_port}/releases/latest"
    env.pop("DEEPTUTOR_CONTAINER", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", "update", "--check"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    assert "Installation: source_cli" in completed.stdout
    assert "Latest stable: 1.6.0" in completed.stdout
