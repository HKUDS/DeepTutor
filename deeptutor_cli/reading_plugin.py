"""Install and manage the independently distributed reading extensions."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(help="Manage reading extensions. Restart the backend after changes.")


def _call(function, *args, **kwargs):
    try:
        result = function(*args, **kwargs)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("list")
def list_plugins():
    from deeptutor.reading.plugin_manager import status

    _call(status)


@app.command("install")
def install(wheel: Path = typer.Argument(..., exists=True, dir_okay=False)):
    from deeptutor.reading.plugin_manager import MAX_BYTES, install

    if wheel.stat().st_size > MAX_BYTES:
        raise typer.BadParameter("Wheel exceeds 10 MB.")
    _call(install, wheel.read_bytes())
    typer.echo("Restart the DeepTutor backend to apply the change.")


@app.command("update")
def update():
    """Download and install the latest published reading bundle."""
    from deeptutor.reading.plugin_manager import download_latest

    _call(download_latest)
    typer.echo("Restart the DeepTutor backend to apply the change.")


@app.command("uninstall")
def uninstall():
    from deeptutor.reading.plugin_manager import configure

    _call(configure, mode="disabled")
    typer.echo("Restart the DeepTutor backend to apply the change.")


@app.command("restore")
def restore():
    from deeptutor.reading.plugin_manager import configure

    _call(configure, mode="builtin")
    typer.echo("Restart the DeepTutor backend to apply the change.")


@app.command("enable")
def enable(extension: str):
    from deeptutor.reading.plugin_manager import configure

    _call(configure, extension=extension, enabled=True)
    typer.echo("Restart the DeepTutor backend to apply the change.")


@app.command("disable")
def disable(extension: str):
    from deeptutor.reading.plugin_manager import configure

    _call(configure, extension=extension, enabled=False)
    typer.echo("Restart the DeepTutor backend to apply the change.")
