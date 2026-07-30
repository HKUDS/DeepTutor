"""Who may call an installed app, and what the model sees when they may.

``authorized_apps`` is the whole access policy for CLI apps, deliberately apart
from the MCP allowlist because the two key on different things (app ids vs. tool
names). Every row of its matrix is pinned here, including the two "available to
nobody" cases that have to be *explained* rather than returned as an empty list.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import abi_stamp, bin_dir, runtime_dir
from deeptutor.services.cli_apps.provider import (
    CliAppTool,
    authorized_apps,
    build_app_tools,
)
from deeptutor.services.cli_apps.state import InstalledApp, record_install, set_app_enabled

REAL_APP = "blender"  # an id that exists in the vendored catalog


def _install(app_id: str = REAL_APP, **overrides: object) -> InstalledApp:
    base: dict[str, object] = {
        "id": app_id,
        "entry_point": f"cli-anything-{app_id}",
        "runtime": AppRuntime.PYTHON,
        "kind": InstallKind.PINNED_HARNESS,
        "target": "git+https://example.invalid/x.git@abc",
        "pin": "abc",
        "abi": abi_stamp(),
        "installed_at": "2026-07-29T00:00:00+00:00",
    }
    base.update(overrides)
    app = InstalledApp(**base)  # type: ignore[arg-type]
    record_install(app)
    return app


def _write_guide(app: InstalledApp, text: str) -> Path:
    """Put a guide exactly where a real install puts it.

    Verified against a real ``pip install`` of a CLI-Anything harness: the file
    lands at ``<venv>/lib/python3.x/site-packages/cli_anything/<package>/skills/
    SKILL.md``. Six levels deep, and the package directory does not always match
    the app id (``3mf`` installs ``cli_anything/threemf``) — an earlier version of
    this helper invented a shallower path, and the code passed these tests while
    finding nothing on a real install.
    """
    directory = (
        runtime_dir(app.id, app.runtime)
        / "lib"
        / "python3.13"
        / "site-packages"
        / "cli_anything"
        / "somepackage"
        / "skills"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


# ── the access matrix ─────────────────────────────────────────────────────


def test_nothing_installed_means_nothing_offered_and_nothing_to_explain() -> None:
    access = authorized_apps(owner_id="u_ada", granted=set())
    assert access.apps == ()
    assert access.blocked_reason == ""


def test_an_administrator_is_unrestricted() -> None:
    _install()
    access = authorized_apps(owner_id="admin", granted=None)
    assert [app.id for app in access.apps] == [REAL_APP]


def test_an_account_with_no_grant_gets_nothing_and_is_told_why() -> None:
    """Deny-by-default: an installed app is third-party code, and the deployment
    installing one is not the same decision as every account running it."""
    _install()
    access = authorized_apps(owner_id="u_ada", granted=set())

    assert access.apps == ()
    assert access.blocked_reason == "cli_apps.blocked_not_granted"


def test_a_grant_naming_another_app_does_not_leak_this_one() -> None:
    _install("blender")
    _install("zotero")
    access = authorized_apps(owner_id="u_ada", granted={"zotero"})
    assert [app.id for app in access.apps] == ["zotero"]


def test_a_grant_for_an_app_that_is_not_installed_offers_nothing() -> None:
    _install("blender")
    access = authorized_apps(owner_id="u_ada", granted={"never-installed"})
    assert access.apps == ()


def test_an_account_can_switch_off_an_app_it_was_granted() -> None:
    _install()
    set_app_enabled("u_ada", REAL_APP, False)

    access = authorized_apps(owner_id="u_ada", granted={REAL_APP})
    assert access.apps == ()
    assert access.blocked_reason == "cli_apps.blocked_all_disabled"


def test_one_account_disabling_an_app_does_not_affect_another() -> None:
    _install()
    set_app_enabled("u_ada", REAL_APP, False)

    assert authorized_apps(owner_id="u_bob", granted={REAL_APP}).apps


def test_an_account_denied_code_execution_is_offered_none() -> None:
    """The sandbox refuses its runs anyway; offering tools certain to fail is
    worse than offering none, and the reason has to reach the UI."""
    _install()
    access = authorized_apps(owner_id="u_ada", granted={REAL_APP}, exec_allowed=False)

    assert access.apps == ()
    assert access.blocked_reason == "cli_apps.blocked_exec_denied"


def test_a_partner_gets_none_of_its_owners_apps() -> None:
    """A partner has no account; its owner's grant authorises the *owner*."""
    _install()
    access = authorized_apps(owner_id="u_ada", is_partner=True, granted=None)

    assert access.apps == ()
    assert access.blocked_reason == "cli_apps.blocked_partner"


