from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread
import time

import pytest

from deeptutor.update.jobs import JobStatus, UpdateJobStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


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


def test_pypi_user_can_confirm_an_update_that_runs_after_cli_exit(tmp_path: Path) -> None:
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
                "HttpReleaseProvider.PYPI_URL = os.environ['DEEPTUTOR_TEST_PYPI_URL']",
            ]
        ),
        encoding="utf-8",
    )
    fake_modules = tmp_path / "fake-modules"
    fake_pip = fake_modules / "pip"
    fake_pip.mkdir(parents=True)
    (fake_pip / "__init__.py").write_text("", encoding="utf-8")
    (fake_pip / "__main__.py").write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                (
                    "Path(os.environ['DEEPTUTOR_TEST_PIP_COMMAND']).write_text("
                    "json.dumps(sys.argv[1:]), encoding='utf-8')"
                ),
            ]
        ),
        encoding="utf-8",
    )

    runtime_home = tmp_path / "home"
    command_path = tmp_path / "pip-command.json"
    state_path = runtime_home / "data" / "user" / "update" / "state.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(fake_modules), str(installed)))
    env["DEEPTUTOR_HOME"] = str(runtime_home)
    env["DEEPTUTOR_TEST_PYPI_URL"] = f"http://127.0.0.1:{server.server_port}/pypi/deeptutor/json"
    env["DEEPTUTOR_TEST_PIP_COMMAND"] = str(command_path)
    env.pop("DEEPTUTOR_CONTAINER", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", "update"],
            cwd=tmp_path,
            env=env,
            input="y\n",
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        deadline = time.monotonic() + 20
        state = {}
        while time.monotonic() < deadline:
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") in {"succeeded", "failed"}:
                    break
            time.sleep(0.05)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert completed.returncode == 0, completed.stderr
    assert "Update scheduled:" in completed.stdout
    assert "will not restart" in completed.stdout
    assert state.get("status") == "succeeded", state
    assert json.loads(command_path.read_text(encoding="utf-8")) == [
        "install",
        "--upgrade",
        "--no-input",
        "deeptutor==1.6.0",
    ]


def test_web_worker_restarts_with_persisted_launcher_arguments(tmp_path: Path) -> None:
    fake_modules = tmp_path / "fake-modules"
    fake_pip = fake_modules / "pip"
    fake_pip.mkdir(parents=True)
    (fake_pip / "__init__.py").write_text("", encoding="utf-8")
    (fake_pip / "__main__.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    fake_cli = fake_modules / "deeptutor_cli"
    fake_cli.mkdir()
    (fake_cli / "__init__.py").write_text("", encoding="utf-8")
    (fake_cli / "main.py").write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                (
                    "Path(os.environ['DEEPTUTOR_TEST_RESTART_ARGV']).write_text("
                    "json.dumps(sys.argv[1:]), encoding='utf-8')"
                ),
            ]
        ),
        encoding="utf-8",
    )

    home = tmp_path / "runtime home"
    home.mkdir()
    restart_argv = ("start", "--home", str(home.resolve()), "--dev")
    store = UpdateJobStore(tmp_path / "update")
    job = store.create_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        restart_requested=True,
    )
    store.prepare_restart(job.id, home=home, restart_argv=restart_argv)
    exited_parent = subprocess.Popen([sys.executable, "-c", "pass"])
    exited_parent.wait(timeout=10)
    command_path = tmp_path / "restart-argv.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(fake_modules), str(PROJECT_ROOT)))
    env["DEEPTUTOR_TEST_RESTART_ARGV"] = str(command_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "deeptutor.update.worker",
            "--store-root",
            str(store.root),
            "--parent-pid",
            str(exited_parent.pid),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not command_path.is_file():
        time.sleep(0.05)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(command_path.read_text(encoding="utf-8")) == list(restart_argv)
    assert store.load().status is JobStatus.RESTARTING
    assert store.load().restart_count == 1


@pytest.mark.parametrize("cli_only", [False, True], ids=["full-source", "cli-only-source"])
def test_source_user_can_fast_forward_from_the_real_cli_process(
    tmp_path: Path,
    cli_only: bool,
) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _run_git(tmp_path, "init", "--bare", str(remote))
    _run_git(tmp_path, "init", "--initial-branch=main", str(seed))
    _run_git(seed, "config", "user.email", "tests@example.com")
    _run_git(seed, "config", "user.name", "DeepTutor Tests")
    (seed / "deeptutor").mkdir()
    (seed / "deeptutor" / "__init__.py").write_text("", encoding="utf-8")
    (seed / "pyproject.toml").write_text(
        "[project]\nname='deeptutor'\n",
        encoding="utf-8",
    )
    cli_project = seed / "packaging" / "deeptutor-cli"
    cli_project.mkdir(parents=True)
    (cli_project / "pyproject.toml").write_text(
        "[project]\nname='deeptutor-cli'\n",
        encoding="utf-8",
    )
    (seed / "web").mkdir()
    (seed / "web" / "package-lock.json").write_text("unchanged\n", encoding="utf-8")
    (seed / "release.txt").write_text("base\n", encoding="utf-8")
    _run_git(seed, "add", ".")
    _run_git(seed, "commit", "-m", "base")
    _run_git(seed, "remote", "add", "origin", str(remote))
    _run_git(seed, "push", "-u", "origin", "main")
    _run_git(tmp_path, "clone", str(remote), str(checkout))
    (seed / "release.txt").write_text("stable\n", encoding="utf-8")
    _run_git(seed, "add", ".")
    _run_git(seed, "commit", "-m", "stable release")
    target = _run_git(seed, "rev-parse", "HEAD")
    _run_git(seed, "tag", "v1.6.0")
    _run_git(seed, "push", "origin", "main", "v1.6.0")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitHubReleaseHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    checkout_uri = checkout.as_uri()
    if cli_only:
        detection_hook = [
            "from pathlib import Path",
            "import deeptutor.update as update_module",
            "from deeptutor.update import Installation, InstallMode",
            "def _detect_installation():",
            (
                "    return Installation(mode=InstallMode.SOURCE_CLI, "
                "current_version='1.5.4', package_name='deeptutor-cli', "
                f"source_root=Path({str(checkout)!r}))"
            ),
            "update_module.detect_current_installation = _detect_installation",
        ]
    else:
        detection_hook = [
            "import importlib.metadata as metadata",
            "import json",
            "_real_distribution = metadata.distribution",
            "class _SourceDistribution:",
            "    version = '1.5.4'",
            "    def read_text(self, name):",
            "        if name != 'direct_url.json':",
            "            return None",
            (
                "        return json.dumps({'url': "
                f"'{checkout_uri}', "
                "'dir_info': {'editable': True}})"
            ),
            "def _distribution(name):",
            "    normalized = name.lower().replace('_', '-')",
            "    if normalized == 'deeptutor':",
            "        return _SourceDistribution()",
            "    if normalized == 'deeptutor-cli':",
            "        raise metadata.PackageNotFoundError(name)",
            "    return _real_distribution(name)",
            "metadata.distribution = _distribution",
        ]
    (hook_dir / "sitecustomize.py").write_text(
        "\n".join(
            [
                "import os",
                *detection_hook,
                "from deeptutor.update import HttpReleaseProvider",
                (
                    "HttpReleaseProvider.GITHUB_LATEST_URL = "
                    "os.environ['DEEPTUTOR_TEST_RELEASE_URL']"
                ),
            ]
        ),
        encoding="utf-8",
    )
    fake_modules = tmp_path / "fake-modules"
    fake_pip = fake_modules / "pip"
    fake_pip.mkdir(parents=True)
    (fake_pip / "__init__.py").write_text("", encoding="utf-8")
    (fake_pip / "__main__.py").write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "import sys",
                "if sys.argv[1:] == ['--version']:",
                "    print('pip test')",
                "else:",
                (
                    "    Path(os.environ['DEEPTUTOR_TEST_PIP_COMMAND']).write_text("
                    "json.dumps(sys.argv[1:]), encoding='utf-8')"
                ),
            ]
        ),
        encoding="utf-8",
    )
    command_path = tmp_path / "source-pip-command.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(fake_modules), str(PROJECT_ROOT)))
    env["DEEPTUTOR_TEST_RELEASE_URL"] = f"http://127.0.0.1:{server.server_port}/releases/latest"
    env["DEEPTUTOR_TEST_PIP_COMMAND"] = str(command_path)
    env["DEEPTUTOR_HOME"] = str(tmp_path / "runtime-home")
    env.pop("DEEPTUTOR_CONTAINER", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", "update"],
            cwd=checkout,
            env=env,
            input="y\n",
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
    package_name = "deeptutor-cli" if cli_only else "deeptutor"
    assert f"Update {package_name} from " in completed.stdout
    assert " to 1.6.0?" in completed.stdout
    assert "Source update complete" in completed.stdout
    assert _run_git(checkout, "rev-parse", "HEAD") == target
    assert json.loads(command_path.read_text(encoding="utf-8")) == [
        "install",
        "--no-deps",
        "--editable",
        str(
            (checkout / "packaging" / "deeptutor-cli").resolve() if cli_only else checkout.resolve()
        ),
    ]
