"""Sandbox: backend selection, restricted subprocess exec, quota, level gating."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys

import pytest

from deeptutor.services.sandbox.backends import (
    BwrapBackend,
    RestrictedSubprocessBackend,
    _decode_process_output,
)
from deeptutor.services.sandbox.config import SandboxSettings, build_backend
from deeptutor.services.sandbox.quota import QuotaExceeded, UserExecQuota
from deeptutor.services.sandbox.service import SandboxService
from deeptutor.services.sandbox.spec import (
    ExecRequest,
    ExecResult,
    IsolationLevel,
    Mount,
    ResourceLimits,
)


def test_backend_selection_runner_url() -> None:
    from deeptutor.services.sandbox.backends import RunnerSidecarBackend

    settings = SandboxSettings(runner_url="http://sandbox-runner:8900")
    backend = build_backend(settings)
    assert isinstance(backend, RunnerSidecarBackend)
    assert backend.level is IsolationLevel.SYSTEM


def test_backend_selection_none_without_optin() -> None:
    # No runner, subprocess not allowed → no backend (on non-bwrap hosts).
    settings = SandboxSettings(runner_url="", allow_subprocess=False)
    backend = build_backend(settings)
    # On a Linux host with bwrap installed this could be BwrapBackend; the
    # invariant we assert is that subprocess fallback is NOT silently used.
    from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend

    assert not isinstance(backend, RestrictedSubprocessBackend)


def test_backend_selection_subprocess_optin() -> None:
    settings = SandboxSettings(runner_url="", allow_subprocess=True)
    # build_backend prefers bwrap on Linux; force the subprocess path by
    # asserting only when no bwrap candidate is chosen.
    backend = build_backend(settings)
    assert backend is not None


def test_bwrap_binds_usr_local_when_available(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    usr = tmp_path / "usr"
    usr_local = tmp_path / "usr" / "local"
    missing = tmp_path / "missing"
    usr_local.mkdir(parents=True)

    monkeypatch.setattr(
        BwrapBackend,
        "_RO_SYSTEM_DIRS",
        (str(usr), str(usr_local), str(missing)),
    )

    argv = BwrapBackend(bwrap_path="bwrap")._build_argv(ExecRequest(command="true"))

    usr_index = argv.index(str(usr))
    assert argv[usr_index - 1 : usr_index + 2] == ["--ro-bind", str(usr), str(usr)]
    assert str(usr_local) in argv
    assert str(missing) not in argv


def _bwrap_setenv(argv: list[str]) -> dict[str, str]:
    return {
        argv[index + 1]: argv[index + 2] for index, item in enumerate(argv) if item == "--setenv"
    }


def test_bwrap_mounts_only_the_active_virtualenv_read_only(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    venv = workspace / ".venv"
    (venv / "bin").mkdir(parents=True)

    argv = BwrapBackend(venv_path=venv)._build_argv(
        ExecRequest(
            command="python -c 'import pptx'",
            env={"PATH": "/custom/bin:/usr/bin", "VIRTUAL_ENV": "/untrusted"},
        )
    )
    resolved_venv = str(venv.resolve())
    ro_binds = [
        tuple(argv[index + 1 : index + 3]) for index, item in enumerate(argv) if item == "--ro-bind"
    ]
    env = _bwrap_setenv(argv)

    assert (resolved_venv, resolved_venv) in ro_binds
    assert (str(workspace.resolve()), str(workspace.resolve())) not in ro_binds
    assert env["VIRTUAL_ENV"] == resolved_venv
    assert env["PATH"] == f"{resolved_venv}/bin:/custom/bin:/usr/bin"


def test_bwrap_mounts_only_the_uv_python_runtime_roots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = tmp_path / "workspace" / ".venv"
    (venv / "bin").mkdir(parents=True)
    runtime = tmp_path / "uv" / "cpython-3.12.13-linux-x86_64"
    runtime_alias = tmp_path / "uv" / "cpython-3.12-linux-x86_64"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "lib").mkdir()
    runtime_alias.symlink_to(runtime, target_is_directory=True)

    monkeypatch.setattr("sys.prefix", str(venv))
    monkeypatch.setattr("sys.base_prefix", str(runtime))
    monkeypatch.setattr("sys.base_exec_prefix", str(runtime))
    monkeypatch.setattr("sys._base_executable", str(runtime_alias / "bin" / "python3.12"))

    argv = BwrapBackend()._build_argv(ExecRequest(command="python -V"))
    ro_binds = [
        tuple(argv[index + 1 : index + 3]) for index, item in enumerate(argv) if item == "--ro-bind"
    ]

    resolved_runtime = str(runtime.resolve())
    assert (resolved_runtime, resolved_runtime) in ro_binds
    assert (resolved_runtime, str(runtime_alias.absolute())) in ro_binds
    assert (str(venv.resolve()), str(venv.resolve())) in ro_binds
    assert (str((tmp_path / "uv").resolve()), str((tmp_path / "uv").resolve())) not in ro_binds
    assert (str(tmp_path.resolve()), str(tmp_path.resolve())) not in ro_binds


def test_bwrap_virtualenv_mount_overrides_a_writable_parent_mount(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    venv = workspace / ".venv"
    (venv / "bin").mkdir(parents=True)
    resolved_workspace = str(workspace.resolve())
    resolved_venv = str(venv.resolve())

    argv = BwrapBackend(venv_path=venv)._build_argv(
        ExecRequest(
            command="true",
            mounts=(Mount(resolved_workspace, resolved_workspace, read_only=False),),
        )
    )

    writable_index = argv.index(resolved_workspace)
    venv_index = argv.index(resolved_venv)
    assert argv[writable_index - 1 : writable_index + 2] == [
        "--bind",
        resolved_workspace,
        resolved_workspace,
    ]
    assert argv[venv_index - 1 : venv_index + 2] == [
        "--ro-bind",
        resolved_venv,
        resolved_venv,
    ]
    assert venv_index > writable_index


def test_bwrap_can_disable_virtualenv_inheritance() -> None:
    argv = BwrapBackend(inherit_virtualenv=False)._build_argv(
        ExecRequest(command="true", env={"PATH": "/custom/bin"})
    )
    env = _bwrap_setenv(argv)

    assert env == {"PATH": "/custom/bin"}


@pytest.mark.asyncio
async def test_restricted_subprocess_runs() -> None:
    backend = RestrictedSubprocessBackend()
    result = await backend.exec(ExecRequest(command="echo hello"))
    assert result.ok
    assert "hello" in result.stdout
    assert result.exit_code == 0


def test_restricted_subprocess_prefers_configured_virtualenv(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare ``python``/``pip`` must resolve inside DeepTutor's own env.

    A Windows desktop install can inherit MSYS Python before the interpreter
    that launched DeepTutor.  That split makes ``pip install`` and the next
    ``python -c`` target different environments.
    """
    venv = tmp_path / "deeptutor-venv"
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", os.pathsep.join(["foreign-python", "system-tools"]))

    backend = RestrictedSubprocessBackend(venv_path=venv)
    env = backend._build_env({})

    assert env["VIRTUAL_ENV"] == str(venv.resolve())
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir.resolve())
    assert env["PATH"].split(os.pathsep).count(str(bin_dir.resolve())) == 1