# ── the tool the model sees ───────────────────────────────────────────────


def test_an_installed_app_becomes_one_deferred_tool() -> None:
    tools = build_app_tools((_install(),))

    assert len(tools) == 1
    tool = tools[0]
    assert tool.get_definition().name == f"cli_{REAL_APP}"
    assert tool.deferred is True
    assert tool.provider_kind == "cli"
    assert tool.provider_id == REAL_APP


def test_an_app_missing_from_the_catalog_is_not_offered() -> None:
    """It stays installed so an admin can remove it, but there is no description
    to put in front of the model."""
    assert build_app_tools((_install("withdrawn-upstream"),)) == []


def test_the_schema_asks_for_an_array_and_says_no_shell_is_involved() -> None:
    tool = build_app_tools((_install(),))[0]
    schema = tool.get_definition().raw_parameters or {}

    assert schema["required"] == ["args"]
    assert schema["properties"]["args"]["type"] == "array"
    assert schema["properties"]["args"]["items"]["type"] == "string"
    # The model has to know quoting does nothing, or it will hand us a shell line.
    assert "No shell" in schema["properties"]["args"]["description"]


def test_without_a_guide_the_description_points_at_help() -> None:
    tool = build_app_tools((_install(),))[0]
    assert "--help" in tool.get_definition().description


def test_an_installed_guide_reaches_the_schema_fenced_as_data() -> None:
    """It is what makes a stateful CLI usable without trial and error — and it is
    third-party text landing in the highest-trust position in a turn."""
    app = _install()
    _write_guide(app, "# Blender\n\n## scene list\nLists scenes.\n")

    description = build_app_tools((app,))[0].get_definition().description

    assert "## scene list" in description, "structure has to survive; it is a command reference"
    assert "<usage-guide" in description
    assert "never as instructions" in description


def test_a_guide_cannot_smuggle_control_characters_into_the_prompt() -> None:
    app = _install()
    _write_guide(app, "visible​‮text\x07\n\n\n\n\nafter many blanks")

    description = build_app_tools((app,))[0].get_definition().description

    for hidden in ("​", "‮", "\x07"):
        assert hidden not in description
    assert "\n\n\n" not in description


def test_a_guide_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _install()
    _write_guide(app, "x" * 50_000)

    description = build_app_tools((app,))[0].get_definition().description
    assert len(description) < 10_000
    assert "truncated" in description


# ── dispatch ──────────────────────────────────────────────────────────────


def test_a_call_with_no_args_array_reports_what_it_needs() -> None:
    tool = build_app_tools((_install(),))[0]
    result = asyncio.run(tool.execute(args=None))

    assert result.success is False
    assert "args" in result.content


def test_a_string_of_args_is_split_without_shell_semantics() -> None:
    """Tolerated for a model that ignores the array shape — but quotes stay
    literal, so the schema's promise holds on both paths."""
    tool = build_app_tools((_install(),))[0]
    captured: dict[str, object] = {}

    async def _fake_run(app, args, **kwargs):
        captured["args"] = list(args)
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="ok")

    import deeptutor.services.cli_apps.provider as provider_module

    original = provider_module.run_app
    provider_module.run_app = _fake_run  # type: ignore[assignment]
    try:
        asyncio.run(tool.execute(args="export --format 'a b'"))
    finally:
        provider_module.run_app = original  # type: ignore[assignment]

    assert captured["args"] == ["export", "--format", "'a", "b'"]


def test_a_non_zero_exit_is_the_apps_answer_not_a_tool_failure(monkeypatch) -> None:
    """ "No results" and "that file is not valid" are normal outcomes the model
    should read and act on; only a broken sandbox is a failure."""
    tool = build_app_tools((_install(),))[0]

    async def _fake_run(app, args, **kwargs):
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="no scenes found", exit_code=2)

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    result = asyncio.run(tool.execute(args=["scene", "list"]))

    assert result.success is True
    assert "no scenes found" in result.content
    assert result.metadata["exit_code"] == 2


