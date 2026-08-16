"""Local Web launcher for the installed DeepTutor app."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import hashlib
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
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from deeptutor.runtime.banner import labels_for, print_banner, resolve_language
from deeptutor.runtime.home import DEEPTUTOR_HOME_ENV, PACKAGE_ROOT, get_runtime_home
from deeptutor.runtime.memory_probe import SUPERVISOR_PID_ENV

BACKEND_READY_TIMEOUT = 60
FRONTEND_READY_TIMEOUT = 120
KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
SOURCE_PRODUCTION_DIST_DIR = "dist"
SOURCE_BUILD_MARKER = ".deeptutor-build.json"
SOURCE_BUILD_EXCLUDED_DIRS = {
    "node_modules",
    "dist",
    "playwright-report",
    "test-results",
    "coverage",
}


def _apply_single_user_allocator_env(env: dict[str, str]) -> None:
    """Reduce glibc arena fragmentation without overriding operator tuning."""

    env.setdefault("MALLOC_ARENA_MAX", "2")
    env.setdefault("MALLOC_TRIM_THRESHOLD_", "131072")


# Mutable holder so module-level helpers can format messages in the active
# UI language without threading the labels through every function.
_ACTIVE_LABELS: dict[str, str] = labels_for("en")


def _t(key: str, **kwargs: object) -> str:
    template = _ACTIVE_LABELS.get(key) or labels_for("en").get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


@dataclass(slots=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    pgid: int | None


@dataclass(frozen=True, slots=True)
class FrontendRuntime:
    kind: str
    command: list[str]
    cwd: Path
    spa_dir: Path | None = None


def _log(message: str) -> None:
    print(message, flush=True)


def _reset_runtime_singletons() -> None:
    """Make a just-selected DEEPTUTOR_HOME visible to path/config singletons."""
    try:
        from deeptutor.services.path_service import PathService

        PathService.reset_instance()
    except Exception:
        pass
    try:
        from deeptutor.services.config.runtime_settings import RuntimeSettingsService

        RuntimeSettingsService._instances.clear()
    except Exception:
        pass
    try:
        from deeptutor.services.config.model_catalog import ModelCatalogService

        ModelCatalogService._instances.clear()
    except Exception:
        pass


def _get_pgid(pid: int | None) -> int | None:
    if pid is None or os.name == "nt":
        return None
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _send_tree_signal(pid: int | None, pgid: int | None, sig: signal.Signals | int) -> None:
    if pid is None:
        return
    if os.name == "nt":
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if sig == KILL_SIGNAL:
            cmd.append("/F")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    if os.name != "nt" and pgid is not None:
        os.killpg(pgid, sig)
    else:
        os.kill(pid, sig)


def _terminate(proc: ManagedProcess | None) -> None:
    if proc is None or proc.process.poll() is not None:
        return
    _log(_t("start.stopping", name=proc.name, pid=proc.process.pid))
    try:
        _send_tree_signal(proc.process.pid, proc.pgid, signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            _send_tree_signal(proc.process.pid, proc.pgid, KILL_SIGNAL)
        except Exception:
            pass


def _relax_console_encoding(streams: tuple[object, ...] | None = None) -> None:
    """Make the launcher's own console output lossy instead of fatal.

    Child pipes are already decoded with ``errors="replace"`` (see ``_spawn``)
    and the children themselves get ``PYTHONIOENCODING=utf-8:replace``, but the
    parent process re-encodes every relayed line with the console's own codec.
    On a legacy Windows code page (cp950/cp936/cp932) an ordinary Vite
    banner character like ``✓`` then raises ``UnicodeEncodeError`` inside
    ``_stream_output``, killing the relay thread — the app keeps running but
    goes silent for the rest of the session (issue #702).
    """
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            # Already-detached or non-reconfigurable stream: nothing to relax.
            continue


def _stream_output(prefix: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"  {prefix:<8} {line.rstrip()}", flush=True)


def _spawn(command: list[str], *, cwd: Path, env: dict[str, str], name: str) -> ManagedProcess:
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
    process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type,call-overload]
    thread = threading.Thread(target=_stream_output, args=(name, process), daemon=True)
    thread.start()
    return ManagedProcess(name=name, process=process, pgid=_get_pgid(process.pid))


def _port_accepts_connection(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _port_listeners(port: int) -> list[tuple[int, str]]:
    """Best-effort list of ``(pid, command)`` for processes listening on ``port``."""
    if os.name == "nt":
        return _port_listeners_windows(port)
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    try:
        completed = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        if not line.startswith("p"):
            continue
        try:
            pid = int(line[1:])
        except ValueError:
            continue
        if pid not in pids:
            pids.append(pid)
    return [(pid, _process_command(pid) or "?") for pid in pids]


def _port_listeners_windows(port: int) -> list[tuple[int, str]]:
    netstat = shutil.which("netstat")
    if not netstat:
        return []
    try:
        completed = subprocess.run(
            [netstat, "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if not parts[1].endswith(f":{port}"):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid not in pids:
            pids.append(pid)
    tasklist = shutil.which("tasklist")
    listeners: list[tuple[int, str]] = []
    for pid in pids:
        name = ""
        if tasklist:
            try:
                result = subprocess.run(
                    [tasklist, "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                first = result.stdout.strip().splitlines()[:1]
                if first and first[0].startswith('"'):
                    name = first[0].split('","')[0].strip('"')
            except Exception:
                name = ""
        listeners.append((pid, name or "?"))
    return listeners


def _suggest_free_port(preferred: int, taken: set[int]) -> int:
    for candidate in range(preferred, min(preferred + 200, 65536)):
        if candidate not in taken and not _port_accepts_connection(candidate):
            return candidate
    return preferred


def _prompt_port(label: str, *, default: int, taken: set[int]) -> int:
    while True:
        try:
            raw = input(f"{label} [{default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(130) from None
        value = raw or str(default)
        try:
            port = int(value)
        except ValueError:
            port = -1
        if 1 <= port <= 65535 and port not in taken and not _port_accepts_connection(port):
            return port
        _log(_t("start.port_invalid", value=value))


def _prompt_conflict_choice() -> str:
    _log("")
    _log(f"  [1] {_t('start.port_option_change')}")
    _log(f"  [2] {_t('start.port_option_kill')}")
    while True:
        try:
            raw = input(f"{_t('init.choice')} [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(130) from None
        if raw in {"1", "2"}:
            return raw
        _log(_t("init.choice_invalid"))


def _persist_ports(settings_dir: Path, backend_port: int, frontend_port: int) -> Path:
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    service = RuntimeSettingsService.get_instance(settings_dir)
    system = service.load_system(include_process_overrides=False)
    system["backend_port"] = backend_port
    system["frontend_port"] = frontend_port
    service.save_system(system)
    return service.path_for("system")


def _prompt_new_ports(
    *,
    backend_port: int,
    frontend_port: int,
    check_frontend: bool,
    settings_dir: Path,
) -> tuple[int, int]:
    backend_occupied = _port_accepts_connection(backend_port)
    new_backend = _prompt_port(
        _t("init.backend_port"),
        default=_suggest_free_port(backend_port + 1, {frontend_port})
        if backend_occupied
        else backend_port,
        taken={frontend_port} if check_frontend else set(),
    )
    new_frontend = frontend_port
    if check_frontend:
        frontend_occupied = _port_accepts_connection(frontend_port)
        new_frontend = _prompt_port(
            _t("init.frontend_port"),
            default=_suggest_free_port(frontend_port + 1, {new_backend})
            if frontend_occupied
            else frontend_port,
            taken={new_backend},
        )
    path = _persist_ports(settings_dir, new_backend, new_frontend)
    _log(_t("start.port_saved", path=path))
    return new_backend, new_frontend


def _kill_port_listeners(listeners: dict[int, list[tuple[int, str]]]) -> None:
    for port, entries in listeners.items():
        for pid, command in entries:
            _log(_t("start.port_killing", pid=pid, command=command))
            try:
                _send_tree_signal(pid, None, signal.SIGTERM)
            except Exception:
                pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _port_accepts_connection(port):
            time.sleep(0.2)
        if _port_accepts_connection(port):
            for pid, _command in entries:
                try:
                    _send_tree_signal(pid, None, KILL_SIGNAL)
                except Exception:
                    pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and _port_accepts_connection(port):
                time.sleep(0.2)
        if _port_accepts_connection(port):
            pids = ", ".join(str(pid) for pid, _command in entries) or "?"
            _log(_t("start.port_kill_failed", port=port, pid=pids))
        else:
            _log(_t("start.port_freed", port=port))


def _resolve_port_conflicts(
    *,
    backend_port: int,
    frontend_port: int,
    check_frontend: bool,
    settings_dir: Path,
) -> tuple[int, int]:
    """Return free ``(backend_port, frontend_port)``, resolving conflicts interactively.

    When stdin is not a TTY (Docker, CI), falls back to exiting with the
    historical ``start.port_in_use`` message.
    """
    while True:
        roles = [("start.backend", backend_port)]
        if check_frontend:
            roles.append(("start.frontend", frontend_port))
        occupied = [(key, port) for key, port in roles if _port_accepts_connection(port)]
        if not occupied:
            return backend_port, frontend_port

        listeners = {port: _port_listeners(port) for _key, port in occupied}
        _log(_t("start.port_conflict_title"))
        for key, port in occupied:
            _log(_t("start.port_conflict_line", role=_t(key), port=port))
            entries = listeners[port]
            if not entries:
                _log(_t("start.port_conflict_unknown_proc"))
            for pid, command in entries:
                _log(_t("start.port_conflict_proc", pid=pid, command=command))

        if sys.stdin is None or not sys.stdin.isatty():
            joined = ", ".join(str(port) for _key, port in occupied)
            raise SystemExit(_t("start.port_in_use", ports=joined))

        if _prompt_conflict_choice() == "1":
            backend_port, frontend_port = _prompt_new_ports(
                backend_port=backend_port,
                frontend_port=frontend_port,
                check_frontend=check_frontend,
                settings_dir=settings_dir,
            )
        else:
            _kill_port_listeners(listeners)


def _wait_for_http(
    *,
    name: str,
    url: str,
    process: ManagedProcess | None,
    timeout: int,
    should_stop: Callable[[], bool],
) -> None:
    _log(_t("start.waiting_for", name=name, url=url))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if should_stop():
            return
        if process is not None and process.process.poll() is not None:
            raise RuntimeError(_t("start.exited", name=name, code=process.process.returncode))
        try:
            with urlrequest.urlopen(url, timeout=1):  # noqa: S310  # nosec B310 - http(s) health-check URL constructed by caller
                _log(_t("start.ready", name=name))
                return
        except (urlerror.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    raise RuntimeError(_t("start.not_ready", name=name, timeout=timeout))


def _packaged_web_dir() -> Path | None:
    try:
        import deeptutor_web
    except ImportError:
        return None
    path = Path(deeptutor_web.__file__).resolve().parent
    return path if (path / "index.html").is_file() else None


def _source_web_dir(home: Path) -> Path | None:
    candidates = [home / "frontend", PACKAGE_ROOT / "frontend"]
    for path in candidates:
        if (path / "package.json").exists() and (path / "index.html").exists():
            return path
    return None


def _ensure_web_dependencies(source: Path, npm: str) -> None:
    """Install ``frontend/node_modules`` on a source checkout that has none.

    ``pip install -e ".[cli]"`` never touches npm, so a fresh clone would hand
    the Vite dev server a missing ``vite`` binary and die on Node's
    MODULE_NOT_FOUND. Prefer ``npm ci`` — reproducible and faster — and fall
    back to ``npm install`` when the checkout has no lockfile. Output is left
    on the terminal so a failing install explains itself. No-op once
    installed, which keeps it cheap on the launcher's repeated resolve path.
    """
    if (source / "node_modules").exists():
        return
    action = "ci" if (source / "package-lock.json").exists() else "install"
    _log(f"frontend/node_modules not found — running `npm {action}` in {source} ...")
    result = subprocess.run([npm, action], cwd=source)
    if result.returncode != 0:
        raise SystemExit(
            f"`npm {action}` failed (exit {result.returncode}). "
            "Fix the error above, then retry `deeptutor start`."
        )


def _source_build_fingerprint(source: Path) -> str:
    """Hash source inputs so a production build can be reused."""

    digest = hashlib.sha256()
    version_file = PACKAGE_ROOT / "deeptutor" / "__version__.py"
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SOURCE_BUILD_EXCLUDED_DIRS and not name.startswith(".")
        )
        root = Path(dirpath)
        candidates.extend(root / name for name in sorted(filenames))
    if version_file.is_file():
        candidates.append(version_file)

    for path in candidates:
        relative = (
            path.relative_to(source).as_posix()
            if path.is_relative_to(source)
            else f"../deeptutor/{path.name}"
        )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _ensure_source_production_build(source: Path, npm: str) -> Path:
    """Build source installs once, then reuse them until an input changes."""

    dist = source / SOURCE_PRODUCTION_DIST_DIR
    marker = dist / SOURCE_BUILD_MARKER
    payload = {"fingerprint": _source_build_fingerprint(source)}
    if (dist / "index.html").is_file():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) == payload:
                return dist
        except Exception:
            pass

    _log(f"Building the source frontend for production in {source} ...")
    result = subprocess.run([npm, "run", "build"], cwd=source)
    if result.returncode != 0:
        raise SystemExit(
            f"`npm run build` failed (exit {result.returncode}). "
            "Fix the error above, then retry `deeptutor start`."
        )
    if not (dist / "index.html").is_file():
        raise SystemExit(f"`npm run build` completed without creating {dist / 'index.html'}.")
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dist


def _spa_server_command(frontend_port: int) -> list[str]:
    from deeptutor.services.config import HTTP_KEEP_ALIVE_TIMEOUT

    return [
        sys.executable,
        "-m",
        "uvicorn",
        "deeptutor.runtime.spa_server:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(frontend_port),
        "--no-access-log",
        "--timeout-keep-alive",
        str(HTTP_KEEP_ALIVE_TIMEOUT),
    ]


def _resolve_frontend(
    home: Path,
    frontend_port: int,
    *,
    api_base: str,
    auth_enabled: bool,
    dev: bool = False,
) -> FrontendRuntime:
    del api_base, auth_enabled
    packaged = _packaged_web_dir()
    if packaged is not None:
        return FrontendRuntime(
            "packaged",
            _spa_server_command(frontend_port),
            packaged,
            packaged,
        )

    source = _source_web_dir(home)
    if source is not None:
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit(
                "npm not found. Source installs require Node.js/npm and "
                "`cd frontend && npm install`."
            )
        _ensure_web_dependencies(source, npm)
        if not dev:
            dist = _ensure_source_production_build(source, npm)
            return FrontendRuntime(
                "source-production",
                _spa_server_command(frontend_port),
                source,
                dist,
            )
        return FrontendRuntime(
            "source",
            [
                npm,
                "run",
                "dev",
                "--",
                "--host",
                "0.0.0.0",
                "--port",
                str(frontend_port),
            ],
            source,
        )

    raise SystemExit(
        "DeepTutor Web assets are not installed. Install the full app with `pip install -U deeptutor`, "
        "or run from a source checkout that contains `frontend/`."
    )


def _process_command(pid: int | None) -> str:
    if pid is None or os.name == "nt":
        return ""
    ps = shutil.which("ps")
    if not ps:
        return ""
    try:
        completed = subprocess.run(
            [ps, "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return completed.stdout.strip()


def _install_signal_handlers(request_shutdown: Callable[[str | None], None]) -> None:
    def _handler(signum: int, _frame) -> None:
        try:
            signal_name = signal.Signals(signum).name
        except ValueError:
            signal_name = str(signum)
        request_shutdown(signal_name)

    for sig_name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            continue


def start(home: str | Path | None = None, *, dev: bool = False) -> None:
    _relax_console_encoding()
    runtime_home = get_runtime_home(home)
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ[DEEPTUTOR_HOME_ENV] = str(runtime_home)
    _reset_runtime_singletons()

    from deeptutor.services.config import (
        HTTP_KEEP_ALIVE_TIMEOUT,
        ensure_runtime_settings_files,
        export_runtime_settings_to_env,
        get_ws_max_size,
        load_auth_settings,
        load_launch_settings,
    )
    from deeptutor.services.setup import init_user_directories

    init_user_directories(runtime_home)
    ensure_runtime_settings_files()
    settings = load_launch_settings(runtime_home)
    runtime_env = export_runtime_settings_to_env(overwrite=True)
    auth_enabled = bool(load_auth_settings()["enabled"])

    global _ACTIVE_LABELS
    language = resolve_language()
    _ACTIVE_LABELS = labels_for(language)

    backend_port = settings.backend_port
    frontend_port = settings.frontend_port
    backend_url = f"http://127.0.0.1:{backend_port}"
    api_base = (
        runtime_env.get("NEXT_PUBLIC_API_BASE_EXTERNAL")
        or runtime_env.get("NEXT_PUBLIC_API_BASE")
        or backend_url
    )
    frontend = _resolve_frontend(
        runtime_home,
        frontend_port,
        api_base=api_base,
        auth_enabled=auth_enabled,
        dev=dev,
    )

    resolved_backend, resolved_frontend = _resolve_port_conflicts(
        backend_port=backend_port,
        frontend_port=frontend_port,
        check_frontend=True,
        settings_dir=settings.settings_dir,
    )
    if (resolved_backend, resolved_frontend) != (backend_port, frontend_port):
        backend_port, frontend_port = resolved_backend, resolved_frontend
        runtime_env = export_runtime_settings_to_env(overwrite=True)
        backend_url = f"http://127.0.0.1:{backend_port}"
        api_base = (
            runtime_env.get("NEXT_PUBLIC_API_BASE_EXTERNAL")
            or runtime_env.get("NEXT_PUBLIC_API_BASE")
            or backend_url
        )
        frontend = _resolve_frontend(
            runtime_home,
            frontend_port,
            api_base=api_base,
            auth_enabled=auth_enabled,
            dev=dev,
        )

    frontend_url = f"http://localhost:{frontend_port}"

    print_banner(language=language, mode_key="start.mode")
    _log(f"{_t('start.backend'):<10} {backend_url}")
    if api_base != backend_url:
        _log(f"{_t('start.browser_api'):<10} {api_base}")
    _log(f"{_t('start.frontend'):<10} {frontend_url}")
    _log(f"{_t('start.workspace'):<10} {runtime_home}")
    _log(f"{_t('start.frontend_runtime')}: {frontend.kind}")
    _log(_t("start.press_ctrl_c"))

    common_env = os.environ.copy()
    common_env.update(runtime_env)
    common_env[DEEPTUTOR_HOME_ENV] = str(runtime_home)
    common_env["BACKEND_PORT"] = str(backend_port)
    common_env["FRONTEND_PORT"] = str(frontend_port)
    common_env["PORT"] = str(frontend_port)
    common_env["HOSTNAME"] = "0.0.0.0"
    common_env["NEXT_PUBLIC_API_BASE"] = api_base
    common_env["NEXT_PUBLIC_AUTH_ENABLED"] = "true" if auth_enabled else "false"
    # The SPA server (and Vite in --dev) read these at request time to forward
    # /api/* and /ws/* to the backend. The browser uses relative paths, so the
    # frontend server reaches the backend on the IPv4 loopback at the resolved
    # port — use backend_url (not api_base, which may be an external browser URL).
    common_env["DEEPTUTOR_API_BASE_URL"] = backend_url
    common_env["DEEPTUTOR_AUTH_ENABLED"] = "true" if auth_enabled else "false"
    if frontend.spa_dir is not None:
        common_env["DEEPTUTOR_SPA_DIR"] = str(frontend.spa_dir)
    common_env["PYTHONUNBUFFERED"] = "1"
    common_env["PYTHONIOENCODING"] = "utf-8:replace"
    # Anchor for deeptutor.runtime.memory_probe: the backend and the frontend
    # are siblings under this process, so only the supervisor's pid identifies
    # the tree that is "DeepTutor". Without it the probe can only measure the
    # backend itself.
    common_env[SUPERVISOR_PID_ENV] = str(os.getpid())
    _apply_single_user_allocator_env(common_env)

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "deeptutor.api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(backend_port),
        "--log-level",
        "info",
        # Disable uvicorn's per-request access log. The selective_access_log
        # middleware (deeptutor/api/main.py) surfaces only non-200s, so routine
        # 200 polling (/settings, /tools, /knowledge/list, ...) stays out of the
        # logs — matching run_server.py's access_log=False.
        "--no-access-log",
        # Chat attachments ride the unified WS as base64 in one JSON message;
        # uvicorn's default 16MB frame cap would sever the socket on uploads
        # allowed by the configured policy. Derived from system.json — raising
        # the attachment limits therefore takes a restart to fully apply.
        "--ws-max-size",
        str(get_ws_max_size()),
        # Outlast the frontend proxy's idle socket pool. The SPA server
        # forwards over httpx, which reaps idle sockets on a 60s timer; stay
        # well above that so the client is the only side retiring connections.
        "--timeout-keep-alive",
        str(HTTP_KEEP_ALIVE_TIMEOUT),
    ]

    processes: list[ManagedProcess] = []
    backend: ManagedProcess | None = None
    web: ManagedProcess | None = None
    shutdown_requested = False
    cleanup_started = False
    exit_code = 0

    def request_shutdown(signal_name: str | None = None) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        if signal_name:
            _log(_t("start.received_signal", signal=signal_name))

    def cleanup() -> None:
        nonlocal cleanup_started
        if cleanup_started:
            return
        cleanup_started = True
        _terminate(web)
        _terminate(backend)

    _install_signal_handlers(request_shutdown)
    atexit.register(cleanup)

    try:
        _log(_t("start.starting_backend"))
        backend = _spawn(backend_cmd, cwd=runtime_home, env=common_env, name="backend")
        processes.append(backend)
        _wait_for_http(
            name=_t("start.backend"),
            url=f"http://127.0.0.1:{backend_port}/",
            process=backend,
            timeout=BACKEND_READY_TIMEOUT,
            should_stop=lambda: shutdown_requested,
        )

        _log(_t("start.starting_frontend"))
        web = _spawn(frontend.command, cwd=frontend.cwd, env=common_env, name="frontend")
        processes.append(web)
        _wait_for_http(
            name=_t("start.frontend"),
            url=f"http://127.0.0.1:{frontend_port}/",
            process=web,
            timeout=FRONTEND_READY_TIMEOUT,
            should_stop=lambda: shutdown_requested,
        )
        _log(_t("start.open_in_browser", url=frontend_url))

        while not shutdown_requested:
            for proc in processes:
                if proc.process.poll() is not None:
                    _log(_t("start.exited", name=proc.name, code=proc.process.returncode))
                    exit_code = 1
                    shutdown_requested = True
                    break
            time.sleep(1)
    except KeyboardInterrupt:
        request_shutdown("SIGINT")
    finally:
        cleanup()

    if exit_code:
        raise SystemExit(exit_code)


__all__ = ["start"]
