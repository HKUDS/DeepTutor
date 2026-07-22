from __future__ import annotations

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.api.routers import tools as tools_router
from deeptutor.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    COMING_SOON_TOOL_NAMES,
    USER_TOGGLEABLE_TOOL_NAMES,
)


@pytest.mark.asyncio
async def test_list_builtin_tools_marks_toggleable_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The /api/v1/tools response must clearly separate user-toggleable
    tools from locked-on (auto-mounted) tools so the /settings/tools UI
    can render the right control per row."""
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    response = await tools_router.list_builtin_tools()
    by_name = {tool.name: tool for tool in response.tools}

    # Every registered tool + every coming-soon placeholder shows up.
    assert set(by_name) == set(BUILTIN_TOOL_NAMES) | set(COMING_SOON_TOOL_NAMES)

    # Coming-soon entries are NOT toggleable and report enabled=False so
    # the UI can lock the toggle and badge them appropriately.
    for name in COMING_SOON_TOOL_NAMES:
        assert by_name[name].coming_soon is True, name
        assert by_name[name].toggleable is False, name
        assert by_name[name].enabled is False, name

    # Exactly the documented set is toggleable. Pinning the literal here
    # (in addition to the constant) is intentional — this list is the
    # product contract for the /settings/tools "体验增强" section.
    toggleable_names = {name for name, tool in by_name.items() if tool.toggleable}
    assert toggleable_names == set(USER_TOGGLEABLE_TOOL_NAMES)
    assert toggleable_names == {
        "brainstorm",
        "web_search",
        "paper_search",
        "reason",
        "geogebra_analysis",
        "imagegen",
        "videogen",
    }

    # Locked-on (non-toggleable, non-coming-soon) tools always report
    # enabled=True.
    for name, tool in by_name.items():
        if not tool.toggleable and not tool.coming_soon:
            assert tool.enabled is True, name

    # On a fresh settings file the default toggleable set is "all on".
    assert set(response.enabled_optional_tools) == set(USER_TOGGLEABLE_TOOL_NAMES)
    for name in USER_TOGGLEABLE_TOOL_NAMES:
        assert by_name[name].enabled is True


@pytest.mark.asyncio
async def test_list_builtin_tools_marks_capability_owned_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Capability-owned tools (solve_*, mastery_*) report their owning
    capability so the /settings/tools UI groups them below the built-ins;
    plain system built-ins report ``capability=None``."""
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    response = await tools_router.list_builtin_tools()
    by_name = {tool.name: tool for tool in response.tools}

    assert by_name["solve_plan"].capability == "solve"
    assert by_name["mastery_status"].capability == "mastery"
    assert by_name["web_fetch"].capability is None
    # Capability tools stay locked-on (not user-toggleable).
    assert by_name["solve_plan"].toggleable is False
    assert by_name["solve_plan"].enabled is True


@pytest.mark.asyncio
async def test_list_builtin_tools_reflects_user_toggle(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    # User disables a subset of toggleable tools.
    await settings_router.update_enabled_tools(
        settings_router.EnabledToolsUpdate(enabled_tools=["web_search", "reason"])
    )

    response = await tools_router.list_builtin_tools()
    by_name = {tool.name: tool for tool in response.tools}

    assert response.enabled_optional_tools == ["reason", "web_search"]
    assert by_name["web_search"].enabled is True
    assert by_name["reason"].enabled is True
    assert by_name["brainstorm"].enabled is False
    assert by_name["paper_search"].enabled is False
    # Locked-on tools stay on regardless (code_execution is now auto-mounted,
    # gated by sandbox availability rather than a user toggle).
    assert by_name["code_execution"].enabled is True
    assert by_name["rag"].enabled is True
    assert by_name["web_fetch"].enabled is True