def test_restricted_subprocess_request_path_keeps_virtualenv_first(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = tmp_path / "deeptutor-venv"
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", "host-tools")

    backend = RestrictedSubprocessBackend(venv_path=venv)
    env = backend._build_env({"PATH": os.pathsep.join(["turn-tools", str(bin_dir)])})

    assert env["PATH"].split(os.pathsep) == [str(bin_dir.resolve()), "turn-tools"]


def test_backends_inherit_the_conda_environment_that_launched_deeptutor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A base Conda env has prefix == base_prefix but is still authoritative."""
    conda_env = tmp_path / "miniconda" / "envs" / "deeptutor"
    bin_dir = conda_env / ("Scripts" if sys.platform == "win32" else "bin")
    bin_dir.mkdir(parents=True)
    executable = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
    executable.touch()

    monkeypatch.setattr(sys, "prefix", str(conda_env))
    monkeypatch.setattr(sys, "base_prefix", str(conda_env))
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setenv("PATH", "system-tools")

    subprocess_backend = RestrictedSubprocessBackend()
    env = subprocess_backend._build_env({})

    assert env["VIRTUAL_ENV"] == str(conda_env.resolve())
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir.resolve())

    if sys.platform != "win32":
        argv = BwrapBackend()._build_argv(ExecRequest(command="python3 -V"))
        resolved_env = str(conda_env.resolve())
        ro_binds = [
            tuple(argv[index + 1 : index + 3])
            for index, item in enumerate(argv)
            if item == "--ro-bind"
        ]
        assert (resolved_env, resolved_env) in ro_binds
        assert _bwrap_setenv(argv)["PATH"].split(os.pathsep)[0] == str(bin_dir.resolve())


def test_windows_process_output_falls_back_to_the_console_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = "不是内部或外部命令"
    monkeypatch.setattr("deeptutor.services.sandbox.backends.sys.platform", "win32")
    monkeypatch.setattr(
        "deeptutor.services.sandbox.backends.locale.getpreferredencoding",
        lambda _do_setlocale=False: "gbk",
    )

    assert _decode_process_output(message.encode("gbk")) == message


@pytest.mark.asyncio
async def test_restricted_subprocess_timeout() -> None:
    backend = RestrictedSubprocessBackend()
    result = await backend.exec(ExecRequest(command="sleep 5", limits=ResourceLimits(timeout_s=1)))
    assert result.timed_out
    assert result.exit_code == 124


@pytest.mark.asyncio
async def test_restricted_subprocess_caps_output_while_draining_streams() -> None:
    backend = RestrictedSubprocessBackend()
    result = await backend.exec(
        ExecRequest.of_argv(
            [sys.executable, "-X", "utf8", "-c", "print('x' * 50_000, end='')"],
            limits=ResourceLimits(timeout_s=10, max_output_chars=1_000),
        )
    )

    assert result.ok
    assert result.stdout.startswith("x")
    assert result.stdout.endswith("x")
    assert "bytes truncated" in result.stdout
    assert len(result.stdout) < 1_500


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_restricted_subprocess_timeout_kills_descendants(tmp_path) -> None:
    pid_file = tmp_path / "background.pid"
    command = f"sleep 30 & echo $! > {shlex.quote(str(pid_file))}; sleep 30"
    backend = RestrictedSubprocessBackend()

    result = await backend.exec(ExecRequest(command=command, limits=ResourceLimits(timeout_s=1)))

    assert result.timed_out
    assert result.exit_code == 124
    child_pid = int(pid_file.read_text().strip())
    for _ in range(40):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("sandbox timeout left a descendant process running")


@pytest.mark.asyncio
async def test_service_disabled_when_no_backend() -> None:
    svc = SandboxService(SandboxSettings(runner_url="", allow_subprocess=False))
    # Force the "no backend" branch deterministically.
    svc._backend = None
    assert await svc.isolation_level() is IsolationLevel.OFF
    result = await svc.run(ExecRequest(command="echo hi"), user_id="u1")
    assert not result.ok
    assert result.error


@pytest.mark.asyncio
async def test_service_runs_with_subprocess() -> None:
    svc = SandboxService(SandboxSettings(allow_subprocess=True))
    svc._backend = RestrictedSubprocessBackend()
    result = await svc.run(ExecRequest(command="echo sandboxed"), user_id="u1")
    assert "sandboxed" in result.stdout


@pytest.mark.asyncio
async def test_quota_rate_limit() -> None:
    quota = UserExecQuota(max_concurrent=5, max_per_minute=2)
    async with await quota.acquire("u1"):
        pass
    async with await quota.acquire("u1"):
        pass
    with pytest.raises(QuotaExceeded):
        await quota.acquire("u1")
    # a different user is unaffected
    async with await quota.acquire("u2"):
        pass


@pytest.mark.asyncio
async def test_quota_concurrency_limit() -> None:
    quota = UserExecQuota(max_concurrent=1, max_per_minute=100)
    lease = await quota.acquire("u1")
    with pytest.raises(QuotaExceeded):
        await quota.acquire("u1")
    await lease.__aexit__(None, None, None)
    # slot freed
    async with await quota.acquire("u1"):
        pass


def test_exec_result_render_truncates() -> None:
    result = ExecResult(stdout="x" * 1000, exit_code=0)
    rendered = result.render(max_chars=100)
    assert "truncated" in rendered
    assert len(rendered) < 400


def test_exec_result_render_error() -> None:
    assert "boom" in ExecResult(error="boom").render(100)


def test_runner_server_validates_request_shape() -> None:
    from deeptutor.services.sandbox.runner import server

    assert "command" in server.execute({})["error"]
    assert "workdir" in server.execute({"command": "true", "workdir": 123})["error"]
    assert "env" in server.execute({"command": "true", "env": ["bad"]})["error"]
    assert "mounts" in server.execute({"command": "true", "mounts": {"bad": True}})["error"]
    assert "limits" in server.execute({"command": "true", "limits": ["bad"]})["error"]


def test_runner_server_executes_and_truncates_output() -> None:
    from deeptutor.services.sandbox.runner import server

    result = server.execute(
        {
            "command": "python -c \"print('x' * 200)\"",
            "limits": {"timeout_s": 5, "max_output_chars": 40},
        }
    )

    assert result["exit_code"] == 0
    assert result["error"] == ""
    assert "truncated" in result["stdout"]
    assert len(result["stdout"]) < 120


def test_runner_server_rejects_workdir_outside_allowed_roots(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.runner import server

    allowed = tmp_path / "workspace"
    allowed.mkdir()
    monkeypatch.setattr(server, "_ALLOWED_WORKDIR_ROOTS", [str(allowed)])

    outside = server.execute({"command": "true", "workdir": str(tmp_path / "elsewhere")})
    assert "outside the shared workspace roots" in outside["error"]

    # Symlinks that point out of the allowed tree must not slip through.
    sneaky = allowed / "link"
    sneaky.symlink_to(tmp_path)
    via_link = server.execute({"command": "true", "workdir": str(sneaky)})
    assert "outside the shared workspace roots" in via_link["error"]

    inside = server.execute(
        {"command": "true", "workdir": str(allowed), "limits": {"timeout_s": 5}}
    )
    assert inside["error"] == ""
    assert inside["exit_code"] == 0
