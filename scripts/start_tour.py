#!/usr/bin/env python
"""DeepTutor Setup Tour — minimal terminal-first guided installer."""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_python() -> str:
    """Return a validated path to the current Python interpreter.

    ``sys.executable`` can be empty or point to a non-existent path on
    some platforms (notably Windows with Python 3.14+).  This helper
    resolves the real path first, then falls back to ``shutil.which``.
    """
    exe = sys.executable
    if exe:
        # Prefer the unresolved path first — resolving symlinks can escape
        # a virtual-env and point at the system Python, which on modern
        # Homebrew / PEP 668 installs will refuse ``pip install``.
        if Path(exe).exists():
            return exe
        resolved = str(Path(exe).resolve())
        if Path(resolved).exists():
            return resolved
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return exe or "python3"


_PYTHON: str = _resolve_python()

# ---------------------------------------------------------------------------
# Bootstrap: ensure minimum packages required to import project modules
# ---------------------------------------------------------------------------

_BOOTSTRAP_PACKAGES = [
    ("yaml", "PyYAML>=6.0"),
]


def _bootstrap() -> None:
    missing = [pip for imp, pip in _BOOTSTRAP_PACKAGES if not _can_import(imp)]
    if not missing:
        return
    print(f"  Installing bootstrap dependencies: {', '.join(missing)} ...")
    subprocess.check_call(
        [_PYTHON, "-m", "pip", "install", *missing, "-q"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


_bootstrap()

# ---------------------------------------------------------------------------


def _load_runtime_deps():
    from _cli_kit import (
        accent,
        banner,
        bold,
        confirm,
        countdown,
        dim,
        log_error,
        log_info,
        log_success,
        log_warn,
        select,
        step,
        text_input,
    )
    from deeptutor.services.config import (
        get_config_test_runner,
        get_env_store,
        get_model_catalog_service,
    )

    return (
        accent,
        banner,
        bold,
        confirm,
        countdown,
        dim,
        log_error,
        log_info,
        log_success,
        log_warn,
        select,
        step,
        text_input,
        get_config_test_runner,
        get_env_store,
        get_model_catalog_service,
    )


(
    accent,
    banner,
    bold,
    confirm,
    countdown,
    dim,
    log_error,
    log_info,
    log_success,
    log_warn,
    select,
    step,
    text_input,
    get_config_test_runner,
    get_env_store,
    get_model_catalog_service,
) = _load_runtime_deps()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROFILE_COMMANDS: dict[str, list[str]] = {
    "cli-core": ["requirements/cli.txt"],
    "cli-rag": ["requirements/cli.txt"],
    "web-basic": ["requirements/server.txt"],
    "web-rag": ["requirements/server.txt"],
}

# Legacy aliases kept for backward compatibility (hidden from UI).
PROFILE_ALIASES: dict[str, str] = {
    "cli-rag-lite": "cli-rag",
    "cli-rag-full": "cli-rag",
    "web-rag-lite": "web-rag",
    "web-rag-full": "web-rag",
}

CACHE_PATH = PROJECT_ROOT / "data" / "user" / "settings" / ".tour_cache.json"
MATH_ANIMATOR_REQUIREMENTS = "requirements/math-animator.txt"

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _save_cache(data: dict[str, Any]) -> None:
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_cache() -> dict[str, Any] | None:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _cleanup_cache() -> None:
    if CACHE_PATH.exists():
        CACHE_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def _python_strategy() -> str:
    if os.environ.get("CONDA_DEFAULT_ENV"):
        return f"conda:{os.environ['CONDA_DEFAULT_ENV']}"
    if os.environ.get("VIRTUAL_ENV"):
        return f"venv:{Path(os.environ['VIRTUAL_ENV']).name}"
    if (PROJECT_ROOT / ".venv").exists():
        return "repo-.venv"
    return "system"


def _node_strategy() -> str:
    if shutil.which("node") and shutil.which("npm"):
        return "installed"
    system = platform.system().lower()
    if system == "darwin":
        return "brew"
    if system == "windows":
        return "winget"
    for pm in ("apt", "dnf", "yum"):
        if shutil.which(pm):
            return pm
    return "manual"


def _node_install_cmd() -> list[str] | None:
    mapping: dict[str, list[str]] = {
        "brew": ["brew", "install", "node"],
        "winget": ["winget", "install", "OpenJS.NodeJS.LTS"],
        "apt": ["sudo", "apt", "install", "-y", "nodejs", "npm"],
        "dnf": ["sudo", "dnf", "install", "-y", "nodejs", "npm"],
        "yum": ["sudo", "yum", "install", "-y", "nodejs", "npm"],
    }
    return mapping.get(_node_strategy())


def _has_cairo_pkgconfig() -> bool:
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        return False
    check = subprocess.run(
        [pkg_config, "--exists", "cairo"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return check.returncode == 0


def _missing_math_animator_system_deps() -> list[str]:
    missing: list[str] = []
    for tool in ("latex", "pkg-config", "cmake", "ffmpeg"):
        if not shutil.which(tool):
            missing.append(tool)
    if not _has_cairo_pkgconfig():
        missing.append("cairo")
    return missing


def _math_animator_install_cmd(dep: str) -> list[str] | None:
    system = platform.system().lower()
    _INSTALL_MAPS: dict[str, dict[str, list[str]]] = {
        "brew": {
            "latex": ["brew", "install", "--cask", "basictex"],
            "pkg-config": ["brew", "install", "pkgconf"],
            "cmake": ["brew", "install", "cmake"],
            "ffmpeg": ["brew", "install", "ffmpeg"],
            "cairo": ["brew", "install", "cairo"],
        },
        "apt": {
            "latex": ["sudo", "apt", "install", "-y", "texlive-latex-base"],
            "pkg-config": ["sudo", "apt", "install", "-y", "pkg-config"],
            "cmake": ["sudo", "apt", "install", "-y", "cmake"],
            "ffmpeg": ["sudo", "apt", "install", "-y", "ffmpeg"],
            "cairo": ["sudo", "apt", "install", "-y", "libcairo2-dev"],
        },
        "dnf": {
            "latex": ["sudo", "dnf", "install", "-y", "texlive-scheme-basic"],
            "pkg-config": ["sudo", "dnf", "install", "-y", "pkgconf"],
            "cmake": ["sudo", "dnf", "install", "-y", "cmake"],
            "ffmpeg": ["sudo", "dnf", "install", "-y", "ffmpeg"],
            "cairo": ["sudo", "dnf", "install", "-y", "cairo-devel"],
        },
        "yum": {
            "latex": ["sudo", "yum", "install", "-y", "texlive-latex"],
            "pkg-config": ["sudo", "yum", "install", "-y", "pkgconfig"],
            "cmake": ["sudo", "yum", "install", "-y", "cmake"],
            "ffmpeg": ["sudo", "yum", "install", "-y", "ffmpeg"],
            "cairo": ["sudo", "yum", "install", "-y", "cairo-devel"],
        },
        "winget": {
            "latex": ["winget", "install", "MiKTeX.MiKTeX"],
            "cmake": ["winget", "install", "Kitware.CMake"],
            "ffmpeg": ["winget", "install", "Gyan.FFmpeg"],
        },
        "choco": {
            "latex": ["choco", "install", "miktex", "-y"],
            "pkg-config": ["choco", "install", "pkgconfiglite", "-y"],
            "cmake": ["choco", "install", "cmake", "-y"],
            "ffmpeg": ["choco", "install", "ffmpeg", "-y"],
            "cairo": ["choco", "install", "gtk-runtime", "-y"],
        },
    }
    if system == "darwin" and shutil.which("brew"):
        return _INSTALL_MAPS["brew"].get(dep)
    if system == "linux":
        for pm in ("apt", "dnf", "yum"):
            if shutil.which(pm):
                return _INSTALL_MAPS[pm].get(dep)
    if system == "windows":
        for pm in ("winget", "choco"):
            if shutil.which(pm):
                return _INSTALL_MAPS[pm].get(dep)
    return None


def _ensure_math_animator_system_deps() -> None:
    missing = _missing_math_animator_system_deps()
    if not missing:
        return

    pretty_names = {
        "latex": "LaTeX executable",
        "pkg-config": "pkg-config",
        "cmake": "CMake",
        "ffmpeg": "FFmpeg",
        "cairo": "Cairo development library",
    }
    details = ", ".join(pretty_names.get(item, item) for item in missing)
    log_warn(f"Math animator system dependencies missing: {details}")

    installable = [dep for dep in missing if _math_animator_install_cmd(dep) is not None]
    if installable and confirm("Install missing system dependencies automatically?", default=True):
        for dep in installable:
            cmd = _math_animator_install_cmd(dep)
            if cmd:
                _run_cmd(cmd, PROJECT_ROOT)

    still_missing = _missing_math_animator_system_deps()
    if still_missing:
        commands = []
        for dep in still_missing:
            cmd = _math_animator_install_cmd(dep)
            commands.append(" ".join(cmd) if cmd else f"install {dep} manually")
        log_warn("Math animator may fail until these are installed: " + " | ".join(commands))


# ---------------------------------------------------------------------------
# Provider detection (providers are now bundled in cli.txt)
# ---------------------------------------------------------------------------

_NATIVE_BINDINGS = frozenset(
    {
        "anthropic",
        "azure_openai",
        "dashscope",
        "perplexity",
        "exa",
        "tavily",
        "serper",
        "jina",
        "baidu",
    }
)


def _needs_providers(catalog: dict[str, Any]) -> bool:
    bindings: list[str] = []
    for svc in ("llm", "embedding"):
        p = get_model_catalog_service().get_active_profile(catalog, svc)
        if p:
            bindings.append(str(p.get("binding") or "").lower())
    sp = get_model_catalog_service().get_active_profile(catalog, "search")
    if sp:
        bindings.append(str(sp.get("provider") or "").lower())
    return bool(_NATIVE_BINDINGS & set(bindings))


# ---------------------------------------------------------------------------
# Dependency installation
# ---------------------------------------------------------------------------


def _get_npm_command() -> str:
    """Return the correct npm command for the current platform.

    With shell=True on Windows, we can just use "npm" and let the shell resolve it.
    """
    if platform.system().lower() == "windows":
        return "npm.cmd"
    else:
        # On Unix-like systems, npm should be found directly
        npm = shutil.which("npm")
        if npm:
            return npm
        return "npm"


def _install_commands(
    profile: str,
    catalog: dict[str, Any],
    *,
    include_math_animator: bool = False,
) -> list[tuple[list[str], Path]]:
    profile = PROFILE_ALIASES.get(profile, profile)
    if profile not in PROFILE_COMMANDS:
        raise ValueError(f"Unknown install profile: {profile}")

    cmds: list[tuple[list[str], Path]] = []
    for req in PROFILE_COMMANDS[profile]:
        cmds.append(([_PYTHON, "-m", "pip", "install", "-r", req], PROJECT_ROOT))
    if include_math_animator:
        cmds.append(
            ([_PYTHON, "-m", "pip", "install", "-r", MATH_ANIMATOR_REQUIREMENTS], PROJECT_ROOT)
        )
    cmds.append(([_PYTHON, "-m", "pip", "install", "-e", ".", "--no-deps"], PROJECT_ROOT))
    if profile.startswith("web"):
        npm_cmd = _get_npm_command()
        cmds.append(([npm_cmd, "install"], PROJECT_ROOT / "web"))
    # Provider SDKs are now bundled in cli.txt, no separate install needed.
    return cmds


def _run_cmd(cmd: list[str], cwd: Path) -> None:
    log_info(f"{dim(str(cwd))}  {' '.join(cmd)}")
    # On Windows, use shell=True to handle .cmd files properly
    use_shell = platform.system().lower() == "windows"
    result = subprocess.run(cmd, cwd=str(cwd), check=False, shell=use_shell)
    if result.returncode != 0:
        # winget may return non-zero even on success (e.g., pending reboot)
        if "winget" in cmd[0]:
            log_warn(f"winget command may have issues (exit {result.returncode}): {' '.join(cmd)}")
        else:
            raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


# ---------------------------------------------------------------------------
# Model catalog helpers
# ---------------------------------------------------------------------------


def _ensure_service(
    catalog: dict[str, Any], svc: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    services = catalog.setdefault("services", {})
    service = services.setdefault(svc, {"active_profile_id": None, "profiles": []})
    profiles = service.setdefault("profiles", [])

    if not profiles:
        pid = f"{svc}-profile-{uuid4().hex[:8]}"
        profile: dict[str, Any] = {
            "id": pid,
            "name": f"Default {svc.title()} Profile",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "models": [],
        }
        if svc == "search":
            profile["provider"] = "perplexity"
        else:
            profile["binding"] = "openai"
            mid = f"{svc}-model-{uuid4().hex[:8]}"
            model: dict[str, Any] = {"id": mid, "name": f"Default {svc.title()} Model", "model": ""}
            if svc == "embedding":
                model["dimension"] = "3072"
            profile["models"] = [model]
            service["active_model_id"] = mid
        profiles.append(profile)
        service["active_profile_id"] = pid

    active_profile = get_model_catalog_service().get_active_profile(catalog, svc)
    if active_profile is None:
        active_profile = profiles[0]
        service["active_profile_id"] = active_profile["id"]

    if svc == "search":
        return active_profile, None

    models = active_profile.setdefault("models", [])
    if not models:
        mid = f"{svc}-model-{uuid4().hex[:8]}"
        m = {"id": mid, "name": f"Default {svc.title()} Model", "model": ""}
        if svc == "embedding":
            m["dimension"] = "3072"
        models.append(m)
        service["active_model_id"] = mid

    active_model = get_model_catalog_service().get_active_model(catalog, svc)
    if active_model is None:
        active_model = models[0]
        service["active_model_id"] = active_model["id"]
    return active_profile, active_model


# ---------------------------------------------------------------------------
# Configure a single service interactively (CLI path only)
# ---------------------------------------------------------------------------


def _configure_service(catalog: dict[str, Any], svc: str) -> None:
    profile, model = _ensure_service(catalog, svc)

    print(f"  {bold(svc.upper())}")
    print()

    profile["name"] = text_input("Profile name", str(profile.get("name") or ""))
    if svc == "search":
        profile["provider"] = text_input("Provider", str(profile.get("provider") or "perplexity"))
    else:
        profile["binding"] = text_input("Binding", str(profile.get("binding") or "openai"))
    profile["base_url"] = text_input("Base URL", str(profile.get("base_url") or ""))
    profile["api_key"] = text_input("API key", str(profile.get("api_key") or ""), secret=True)
    profile["api_version"] = text_input("API version", str(profile.get("api_version") or ""))

    if model is not None:
        model["name"] = text_input("Model label", str(model.get("name") or ""))
        model["model"] = text_input("Model id", str(model.get("model") or ""))
        if svc == "embedding":
            model["dimension"] = text_input("Dimension", str(model.get("dimension") or "3072"))

    print()


# ---------------------------------------------------------------------------
# Live connectivity test (CLI path only)
# ---------------------------------------------------------------------------


def _stream_test(svc: str, catalog: dict[str, Any]) -> bool:
    run = get_config_test_runner().start(svc, catalog)
    seen = 0
    print(f"  {dim(f'Testing {svc.upper()} endpoint ...')}")

    while True:
        events = run.snapshot(seen)
        if events:
            for ev in events:
                kind = ev["type"]
                msg = ev["message"]
                if kind == "info":
                    log_info(dim(msg))
                elif kind == "config":
                    p = ev.get("profile", {})
                    log_info(
                        dim(f"{p.get('name', '')}  {p.get('binding', '')}  {p.get('base_url', '')}")
                    )
                elif kind == "response":
                    snippet = ev.get("snippet", "")
                    d_actual = ev.get("actual_dimension")
                    if snippet:
                        log_success(f"Response received  {dim(snippet[:120])}")
                    elif d_actual is not None:
                        log_success(f"Embedding OK  dim={d_actual}")
                    else:
                        log_success("Response received")
                elif kind == "completed":
                    log_success(msg)
                elif kind == "failed":
                    log_error(msg)
            seen += len(events)
            last = events[-1]["type"]
            if last in ("completed", "failed"):
                return last == "completed"
        time.sleep(0.15)


# ---------------------------------------------------------------------------
# Build final .env dict
# ---------------------------------------------------------------------------


def _build_env(ports: dict[str, int], catalog: dict[str, Any]) -> dict[str, str]:
    rendered = get_env_store().render_from_catalog(catalog)
    rendered["BACKEND_PORT"] = str(ports["backend"])
    rendered["FRONTEND_PORT"] = str(ports["frontend"])
    return rendered


# ---------------------------------------------------------------------------
# Tour banner
# ---------------------------------------------------------------------------


def _tour_banner() -> None:
    banner(
        "DeepTutor Setup Tour",
        [
            "Configure your local DeepTutor environment.",
            "Choose a workflow, set API endpoints, verify connections.",
        ],
    )


# ===================================================================
# Web path — install deps, start temp server, wait for browser config
# ===================================================================


def _stream_text_kwargs() -> dict[str, object]:
    """Best-effort text decoding for background process output."""
    # Some Windows child processes emit locale-specific bytes even when Python
    # runs in UTF-8 mode. Replace undecodable bytes so the background drain
    # thread keeps consuming output instead of crashing.
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": encoding,
        "errors": "replace",
        "bufsize": 1,
    }


def _spawn_process(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    name: str,
) -> subprocess.Popen[str]:
    import threading

    kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": env,
        **_stream_text_kwargs(),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)  # type: ignore[arg-type]

    def _drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            pass  # silently drain; tour terminal stays clean

    threading.Thread(target=_drain, daemon=True).start()
    return proc


def _kill_process(proc: subprocess.Popen[str] | None, name: str) -> None:
    import signal as _sig

    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(_sig.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            os.killpg(os.getpgid(proc.pid), _sig.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def _run_web_tour() -> None:
    total = 4

    # -- Step 1: Profile ---------------------------------------------------
    step(1, total, "Install profile")
    profile = select(
        "Choose a dependency profile",
        [
            ("web-basic", "web-basic", "FastAPI + Next.js"),
            ("web-rag", "web-rag", "+ LlamaIndex RAG"),
        ],
    )
    _save_cache({"step": 1, "mode": "web", "profile": profile, "status": "running"})

    # -- Step 2: Ports -----------------------------------------------------
    step(2, total, "Ports")
    summary = get_env_store().as_summary()
    ports = {
        "backend": summary.backend_port,
        "frontend": summary.frontend_port,
    }
    ports["frontend"] = int(text_input("Frontend port", str(ports["frontend"])))
    ports["backend"] = int(text_input("Backend port", str(ports["backend"])))
    print()
    _save_cache({"step": 2, "mode": "web", "profile": profile, "ports": ports, "status": "running"})

    # -- Step 3: Install dependencies --------------------------------------
    catalog = get_model_catalog_service().load()

    step(3, total, "Install dependencies")
    if confirm("Install dependencies now?", default=True):
        install_math_animator = confirm("Install Math Animator addon (Manim) now?", default=True)
        if not (shutil.which("node") and shutil.which("npm")):
            cmd = _node_install_cmd()
            if cmd:
                if confirm(f"Node.js not found. Install via {cmd[0]}?", default=True):
                    _run_cmd(cmd, PROJECT_ROOT)
            else:
                log_warn("No automatic Node.js installer found for this platform.")
        if install_math_animator:
            _ensure_math_animator_system_deps()

        for cmd, cwd in _install_commands(
            profile,
            catalog,
            include_math_animator=install_math_animator,
        ):
            _run_cmd(cmd, cwd)
        log_success("Dependencies installed.")
    else:
        log_warn("Skipped. You can rerun the tour later.")
    print()

    # -- Step 4: Start temp server & wait for browser config ---------------
    step(4, total, "Configure in browser")

    # Write ports to .env for the temp server
    get_env_store().write(_build_env(ports, catalog))

    # Mark cache as waiting (the backend reads this)
    _save_cache(
        {
            "step": 4,
            "mode": "web",
            "profile": profile,
            "ports": ports,
            "status": "waiting",
        }
    )

    npm = _get_npm_command()
    # Verify npm is actually available and works
    try:
        subprocess.run([npm, "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log_error("npm not found. Cannot start frontend.")
        raise SystemExit(1)

    api_base = f"http://localhost:{ports['backend']}"

    # Write web/.env.local so the frontend picks up the correct backend port
    env_local_path = PROJECT_ROOT / "web" / ".env.local"
    env_local_path.write_text(
        f"# Auto-generated by start_tour.py — do not edit manually\n"
        f"NEXT_PUBLIC_API_BASE={api_base}\n"
    )

    backend_env = os.environ.copy()
    backend_env["PYTHONUNBUFFERED"] = "1"

    frontend_env = os.environ.copy()
    frontend_env["NEXT_PUBLIC_API_BASE"] = api_base

    backend_cmd = [_PYTHON, "-m", "deeptutor.api.run_server"]
    frontend_cmd = [npm, "run", "dev", "--", "--port", str(ports["frontend"])]

    log_info("Starting temporary server ...")
    backend = _spawn_process(backend_cmd, cwd=PROJECT_ROOT, env=backend_env, name="backend")
    time.sleep(2)
    frontend = _spawn_process(
        frontend_cmd, cwd=PROJECT_ROOT / "web", env=frontend_env, name="frontend"
    )
    time.sleep(3)

    settings_url = f"http://localhost:{ports['frontend']}/settings?tour=true"

    banner(
        "Setup Tour",
        [
            f"Open {settings_url}",
            "Configure your endpoints in the browser, then click 'Complete & Launch'.",
            "Waiting for you to finish ...",
        ],
    )

    # Poll the cache file for the "completed" signal from the backend
    try:
        while True:
            if backend.poll() is not None:
                log_error(f"Backend exited unexpectedly (code {backend.returncode}).")
                _kill_process(frontend, "frontend")
                raise SystemExit(1)
            cache = _load_cache()
            if cache and cache.get("status") == "completed":
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log_warn("Interrupted. Stopping temporary server ...")
        _kill_process(frontend, "frontend")
        _kill_process(backend, "backend")
        raise SystemExit(130)

    log_success("Configuration complete!")
    print()

    # Shut down temp server
    log_info("Stopping temporary server ...")
    _kill_process(frontend, "frontend")
    _kill_process(backend, "backend")
    time.sleep(1)

    _cleanup_cache()

    log_info("Restarting DeepTutor with your configuration ...")
    print()
    launch_at = None
    if cache:
        try:
            launch_at = int(cache.get("launch_at")) if cache.get("launch_at") is not None else None
        except (TypeError, ValueError):
            launch_at = None

    remaining = max(1, int((launch_at - time.time()) + 0.999)) if launch_at else 3
    countdown(remaining, "Launching in")
    print()

    os.execvp(_PYTHON, [_PYTHON, str(PROJECT_ROOT / "scripts" / "start_web.py")])


# ===================================================================
# CLI path — full interactive configuration in the terminal
# ===================================================================


def _run_cli_tour() -> None:
    total = 6

    # -- Step 1: Profile ---------------------------------------------------
    step(1, total, "Install profile")
    profile = select(
        "Choose a dependency profile",
        [
            ("cli-core", "cli-core", "Minimal CLI (~80 MB)"),
            ("cli-rag", "cli-rag", "+ LlamaIndex RAG"),
        ],
    )
    _save_cache({"step": 1, "mode": "cli", "profile": profile})

    # -- Step 2: Ports -----------------------------------------------------
    step(2, total, "Ports")
    summary = get_env_store().as_summary()
    ports = {
        "backend": summary.backend_port,
        "frontend": summary.frontend_port,
    }
    ports["backend"] = int(text_input("Backend port", str(ports["backend"])))
    print()
    _save_cache({"step": 2, "mode": "cli", "profile": profile, "ports": ports})

    # -- Step 3: Install dependencies --------------------------------------
    catalog = get_model_catalog_service().load()

    step(3, total, "Install dependencies")
    if confirm("Install dependencies now?", default=True):
        for cmd, cwd in _install_commands(profile, catalog):
            _run_cmd(cmd, cwd)
        log_success("Dependencies installed.")
    else:
        log_warn("Skipped. You can rerun the tour later.")
    print()
    _save_cache({"step": 3, "mode": "cli", "profile": profile, "ports": ports})

    # -- Step 4: Configure providers ---------------------------------------
    step(4, total, "Configure providers")
    _configure_service(catalog, "llm")
    _configure_service(catalog, "embedding")

    search_enabled = False
    if confirm("Configure a search provider?", default=False):
        _configure_service(catalog, "search")
        search_enabled = True

    _save_cache({"step": 4, "mode": "cli", "profile": profile, "ports": ports})

    # -- Step 5: Live diagnostics ------------------------------------------
    step(5, total, "Verify connections")
    llm_ok = _stream_test("llm", catalog)
    print()
    emb_ok = _stream_test("embedding", catalog)
    print()

    if search_enabled:
        _stream_test("search", catalog)
        print()

    if not llm_ok or not emb_ok:
        log_error("LLM and Embedding must both pass before saving.")
        raise SystemExit(1)

    # -- Step 6: Review & apply --------------------------------------------
    step(6, total, "Review & apply")

    llm_p = get_model_catalog_service().get_active_profile(catalog, "llm")
    llm_m = get_model_catalog_service().get_active_model(catalog, "llm")
    emb_p = get_model_catalog_service().get_active_profile(catalog, "embedding")
    emb_m = get_model_catalog_service().get_active_model(catalog, "embedding")
    search_p = get_model_catalog_service().get_active_profile(catalog, "search")

    log_info(f"Profile   {bold(profile)}")
    log_info(f"Backend   {bold(str(ports['backend']))}")
    log_info(
        f"LLM       {bold((llm_p or {}).get('name', '?'))}  {dim((llm_m or {}).get('model', '?'))}"
    )
    log_info(
        f"Embedding {bold((emb_p or {}).get('name', '?'))}  {dim((emb_m or {}).get('model', '?'))}"
    )
    if search_enabled:
        log_info(f"Search    {bold((search_p or {}).get('name', '?'))}")
    else:
        log_info(f"Search    {dim('skipped')}")
    print()

    if not confirm("Write configuration?", default=True):
        log_warn("No files changed.")
        _cleanup_cache()
        raise SystemExit(0)

    get_model_catalog_service().save(catalog)
    get_env_store().write(_build_env(ports, catalog))
    log_success("Saved model_catalog.json and .env")

    _cleanup_cache()

    print()
    log_success("Tour complete. Next commands:")
    print()
    print(f"  {dim('$')} deeptutor chat")
    print(f"  {dim('$')} deeptutor kb list")
    print(f"  {dim('$')} deeptutor serve --port {ports['backend']}")
    print()


# ===================================================================
# Entry
# ===================================================================


def run_tour() -> None:
    _tour_banner()

    log_info(f"Platform  {dim(f'{platform.system()} {platform.release()}')}")
    log_info(f"Python    {dim(_python_strategy())}")
    log_info(f"Node      {dim(_node_strategy())}")
    print()

    cache = _load_cache()
    if cache:
        log_warn("A previous tour session was interrupted.")
        if not confirm("Resume where you left off?", default=True):
            _cleanup_cache()
            cache = None

    step(1, "?", "Choose mode")
    mode = select(
        "How would you like to use DeepTutor?",
        [
            ("web", "web", "Browser UI — configure in Settings page (recommended)"),
            ("cli", "cli", "Terminal only — configure interactively here"),
        ],
    )

    if mode == "web":
        _run_web_tour()
    else:
        _run_cli_tour()


def main() -> None:
    try:
        run_tour()
    except KeyboardInterrupt:
        print()
        log_warn("Tour interrupted.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
