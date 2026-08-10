#!/usr/bin/env python
"""
Uvicorn Server Startup Script
Uses Python API instead of command line to avoid Windows path parsing issues.
"""

import asyncio
import os
from pathlib import Path
import sys

from deeptutor.runtime.home import get_runtime_home

# Windows: uvicorn defaults to SelectorEventLoop which does not support
# asyncio.create_subprocess_exec.  Switch to ProactorEventLoop so that
# child-process APIs (used by Math Animator renderer, etc.) work correctly.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

# Force unbuffered output
os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")


def main() -> None:
    # Runtime workspace root owns data/user/settings and generated outputs.
    project_root = get_runtime_home()
    os.chdir(str(project_root))

    # Get port from configuration
    from deeptutor.logging import configure_logging
    from deeptutor.runtime.mode import RunMode, set_mode
    from deeptutor.services.config import HTTP_KEEP_ALIVE_TIMEOUT, get_ws_max_size
    from deeptutor.services.setup import get_backend_port

    set_mode(RunMode.SERVER)
    configure_logging()
    backend_port = get_backend_port(project_root)

    # Configure reload_excludes to skip directories that shouldn't trigger reloads
    # Use absolute paths to ensure they're properly resolved
    reload_excludes = [
        str(project_root / "venv"),  # Virtual environment
        str(project_root / ".venv"),  # Virtual environment (alternative name)
        str(project_root / "data"),  # Data directory (includes knowledge_bases, user data, logs)
        str(project_root / "node_modules"),  # Node modules (if any at root)
        str(project_root / "web" / "node_modules"),  # Web node modules
        str(project_root / "web" / ".next"),  # Next.js build
        str(project_root / ".git"),  # Git directory
        str(project_root / "scripts"),  # Scripts directory - don't reload on launcher changes
    ]

    # Filter out non-existent directories to avoid warnings
    reload_excludes = [d for d in reload_excludes if Path(d).exists()]

    # Reload launches a supervisor plus a worker and retains file-watcher state,
    # so keep it opt-in for local development. ws_max_size tracks the configured
    # chat-attachment total so base64 uploads fit in one WS frame.
    dev_reload = os.environ.get("DEEPTUTOR_DEV_RELOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    uvicorn.run(
        "deeptutor.api.main:app",
        host="0.0.0.0",
        port=backend_port,
        reload=dev_reload,
        reload_excludes=reload_excludes if dev_reload else None,
        log_level="info",
        access_log=False,
        ws_max_size=get_ws_max_size(),
        timeout_keep_alive=HTTP_KEEP_ALIVE_TIMEOUT,
    )


if __name__ == "__main__":
    main()
