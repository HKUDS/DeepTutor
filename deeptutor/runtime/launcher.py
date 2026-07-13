"""Local Web launcher for the installed DeepTutor app."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
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
from urllib import parse as urlparse
from urllib import request as urlrequest

from deeptutor.runtime.banner import labels_for, print_banner, resolve_language
from deeptutor.runtime.home import DEEPTUTOR_HOME_ENV, PACKAGE_ROOT, get_runtime_home

BACKEND_READY_TIMEOUT = 60
FRONTEND_READY_TIMEOUT = 120
FRONTEND_REUSE_PROBE_TIMEOUT = 2
KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
WEB_CACHE_DIR = Path("data") / "user" / "runtime" / "web"

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


@dataclass(frozen=True, slots=True)
class ExistingFrontendRuntime:
    url: str
    port: int
    pid: int | None
    lock_path: Path


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


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


def _http_ready(url: str, *, timeout: float) -> bool:
    try:
        with urlrequest.urlopen(url, timeout=timeout):  # noqa: S310  # nosec B310 - launcher health check
            return True
    except (urlerror.URLError, TimeoutError, OSError):
        return False


def _packaged_web_dir() -> Path | None:
    try:
        import deeptutor_web
    except ImportError:
        return None
    path = Path(deeptutor_web.__file__).resolve().parent
    return path if (path / "server.js").exists() else None


def _copy_packaged_web_if_needed(
    packaged: Path,
    *,
    home: Path,
    api_base: str,
    auth_enabled: bool,
) -> Path:
    """Copy packaged Next.js standalone files into a writable runtime cache.

    Next public variables are inlined at build time, so placeholders must be
    replaced before ``server.js`` starts. The installed package may live in a
    read-only site-packages directory; the cache keeps mutation local to the
    active workspace.
    """

    cache = home / WEB_CACHE_DIR
    marker = cache / ".deeptutor-web-runtime.json"
    source_server = packaged / "server.js"
    marker_payload = {
        "source": str(packaged),
        "source_mtime_ns": source_server.stat().st_mtime_ns,
        "api_base": api_base,
        "auth_enabled": bool(auth_enabled),
    }
    if (cache / "server.js").exists():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) == marker_payload:
                return cache
        except Exception:
            pass

    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(packaged, cache)
    _patch_packaged_web_placeholders(
        cache,
        api_base=api_base,
        auth_enabled="true" if auth_enabled else "false",
    )
    marker.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
    return cache


def _patch_packaged_web_placeholders(
    web_dir: Path,
    *,
    api_base: str,
    auth_enabled: str,
) -> None:
    replacements = {
        "__NEXT_PUBLIC_API_BASE_PLACEHOLDER__": api_base,
        "__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__": auth_enabled,
    }
    roots = [web_dir / ".next", web_dir / "server.js"]
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*") if root.exists() else []
        for path in paths:
            if not path.is_file() or path.suffix not in {".js", ".json", ".html", ".txt"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            updated = text
            for placeholder, value in replacements.items():
                updated = updated.replace(placeholder, value)
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def _source_web_dir(home: Path) -> Path | None:
    candidates = [home / "web", PACKAGE_ROOT / "web"]
    for path in candidates:
        if (path / "package.json").exists():
            return path
    return None


def _resolve_frontend(
    home: Path,
    frontend_port: int,
    *,
    api_base: str,
    auth_enabled: bool,
) -> FrontendRuntime:
    packaged = _packaged_web_dir()
    node = shutil.which("node")
    if packaged is not None:
        if not node:
            raise SystemExit("Node.js 20+ is required to run the packaged DeepTutor Web app.")
        runtime_web = _copy_packaged_web_if_needed(
            packaged,
            home=home,
            api_base=api_base,
            auth_enabled=auth_enabled,
        )
        return FrontendRuntime("packaged", [node, str(runtime_web / "server.js")], runtime_web)

    source = _source_web_dir(home)
    if source is not None:
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit(
                "npm not found. Source installs require Node.js/npm and `cd web && npm install`."
            )
        return FrontendRuntime(
            "source", [npm, "run", "dev", "--", "--port", str(frontend_port)], source
        )

    raise SystemExit(
        "DeepTutor Web assets are not installed. Install the full app with `pip install -U deeptutor`, "
        "or run from a source checkout that contains `web/`."
    )


def _coerce_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _coerce_port(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _local_app_url(value: object, port: int) -> str:
    fallback = f"http://localhost:{port}"
    if not isinstance(value, str) or not value.strip():
        return fallback
    raw = value.strip().rstrip("/")
    try:
        parsed = urlparse.urlparse(raw)
    except ValueError:
        return fallback
    if parsed.scheme not in {"http", "https"}:
        return fallback
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return fallback
    if parsed.port != port:
        return fallback
    return raw


def _detect_existing_source_frontend(frontend: FrontendRuntime) -> ExistingFrontendRuntime | None:
    """Return an already-running Next dev server for this source checkout."""

    if frontend.kind != "source":
        return None

    lock_candidates = [
        frontend.cwd / ".next" / "dev" / "lock",
        frontend.cwd / ".next" / "lock",
    ]
    for lock_path in lock_candidates:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        port = _coerce_port(payload.get("port"))
        if port is None:
            continue
        pid = _coerce_pid(payload.get("pid"))
        if not _is_pid_alive(pid) and not _port_accepts_connection(port):
            continue
        return ExistingFrontendRuntime(
            url=_local_app_url(payload.get("appUrl"), port),
            port=port,
            pid=pid,
            lock_path=lock_path,
        )
    return None


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


def _looks_like_next_process(pid: int | None) -> bool:
    command = _process_command(pid).lower()
    return bool(
        command
        and ("next-server" in command or "next/dist/bin/next" in command or " next dev" in command)
    )


def _stop_unhealthy_source_frontend(frontend: ExistingFrontendRuntime) -> bool:
    """Stop a locked Next dev server only when the lock points at Next itself."""

    if frontend.pid is None:
        return False
    if not _is_pid_alive(frontend.pid):
        try:
            frontend.lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        return True
    if not _looks_like_next_process(frontend.pid):
        return False

    pgid = _get_pgid(frontend.pid)
    try:
        _send_tree_signal(frontend.pid, pgid, signal.SIGTERM)
    except Exception:
        return False

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _is_pid_alive(frontend.pid):
        time.sleep(0.2)

    if _is_pid_alive(frontend.pid):
        try:
            _send_tree_signal(frontend.pid, pgid, KILL_SIGNAL)
        except Exception:
            return False
        time.sleep(0.5)

    try:
        frontend.lock_path.unlink(missing_ok=True)
    except OSError:
        pass
    return not _http_ready(frontend.url, timeout=0.5)


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


def start(home: str | Path | None = None) -> None:
    runtime_home = get_runtime_home(home)
    runtime_home.mkdir(parents=True, exist_ok=True)
    os.environ[DEEPTUTOR_HOME_ENV] = str(runtime_home)
    _reset_runtime_singletons()

    from deeptutor.services.config import (
        ensure_runtime_settings_files,
        export_runtime_settings_to_env,
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
    backend_url = f"http://localhost:{backend_port}"
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
    )
    existing_frontend = _detect_existing_source_frontend(frontend)
    if existing_frontend is not None and not _http_ready(
        existing_frontend.url, timeout=FRONTEND_REUSE_PROBE_TIMEOUT
    ):
        pid = existing_frontend.pid if existing_frontend.pid is not None else "unknown"
        _log(_t("start.restarting_frontend", url=existing_frontend.url, pid=pid))
        if not _stop_unhealthy_source_frontend(existing_frontend):
            raise SystemExit(
                _t("start.frontend_restart_failed", url=existing_frontend.url, pid=pid)
            )
        existing_frontend = None
    if existing_frontend is not None:
        frontend_port = existing_frontend.port

    resolved_backend, resolved_frontend = _resolve_port_conflicts(
        backend_port=backend_port,
        frontend_port=frontend_port,
        check_frontend=existing_frontend is None,
        settings_dir=settings.settings_dir,
    )
    if (resolved_backend, resolved_frontend) != (backend_port, frontend_port):
        backend_port, frontend_port = resolved_backend, resolved_frontend
        runtime_env = export_runtime_settings_to_env(overwrite=True)
        backend_url = f"http://localhost:{backend_port}"
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
        )

    frontend_url = (
        existing_frontend.url
        if existing_frontend is not None
        else f"http://localhost:{frontend_port}"
    )

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
    # The Next.js middleware (web/proxy.ts) runs in the frontend's Node runtime
    # and reads these at request time to forward /api/* and /ws/* to the backend
    # and to gate the login redirect. The browser uses relative paths, so the
    # frontend server reaches the backend on localhost at the resolved port —
    # use backend_url (not api_base, which may be an external browser URL).
    common_env["DEEPTUTOR_API_BASE_URL"] = backend_url
    common_env["DEEPTUTOR_AUTH_ENABLED"] = "true" if auth_enabled else "false"
    common_env["PYTHONUNBUFFERED"] = "1"
    common_env["PYTHONIOENCODING"] = "utf-8:replace"

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

        if existing_frontend is not None:
            pid = existing_frontend.pid if existing_frontend.pid is not None else "unknown"
            _log(_t("start.reusing_frontend", url=frontend_url, pid=pid))
            _wait_for_http(
                name=_t("start.frontend"),
                url=frontend_url,
                process=None,
                timeout=FRONTEND_READY_TIMEOUT,
                should_stop=lambda: shutdown_requested,
            )
        else:
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