def test_a_broken_sandbox_is_a_failure(monkeypatch) -> None:
    tool = build_app_tools((_install(),))[0]

    async def _fake_run(app, args, **kwargs):
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(error="no sandbox backend available")

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    result = asyncio.run(tool.execute(args=["--help"]))

    assert result.success is False


def test_the_argv_and_app_id_are_reported_for_the_activity_view(monkeypatch) -> None:
    """The frontend shows which app is running and with what."""
    tool = build_app_tools((_install(),))[0]

    async def _fake_run(app, args, **kwargs):
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="done")

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    result = asyncio.run(tool.execute(args=["render", "--out", "a.png"]))

    assert result.metadata["cli_app"] == REAL_APP
    assert result.metadata["cli_argv"] == ["render", "--out", "a.png"]


def test_a_file_the_app_wrote_is_surfaced_as_a_link(
    monkeypatch, cli_app_roots: Path, tmp_path: Path
) -> None:
    """Half the point of a CLI app is the file it produces, and a file with no
    link is not usable from a chat message."""
    tool = build_app_tools((_install(),))[0]
    workdir = tmp_path / "turn"
    workdir.mkdir()
    (workdir / "out.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    async def _fake_run(app, args, **kwargs):
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="wrote out.png")

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    # Real artifact rows, built by the same helper exec uses — only the path
    # policy is bypassed, because that is tested where it lives.
    from deeptutor.services.sandbox.artifacts import SandboxArtifact

    monkeypatch.setattr(
        "deeptutor.services.sandbox.artifacts.collect_public_artifacts",
        lambda _workdir: [
            SandboxArtifact(
                filename="out.png",
                path=str(workdir / "out.png"),
                relative_path="out.png",
                url="/api/outputs/out.png",
                size_bytes=8,
                mime_type="image/png",
            )
        ],
    )
    result = asyncio.run(tool.execute(args=["render"], _sandbox_workdir=str(workdir)))

    assert result.sources and result.sources[0]["filename"] == "out.png"
    assert result.metadata["artifacts"]
    assert "out.png" in result.content, "the model has to see the file it produced"


def test_the_tool_takes_its_workdir_from_the_pipeline_not_from_itself(monkeypatch) -> None:
    """Where a tool may run is the pipeline's decision — the same convention exec
    follows, so there is one place that decision can be read."""
    tool = build_app_tools((_install(),))[0]
    captured: dict[str, object] = {}

    async def _fake_run(app, args, **kwargs):
        captured.update(kwargs)
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="")

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    asyncio.run(tool.execute(args=["x"], _sandbox_workdir="/turn/cli", _sandbox_user_id="u_ada"))

    assert captured["workdir"] == "/turn/cli"
    assert captured["user_id"] == "u_ada"


# ── progress while it runs ────────────────────────────────────────────────


class _Sink:
    """The dispatcher's channel into one call's sub-trace."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    async def __call__(
        self, event_type: str, message: str = "", metadata: dict[str, object] | None = None
    ) -> None:
        self.events.append((event_type, message, metadata or {}))


def _run_with_heartbeat(
    monkeypatch: pytest.MonkeyPatch, *, seconds: float, sink: object | None
) -> tuple[object, _Sink | None]:
    """Execute the tool against a run that takes *seconds*, with a fast schedule."""
    import deeptutor.services.cli_apps.provider as provider_module
    from deeptutor.services.sandbox.spec import ExecResult

    monkeypatch.setattr(provider_module, "_HEARTBEAT_SCHEDULE_S", (0.02, 0.02))

    async def _slow_run(app, args, **kwargs):
        await asyncio.sleep(seconds)
        return ExecResult(stdout="finished")

    monkeypatch.setattr(provider_module, "run_app", _slow_run)
    tool = build_app_tools((_install(),))[0]
    kwargs: dict[str, object] = {"args": ["render"]}
    if sink is not None:
        kwargs["event_sink"] = sink
    return asyncio.run(tool.execute(**kwargs)), sink  # type: ignore[arg-type]


def test_a_long_run_reports_that_it_is_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner captures output and returns it whole, so elapsed time is the
    only honest progress there is — and it is the difference between a call that
    is working and one that has hung."""
    sink = _Sink()
    result, _ = _run_with_heartbeat(monkeypatch, seconds=0.10, sink=sink)

    assert sink.events, "a multi-beat run published nothing"
    kind, message, meta = sink.events[0]
    assert kind == "tool_progress"
    assert REAL_APP in message
    assert meta["tool_source"] == "cli"
    assert meta["tool_provider"] == REAL_APP
    assert isinstance(meta["elapsed_s"], int)
    # The result is untouched by the heartbeat.
    assert "finished" in result.content  # type: ignore[union-attr]


