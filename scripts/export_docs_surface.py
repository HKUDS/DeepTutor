#!/usr/bin/env python3
"""Export the real CLI and API surface the docs are checked against.

Imports the live application (Typer CLI and FastAPI app) and dumps the
command groups, HTTP paths, and WebSocket paths it actually registers to
``docs/tests/docs_surface.json``. The committed artifact is what the
dependency-free doc contract tests read; this script is what regenerates it.

Run it with the full dependency set installed::

    python scripts/export_docs_surface.py           # regenerate the artifact
    python scripts/export_docs_surface.py --check    # fail on drift (CI)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "tests" / "docs_surface.json"

# Routes the app mounts itself, outside of any module manifest.
SELF_MOUNTED_PREFIXES = (
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/health",
    "/health/live",
    "/health/ready",
)


def _normalize_path(path: str) -> str:
    """Canonical ``/a/b`` form: single slashes, no trailing slash (except root)."""
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "/"
    return "/" + "/".join(segments)


def collect_cli() -> dict:
    """Top-level ``deeptutor <group>`` names and each group's subcommands."""
    import typer.main

    from deeptutor_cli.main import app

    command = typer.main.get_command(app)
    groups = sorted(command.commands)
    subcommands = {}
    for name, entry in command.commands.items():
        inner = getattr(entry, "commands", None)
        if inner:
            subcommands[name] = sorted(inner)
    return {"groups": groups, "subcommands": subcommands}


def _manifest_prefixes() -> dict[str, str]:
    """Map each manifest router reference to the prefix it is mounted under."""
    from deeptutor.modules.catalog import manifests

    prefixes: dict[str, str] = {}
    for module in manifests().values():
        for route in module.get("routes", []):
            options = route.get("options") or {}
            prefix = options.get("prefix", "")
            if isinstance(prefix, str):
                prefixes[route["reference"]] = prefix
    return prefixes


def collect_api() -> tuple[list[str], list[str]]:
    """Every HTTP and WebSocket path the backend mounts, prefixes included.

    HTTP paths come from the public OpenAPI schema: it already resolves include
    prefixes, expands the lazy router loader, and hides only the routes
    deliberately excluded from the schema. WebSocket routes never appear in
    OpenAPI, so they come from the repo's own router loader instead.
    """
    from starlette.routing import WebSocketRoute

    from deeptutor.api.main import _router_loader, app

    paths = {_normalize_path(path) for path in app.openapi()["paths"]}

    prefixes = _manifest_prefixes()
    ws_paths = {
        _normalize_path(prefixes.get(reference, "") + str(route.path))
        for reference, router in _router_loader.records.items()
        for route in router.routes
        if isinstance(route, WebSocketRoute)
    }

    # The schema omits the framework-owned and self-mounted routes below.
    for prefix in SELF_MOUNTED_PREFIXES:
        paths.add(_normalize_path(prefix))

    return sorted(paths), sorted(ws_paths)


def render_surface() -> str:
    from deeptutor.__version__ import __version__

    cli = collect_cli()
    http, ws = collect_api()
    payload = {
        "version": __version__,
        "cli": cli,
        "http": http,
        "ws": ws,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_surface(output: Path, *, check: bool = False) -> bool:
    """Write (or check) the artifact. Returns True when it drifted."""
    rendered = render_surface()
    current = output.read_text(encoding="utf-8") if output.exists() else None
    if current == rendered:
        return False
    if not check:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the artifact drifts")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    drifted = write_surface(args.output, check=args.check)
    if args.check:
        if drifted:
            print(f"docs surface drift: {args.output} does not match the live CLI/API surface.")
            print("Run: python scripts/export_docs_surface.py")
            return 1
        print("docs surface up to date")
        return 0
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
