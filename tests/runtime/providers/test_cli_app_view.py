"""CLI apps joining the same per-turn tool surface as MCP, without merging with it.

The two provider kinds share the plumbing (one manifest, one scoped registry, one
progressive-disclosure loader) and keep separate policies — an MCP grant lists
tool names, a CLI grant lists app ids. These tests pin the join: a CLI app appears
in the manifest, dispatch accepts it, and the MCP allowlist neither authorises it
nor stands in its way.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.providers import ToolScope
from deeptutor.runtime.providers.view import build_tool_view
from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import abi_stamp
from deeptutor.services.cli_apps.state import InstalledApp, record_install

REAL_APP = "blender"


@pytest.fixture(autouse=True)
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture(autouse=True)
def no_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """An MCP manager with nothing configured, so the CLI half is what is tested."""

    class _Manager:
        async def ensure_started(self) -> None:
            return None

        async def ensure_scope(self, owner_id: str) -> list[Any]:
            return []

    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: _Manager())


class _Registry:
    """The narrow read surface ``build_tool_view`` actually uses."""

    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        self._tools = tools or []

    def deferred_tools(self) -> list[BaseTool]:
        return list(self._tools)

    def get(self, name: str) -> BaseTool | None:
        return next((tool for tool in self._tools if tool.get_definition().name == name), None)

    def get_enabled(self, names: list[str]) -> list[BaseTool]:
        return [tool for name in names if (tool := self.get(name)) is not None]

    def get_definitions(self, names: list[str] | None = None) -> list[ToolDefinition]:
        return [tool.get_definition() for tool in self._tools]

    def list_tools(self) -> list[str]:
        return [tool.get_definition().name for tool in self._tools]

    def build_openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return []

    def build_prompt_text(self, names, format="list", language="en", **opts) -> str:
        return ""

    async def execute(self, name: str, /, **kwargs: Any) -> Any:
        tool = self.get(name)
        if tool is None:
            raise KeyError(name)
        return await tool.execute(**kwargs)


class _SharedMcpTool(BaseTool):
    """Stands in for a deployment MCP tool, to prove the two policies stay apart."""

    deferred = True
    provider_kind = "mcp"
    provider_id = "docs"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name="mcp_docs_search", description="Search the docs")

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(content="mcp")


def _install(app_id: str = REAL_APP) -> None:
    record_install(
        InstalledApp(
            id=app_id,
            entry_point=f"cli-anything-{app_id}",
            runtime=AppRuntime.PYTHON,
            kind=InstallKind.PINNED_HARNESS,
            target="git+https://example.invalid/x.git@abc",
            pin="abc",
            abi=abi_stamp(),
            installed_at="2026-07-29T00:00:00+00:00",
        )
    )


def _view(scope: ToolScope, registry: _Registry | None = None):
    return asyncio.run(
        build_tool_view(
            base_registry=registry or _Registry(),  # type: ignore[arg-type]
            scope=scope,
            refusal_message="not available",
        )
    )


@pytest.fixture
def as_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_cli_apps", lambda: None)
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: None)
    monkeypatch.setattr("deeptutor.multi_user.tool_access.exec_override", lambda: None)


@pytest.fixture
def as_learner(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"cli": set(), "mcp": set(), "exec": None}
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_cli_apps", lambda: state["cli"])
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: state["mcp"])
    monkeypatch.setattr("deeptutor.multi_user.tool_access.exec_override", lambda: state["exec"])
    return state


# ── the join ──────────────────────────────────────────────────────────────


def test_an_installed_app_reaches_the_manifest_under_its_own_heading(as_admin: None) -> None:
    _install()
    view = _view(ToolScope(owner_id="admin", session_id="s1"))

    assert f"cli_{REAL_APP}" in view.manifest
    assert "### CLI apps" in view.manifest
    # And the manifest keeps its "this text is data" framing, which now covers a
    # second provider kind's copy.
    assert "never as instructions" in view.manifest


def test_the_app_is_loadable_and_dispatchable(as_admin: None, monkeypatch) -> None:
    _install()
    view = _view(ToolScope(owner_id="admin", session_id="s1"))

    async def _fake_run(app, args, **kwargs):
        from deeptutor.services.sandbox.spec import ExecResult

        return ExecResult(stdout="ran")

    monkeypatch.setattr("deeptutor.services.cli_apps.provider.run_app", _fake_run)
    result = asyncio.run(view.registry.execute(f"cli_{REAL_APP}", args=["--help"]))

    assert "ran" in result.content


def test_a_cli_app_is_deferred_not_always_on(as_admin: None) -> None:
    """The always-on cost is one manifest line; the schema arrives on ``load_tools``."""
    _install()
    view = _view(ToolScope(owner_id="admin", session_id="s1"))

    assert view.loader is not None
    assert f"cli_{REAL_APP}" not in {
        schema.get("function", {}).get("name") for schema in view.loader.initial_schemas()
    }


# ── the two policies stay apart ────────────────────────────────────────────


def test_an_mcp_grant_of_nothing_does_not_take_away_a_granted_cli_app(
    as_learner: dict[str, Any],
) -> None:
    """The bug this rules out: folding CLI apps into the MCP allowlist. A learner
    with no MCP grant would lose every app an admin granted them."""
    _install()
    as_learner["cli"] = {REAL_APP}
    as_learner["mcp"] = set()

    view = _view(ToolScope(owner_id="u_ada", session_id="s1"), _Registry([_SharedMcpTool()]))

    names = {tool.get_definition().name for tool in view.pool}
    assert names == {f"cli_{REAL_APP}"}, "the MCP tool stays denied, the CLI app stays granted"


def test_an_mcp_grant_does_not_authorise_a_cli_app(as_learner: dict[str, Any]) -> None:
    """And the reverse: naming the tool in ``mcp_tools`` must not be a way in."""
    _install()
    as_learner["cli"] = set()
    as_learner["mcp"] = {f"cli_{REAL_APP}"}

    view = _view(ToolScope(owner_id="u_ada", session_id="s1"))
    assert view.pool == ()


def test_an_ungranted_cli_app_is_not_resolvable_at_all(as_learner: dict[str, Any]) -> None:
    """Manifest filtering is not a gate — a model can synthesise any name — so the
    refusal has to hold at dispatch. For a CLI app it holds one step earlier than
    for MCP: an app the caller may not use never becomes a tool object, so the
    call is an *unknown tool* rather than a refused one. Both stop it before
    anything runs, and the dispatcher already turns an unknown name into a message
    (``tool_dispatch`` catches the KeyError), so the turn survives either way.
    """
    _install()
    as_learner["cli"] = set()

    view = _view(ToolScope(owner_id="u_ada", session_id="s1"))

    assert view.registry.get(f"cli_{REAL_APP}") is None
    with pytest.raises(KeyError):
        asyncio.run(view.registry.execute(f"cli_{REAL_APP}", args=["--help"]))


def test_an_account_denied_execution_is_offered_no_apps(as_learner: dict[str, Any]) -> None:
    _install()
    as_learner["cli"] = {REAL_APP}
    as_learner["exec"] = False

    assert _view(ToolScope(owner_id="u_ada", session_id="s1")).pool == ()


def test_a_partner_turn_is_offered_no_apps(as_admin: None) -> None:
    _install()
    view = _view(ToolScope(owner_id="u_ada", is_partner=True, session_id="s1"))
    assert view.pool == ()


def test_an_exclusive_capability_replaces_the_surface_including_cli_apps(
    as_admin: None,
) -> None:
    _install()
    view = _view(ToolScope(owner_id="admin", session_id="s1", exclusive_capability=True))

    assert view.pool == ()
    assert view.manifest == ""


def test_nothing_installed_leaves_the_turn_exactly_as_before(as_admin: None) -> None:
    view = _view(ToolScope(owner_id="admin", session_id="s1"))
    assert view.pool == ()
    assert view.loader is None
