#!/usr/bin/env python
"""DeepTutor Web Launcher — starts backend + frontend from user settings."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_runtime_deps():
    from _cli_kit import banner, bold, dim, log_error, log_info, log_success, log_warn

    from deeptutor.services.config.launch_settings import load_launch_settings

    return banner, bold, dim, log_error, log_info, log_success, log_warn, load_launch_settings


banner, bold, dim, log_error, log_info, log_success, log_warn, load_launch_settings = (
    _load_runtime_deps()
)

STATE_PATH = PROJECT_ROOT / "data" / "user" / "settings" / "start_web_state.json"
BACKEND_READY_TIMEOUT = 60
FRONTEND_READY_TIMEOUT = 120
KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)

MESSAGES = {
    "en": {
        "backend": "Backend",
        "frontend": "Frontend",
        "config_source": "Config source: {source}",
        "npm_missing": "npm not found. Run `python scripts/start_tour.py` first.",
        "port_conflict": "{name} port {port} is already in use.",
        "port_owner": "owner: {command} (PID {pid})",
        "port_owner_unknown": "owner: unknown process",
        "port_hint": "Stop the existing process or run `python scripts/stop_web.py` if it is a stale DeepTutor launch.",
        "cleanup_previous": "Found a stale DeepTutor launch state; cleaning it up first ...",
        "starting_backend": "Starting backend ...",
        "starting_frontend": "Starting frontend ...",
        "waiting_backend": "Waiting for backend at {url} ...",
        "waiting_frontend": "Waiting for frontend at {url} ...",
        "ready_backend": "Backend is ready.",
        "ready_frontend": "Frontend is ready.",
        "ready_timeout": "{name} did not become ready within {seconds}s.",
        "process_exited": "{name} exited with code {code}.",
        "open_url": "Open {url} in your browser.",
        "shutdown_signal": "Received {signal}; shutting down ...",
        "shutdown": "Shutting down ...",
        "stopping": "Stopping {name} (PID {pid})",
        "state_missing": "No DeepTutor launcher state found.",
        "state_stopped": "Stopped recorded DeepTutor processes.",
        "state_invalid": "Ignoring unreadable launcher state.",
    },
    "zh": {
        "backend": "后端",
        "frontend": "前端",
        "config_source": "配置来源：{source}",
        "npm_missing": "未找到 npm。请先运行 `python scripts/start_tour.py`。",
        "port_conflict": "{name}端口 {port} 已被占用。",
        "port_owner": "占用进程：{command} (PID {pid})",
        "port_owner_unknown": "占用进程：未知",
        "port_hint": "请先停止已有进程；如果是上次 DeepTutor 异常退出残留，可运行 `python scripts/stop_web.py`。",
        "cleanup_previous": "发现上次 DeepTutor 启动状态，正在先清理残留进程 ...",
        "starting_backend": "正在启动后端 ...",
        "starting_frontend": "正在启动前端 ...",
        "waiting_backend": "正在等待后端就绪：{url} ...",
        "waiting_frontend": "正在等待前端就绪：{url} ...",
        "ready_backend": "后端已就绪。",
        "ready_frontend": "前端已就绪。",
        "ready_timeout": "{name}在 {seconds}s 内未就绪。",
        "process_exited": "{name}已退出，退出码 {code}。",
        "open_url": "请在浏览器中打开 {url}。",
        "shutdown_signal": "收到 {signal}，正在关闭 ...",
        "shutdown": "正在关闭 ...",
        "stopping": "正在停止 {name} (PID {pid})",
        "state_missing": "未找到 DeepTutor 启动状态。",
        "state_stopped": "已停止记录中的 DeepTutor 进程。",
        "state_invalid": "启动状态文件不可读，已忽略。",
    },
}


@dataclass(slots=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    pgid: int | None


@dataclass(frozen=True, slots=True)
class PortOwner:
    command: str
    pid: int | None


@dataclass(frozen=True, slots=True)
class PortConflict:
    name: str
    port: int
    owners: list[PortOwner]


def _t(language: str, key: str, **kwargs: Any) -> str:
    catalog = MESSAGES.get(language, MESSAGES["en"])
    template = catalog.get(key, MESSAGES["en"][key])
    return template.format(**kwargs)


# ---------------------------------------------------------------------------
# Process and state management
# ---------------------------------------------------------------------------


def _stream_output(prefix: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"  {dim(prefix)}  {line.rstrip()}", flush=True)


def _get_pgid(pid: int | None) -> int | None:
    if pid is None or os.name == "nt":
        return None
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _spawn(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    name: str,
) -> ManagedProcess:
    kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
    thread = threading.Thread(target=_stream_output, args=(name, process), daemon=True)
    thread.start()
    return ManagedProcess(name=name, process=process, pgid=_get_pgid(process.pid))


def _send_tree_signal(pid: int | None, pgid: int | None, sig: int) -> None:
    if pid is None:
        return
    if os.name == "nt":
        # taskkill is the most reliable way to include npm/node child processes.
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if sig == KILL_SIGNAL:
            cmd.append("/F")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    if pgid is not None:
        os.killpg(pgid, sig)
    else:
        os.kill(pid, sig)


def _terminate(process: ManagedProcess | None, language: str) -> None:
    if process is None:
        return

    pid = process.process.pid
    log_info(_t(language, "stopping", name=process.name, pid=pid))
    try:
        if os.name == "nt" and process.process.poll() is None:
            process.process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            _send_tree_signal(pid, process.pgid, signal.SIGTERM)
    except Exception:
        pass

    try:
        process.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            _send_tree_signal(pid, process.pgid, KILL_SIGNAL)
        except Exception:
            try:
                process.process.kill()
            except Exception:
                pass
    except Exception:
        try:
            _send_tree_signal(pid, process.pgid, KILL_SIGNAL)
        except Exception:
            pass


def _read_state(path: Path = STATE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _write_state(
    processes: list[ManagedProcess],
    *,
    backend_port: int,
    frontend_port: int,
    path: Path = STATE_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend_port": backend_port,
        "frontend_port": frontend_port,
        "processes": {
            item.name: {"pid": item.process.pid, "pgid": item.pgid} for item in processes
        },
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _remove_state(path: Path = STATE_PATH) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _state_process_records(state: dict[str, Any]) -> list[tuple[int | None, int | None]]:
    processes = state.get("processes")
    if not isinstance(processes, dict):
        return []
    records: list[tuple[int | None, int | None]] = []
    for raw in processes.values():
        if not isinstance(raw, dict):
            continue
        pid = raw.get("pid")
        pgid = raw.get("pgid")
        records.append(
            (pid if isinstance(pid, int) else None, pgid if isinstance(pgid, int) else None)
        )
    return records


def _terminate_state_processes(state: dict[str, Any]) -> None:
    seen: set[tuple[int | None, int | None]] = set()
    for pid, pgid in _state_process_records(state):
        key = (pid, pgid)
        if key in seen:
            continue
        seen.add(key)
        try:
            _send_tree_signal(pid, pgid, signal.SIGTERM)
        except Exception:
            pass
    time.sleep(1)
    for pid, pgid in seen:
        if _is_pid_alive(pid):
            try:
                _send_tree_signal(pid, pgid, KILL_SIGNAL)
            except Exception:
                pass


def stop_recorded_processes(language: str | None = None) -> bool:
    settings = load_launch_settings(PROJECT_ROOT)
    lang = language or settings.language
    state = _read_state()
    if state is None:
        log_info(_t(lang, "state_missing"))
        return False
    _terminate_state_processes(state)
    _remove_state()
    log_success(_t(lang, "state_stopped"))
    return True


# ---------------------------------------------------------------------------
# Port checks and readiness
# ---------------------------------------------------------------------------


def _port_accepts_connection(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _listening_owners(port: int) -> list[PortOwner]:
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    try:
        result = subprocess.run(
            [lsof, "-n", "-P", f"-iTCP:{port}", "-sTCP:LISTEN"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except Exception:
        return []
    owners: list[PortOwner] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            pid = None
        owners.append(PortOwner(command=parts[0], pid=pid))
    return owners


def _collect_port_conflicts(ports: dict[str, int]) -> list[PortConflict]:
    conflicts: list[PortConflict] = []
    for name, port in ports.items():
        owners = _listening_owners(port)
        if owners or _port_accepts_connection(port):
            conflicts.append(PortConflict(name=name, port=port, owners=owners))
    return conflicts


def _conflicts_match_state(conflicts: list[PortConflict], state: dict[str, Any]) -> bool:
    records = _state_process_records(state)
    state_pids = {pid for pid, _pgid in records if pid is not None}
    state_pgids = {pgid for _pid, pgid in records if pgid is not None}
    if not state_pids and not state_pgids:
        return False
    for conflict in conflicts:
        for owner in conflict.owners:
            if owner.pid in state_pids:
                return True
            owner_pgid = _get_pgid(owner.pid)
            if owner_pgid is not None and owner_pgid in state_pgids:
                return True
    return False


def _state_has_live_process(state: dict[str, Any]) -> bool:
    return any(_is_pid_alive(pid) for pid, _pgid in _state_process_records(state))


def _cleanup_previous_launch_if_safe(ports: dict[str, int], language: str) -> None:
    state = _read_state()
    if state is None:
        return

    state_ports = {
        "backend": state.get("backend_port"),
        "frontend": state.get("frontend_port"),
    }
    conflicts = _collect_port_conflicts(ports)
    ports_match_state = all(state_ports.get(name) == port for name, port in ports.items())
    if conflicts and (
        _conflicts_match_state(conflicts, state)
        or (ports_match_state and _state_has_live_process(state))
    ):
        log_warn(_t(language, "cleanup_previous"))
        _terminate_state_processes(state)
        _remove_state()
        return
    if not conflicts and _state_has_live_process(state):
        log_warn(_t(language, "cleanup_previous"))
        _terminate_state_processes(state)
        _remove_state()
        return
    if not conflicts and not _state_has_live_process(state):
        _remove_state()


def _ensure_ports_available(backend_port: int, frontend_port: int, language: str) -> None:
    ports = {
        _t(language, "backend"): backend_port,
        _t(language, "frontend"): frontend_port,
    }
    state_ports = {"backend": backend_port, "frontend": frontend_port}
    _cleanup_previous_launch_if_safe(state_ports, language)

    conflicts = _collect_port_conflicts(ports)
    if not conflicts:
        return
    for conflict in conflicts:
        log_error(_t(language, "port_conflict", name=conflict.name, port=conflict.port))
        if conflict.owners:
            for owner in conflict.owners:
                log_info(_t(language, "port_owner", command=owner.command, pid=owner.pid))
        else:
            log_info(_t(language, "port_owner_unknown"))
    log_info(_t(language, "port_hint"))
    raise SystemExit(1)


def _wait_for_http(
    *,
    name: str,
    url: str,
    process: ManagedProcess,
    timeout: int,
    language: str,
    waiting_key: str,
    ready_key: str,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    log_info(_t(language, waiting_key, url=url))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if should_stop is not None and should_stop():
            raise SystemExit(0)
        if process.process.poll() is not None:
            log_error(_t(language, "process_exited", name=name, code=process.process.returncode))
            raise SystemExit(1)
        try:
            with urlrequest.urlopen(url, timeout=1):
                log_success(_t(language, ready_key))
                return
        except urlerror.HTTPError as exc:
            if exc.code < 500:
                log_success(_t(language, ready_key))
                return
        except (OSError, urlerror.URLError, TimeoutError):
            pass
        time.sleep(0.5)
    log_error(_t(language, "ready_timeout", name=name, seconds=timeout))
    raise SystemExit(1)


def _install_signal_handlers(request_shutdown: Callable[[str], None]) -> None:
    def _handler(signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        request_shutdown(signal_name)

    for sig_name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            continue


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    settings = load_launch_settings(PROJECT_ROOT)
    language = settings.language
    backend_port = settings.backend_port
    frontend_port = settings.frontend_port
    env_values = settings.env_path.read_text(encoding="utf-8") if settings.env_path.exists() else ""

    def _root_env_value(key: str, default: str = "") -> str:
        prefix = f"{key}="
        for raw_line in env_values.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or not line.startswith(prefix):
                continue
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value or default
        return os.getenv(key, default)

    auth_enabled = (
        _root_env_value("NEXT_PUBLIC_AUTH_ENABLED")
        or _root_env_value("AUTH_ENABLED", "false")
    ).lower() in {"1", "true", "yes", "on"}

    npm = shutil.which("npm")
    if not npm:
        log_error(_t(language, "npm_missing"))
        raise SystemExit(1)

    banner(
        "DeepTutor",
        [
            f"{_t(language, 'backend')}   http://localhost:{backend_port}",
            f"{_t(language, 'frontend')}  http://localhost:{frontend_port}",
        ],
    )
    log_info(_t(language, "config_source", source=settings.source))

    _ensure_ports_available(backend_port, frontend_port, language)

    api_base = f"http://localhost:{backend_port}"

    # Write web/.env.local so the frontend picks up the correct backend port and
    # auth switch even when started independently (e.g. `npm run dev`).
    env_local_path = PROJECT_ROOT / "web" / ".env.local"
    env_local_path.write_text(
        f"# Auto-generated by start_web.py - do not edit manually\n"
        f"NEXT_PUBLIC_API_BASE={api_base}\n"
        f"NEXT_PUBLIC_AUTH_ENABLED={'true' if auth_enabled else 'false'}\n",
        encoding="utf-8",
    )

    backend_env = os.environ.copy()
    backend_env["BACKEND_PORT"] = str(backend_port)
    backend_env["FRONTEND_PORT"] = str(frontend_port)
    backend_env["PYTHONUNBUFFERED"] = "1"
    backend_env["PYTHONIOENCODING"] = "utf-8:replace"

    frontend_env = os.environ.copy()
    frontend_env["BACKEND_PORT"] = str(backend_port)
    frontend_env["FRONTEND_PORT"] = str(frontend_port)
    frontend_env["NEXT_PUBLIC_API_BASE"] = api_base
    frontend_env["AUTH_ENABLED"] = "true" if auth_enabled else "false"
    frontend_env["NEXT_PUBLIC_AUTH_ENABLED"] = "true" if auth_enabled else "false"
    frontend_env["PYTHONIOENCODING"] = "utf-8:replace"

    backend_cmd = [sys.executable, "-m", "deeptutor.api.run_server"]
    frontend_cmd = [npm, "run", "dev", "--", "--port", str(frontend_port)]

    processes: list[ManagedProcess] = []
    frontend: ManagedProcess | None = None
    backend: ManagedProcess | None = None
    shutdown_requested = False
    cleanup_started = False
    exit_code = 0

    def request_shutdown(signal_name: str | None = None) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        if signal_name:
            print()
            log_info(_t(language, "shutdown_signal", signal=signal_name))

    def cleanup() -> None:
        nonlocal cleanup_started
        if cleanup_started:
            return
        cleanup_started = True
        _terminate(frontend, language)
        _terminate(backend, language)
        _remove_state()

    _install_signal_handlers(request_shutdown)
    atexit.register(cleanup)

    try:
        log_info(_t(language, "starting_backend"))
        backend = _spawn(backend_cmd, cwd=PROJECT_ROOT, env=backend_env, name="backend")
        processes.append(backend)
        _write_state(processes, backend_port=backend_port, frontend_port=frontend_port)
        _wait_for_http(
            name=_t(language, "backend"),
            url=f"http://127.0.0.1:{backend_port}/",
            process=backend,
            timeout=BACKEND_READY_TIMEOUT,
            language=language,
            waiting_key="waiting_backend",
            ready_key="ready_backend",
            should_stop=lambda: shutdown_requested,
        )

        log_info(_t(language, "starting_frontend"))
        frontend = _spawn(frontend_cmd, cwd=PROJECT_ROOT / "web", env=frontend_env, name="frontend")
        processes.append(frontend)
        _write_state(processes, backend_port=backend_port, frontend_port=frontend_port)
        _wait_for_http(
            name=_t(language, "frontend"),
            url=f"http://127.0.0.1:{frontend_port}/",
            process=frontend,
            timeout=FRONTEND_READY_TIMEOUT,
            language=language,
            waiting_key="waiting_frontend",
            ready_key="ready_frontend",
            should_stop=lambda: shutdown_requested,
        )

        log_success(_t(language, "open_url", url=bold(f"http://localhost:{frontend_port}")))
        print()

        while not shutdown_requested:
            if backend.process.poll() is not None:
                log_error(
                    _t(
                        language,
                        "process_exited",
                        name=backend.name,
                        code=backend.process.returncode,
                    )
                )
                exit_code = 1
                break
            if frontend.process.poll() is not None:
                log_error(
                    _t(
                        language,
                        "process_exited",
                        name=frontend.name,
                        code=frontend.process.returncode,
                    )
                )
                exit_code = 1
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        log_info(_t(language, "shutdown"))
    finally:
        cleanup()

    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