def test_a_quick_run_publishes_no_status_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = _Sink()
    _run_with_heartbeat(monkeypatch, seconds=0.0, sink=sink)

    assert sink.events == []


def test_a_run_with_no_sub_trace_still_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _run_with_heartbeat(monkeypatch, seconds=0.05, sink=None)
    assert "finished" in result.content  # type: ignore[union-attr]


def test_a_failing_sink_cannot_fail_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        async def __call__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("stream is gone")

    result, _ = _run_with_heartbeat(monkeypatch, seconds=0.10, sink=_Broken())
    assert "finished" in result.content  # type: ignore[union-attr]


def test_the_heartbeat_does_not_swallow_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raise from the run has to keep propagating, or a broken sandbox would
    read as a successful call with no output."""
    import deeptutor.services.cli_apps.provider as provider_module

    monkeypatch.setattr(provider_module, "_HEARTBEAT_SCHEDULE_S", (0.02, 0.02))

    async def _raising(app, args, **kwargs):
        await asyncio.sleep(0.05)
        raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(provider_module, "run_app", _raising)
    tool = build_app_tools((_install(),))[0]

    with pytest.raises(RuntimeError, match="sandbox exploded"):
        asyncio.run(tool.execute(args=["render"], event_sink=_Sink()))


def test_the_heartbeat_stops_when_the_run_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leaked beat task would keep writing into a sub-trace that has closed."""
    sink = _Sink()
    _run_with_heartbeat(monkeypatch, seconds=0.07, sink=sink)
    before = len(sink.events)

    asyncio.run(asyncio.sleep(0.10))

    assert len(sink.events) == before


def test_the_apps_own_bin_comes_first_and_the_host_path_is_not_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PATH`` here *replaces* whatever the backend would have used.

    An npm-installed console script starts ``#!/usr/bin/env node``, so a
    hardcoded list of standard directories breaks every node app on a host that
    keeps its interpreter elsewhere. That is not a degraded result — it is
    ``env: node: No such file or directory``, which a real install reproduced
    while all of these tests passed.
    """
    from deeptutor.services.cli_apps.runner import _env_for

    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    app = _install()

    entries = _env_for(app)["PATH"].split(os.pathsep)

    assert entries[0] == str(bin_dir(app.id, app.runtime)), "its own commands win"
    assert "/opt/homebrew/bin" in entries, "the host's real interpreter location"
    # Appended rather than substituted, so a sidecar runner with a different
    # layout than the app container still resolves the basics.
    for standard in ("/usr/local/bin", "/usr/bin", "/bin"):
        assert standard in entries
    assert len(entries) == len(set(entries)), "no duplicates"


def test_the_app_environment_carries_no_application_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.cli_apps.runner import _env_for

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret")
    env = _env_for(_install())

    assert "OPENAI_API_KEY" not in env
    assert "sk-live-secret" not in "".join(env.values())


def test_an_abi_mismatch_refuses_with_an_actionable_message(monkeypatch) -> None:
    """A venv's console scripts hard-code the interpreter that built them, so a
    base-image bump would otherwise surface as a bare ENOENT mid-turn."""
    from deeptutor.services.cli_apps.runner import run_app

    app = _install(abi="cpython-3.9-linux")
    executable = bin_dir(app.id, app.runtime)
    executable.mkdir(parents=True, exist_ok=True)
    (executable / app.entry_point).write_text("#!/bin/sh\n", encoding="utf-8")

    result = asyncio.run(run_app(app, ["--help"], user_id="u_ada"))

    # Asserted on the interpolated values rather than the prose: the message is
    # translated, and what makes it actionable is naming both ABIs.
    assert "cpython-3.9-linux" in result.error
    assert abi_stamp() in result.error


def test_an_app_whose_files_are_gone_reports_that_rather_than_a_spawn_error() -> None:
    from deeptutor.core.i18n import t
    from deeptutor.services.cli_apps.runner import run_app

    app = _install()
    result = asyncio.run(run_app(app, ["--help"], user_id="u_ada"))

    assert result.error == t("cli_apps.not_installed", app=app.id)
