"""CLI completion releases the runtime before closing its event loop."""

import asyncio

import pytest
from typer.testing import CliRunner

from deeptutor.app import container as containers
from deeptutor.modules.lifecycle import environment_lease
from deeptutor_cli.common import maybe_run
from deeptutor_cli.main import app


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_cli_releases_runtime_lease_on_every_exit(outcome):
    container = containers.get_application_container()

    async def command():
        await container.start()
        if outcome == "error":
            raise ValueError("command failed")
        if outcome == "cancel":
            raise asyncio.CancelledError
        return "done"

    if outcome == "success":
        assert maybe_run(command()) == "done"
    else:
        error = ValueError if outcome == "error" else asyncio.CancelledError
        with pytest.raises(error):
            maybe_run(command())
    assert not container._started
    assert container._module_lease is None
    assert containers._default_container is None
    with environment_lease(exclusive=True):
        pass


def test_invalid_cli_capability_does_not_block_module_changes():
    result = CliRunner().invoke(app, ["run", "auto", "hello"])
    assert isinstance(result.exception, ValueError)
    # Retain the traceback (and its container references): no GC is needed.
    assert "Unknown capability" in str(result.exception)
    with environment_lease(exclusive=True):
        pass


def test_cleanup_does_not_construct_an_unused_container(monkeypatch):
    monkeypatch.setattr(
        containers.ApplicationContainer,
        "build",
        lambda: pytest.fail("Cleanup constructed a runtime"),
    )

    async def command():
        return 42

    assert maybe_run(command()) == 42
