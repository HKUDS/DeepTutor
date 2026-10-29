"""Module boundaries, lifecycle safety and per-turn extension ownership."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys

import pytest

from deeptutor.modules import catalog, lifecycle


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "state_path", lambda: tmp_path / "modules.json")
    monkeypatch.setattr(lifecycle, "state_path", lambda: tmp_path / "modules.json")


def test_dependent_disable_requires_explicit_order():
    assert "reading" in lifecycle.plan("disable", "knowledge")["blocked_by"]
    with pytest.raises(lifecycle.ModuleLifecycleError, match="Required by"):
        lifecycle.change("disable", "knowledge")
    assert not catalog.state_path().exists()


def test_disable_enable_preserves_files_and_assembles_consistently(tmp_path):
    from deeptutor.capabilities.registry import all_loop_capabilities
    from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
    from deeptutor.runtime.request_contracts import CAPABILITY_CONFIG_MODELS

    data = tmp_path / "user-content.json"
    data.write_text('{"preserve": true}')
    lifecycle.change("disable", "solve")
    assert not catalog.module_enabled("solve")
    registry = CapabilityRegistry()
    registry.load_builtins()
    assert "deep_solve" not in {row["name"] for row in registry.get_manifests()}
    assert "deep_solve" not in CAPABILITY_CONFIG_MODELS
    assert "solve" not in {extension.name for extension in all_loop_capabilities()}
    lifecycle.change("enable", "solve")
    assert catalog.module_enabled("solve")
    assert json.loads(data.read_text()) == {"preserve": True}


def test_environment_cannot_change_while_runtime_holds_lease():
    with lifecycle.environment_lease():
        with pytest.raises(lifecycle.ModuleLifecycleError, match="in use"):
            lifecycle.change("disable", "solve")
    lifecycle.change("disable", "solve")


def test_environment_lock_crosses_process_boundaries():
    command = [
        sys.executable,
        "-c",
        "from deeptutor.modules.lifecycle import environment_lease; "
        "lease=environment_lease(exclusive=True); lease.__enter__()",
    ]
    with lifecycle.environment_lease():
        result = subprocess.run(command, text=True, capture_output=True)
        assert result.returncode != 0
        assert "Environment is in use" in result.stderr
    assert subprocess.run(command, capture_output=True).returncode == 0


def test_invalid_state_is_preserved_and_fails_closed():
    catalog.state_path().write_text('{"schema_version":1,"enabled":{"solve":"yes"}}')
    with pytest.raises(ValueError, match="Invalid module selection"):
        lifecycle.change("enable", "solve")
    assert '"yes"' in catalog.state_path().read_text()


def test_core_cannot_be_removed():
    for action in ("disable", "uninstall"):
        with pytest.raises(lifecycle.ModuleLifecycleError, match="core module"):
            lifecycle.plan(action, "core")


def test_core_does_not_offer_tools_owned_by_missing_features(monkeypatch):
    from deeptutor.runtime.registry.tool_registry import ToolRegistry

    monkeypatch.setattr(catalog, "installed", lambda name: name == "core")
    registry = ToolRegistry()
    registry.load_builtins()
    for name in ("paper_search", "partner_read", "partner_memorize", "partner_search"):
        assert registry.get(name) is None
    assert registry.get("web_search") is not None
    assert "memory" in catalog.dependency_order(["partners"])


def test_source_install_has_no_pip_side_effect(monkeypatch):
    monkeypatch.setattr(lifecycle, "_pip", lambda argv: pytest.fail("pip was invoked"))
    with pytest.raises(lifecycle.ModuleLifecycleError, match="source checkout"):
        lifecycle.change("install", "solve")


def test_per_turn_factory_once_and_state_isolation(monkeypatch):
    from deeptutor.capabilities import registry
    from deeptutor.core.context import UnifiedContext

    calls = []

    @dataclass
    class Extension:
        name: str = "test_extension"
        owned_tools: tuple = ()

        def is_active(self, context):
            return context.user_message == "activate"

    def factory():
        calls.append(1)
        return Extension()

    monkeypatch.setattr(registry, "BUILTIN_LOOP_CAPABILITY_SPECS", ())
    monkeypatch.setattr(
        registry, "discover_external_loop_capabilities", lambda: (("test_extension", factory),)
    )
    first = UnifiedContext(user_message="idle")
    assert not registry.active_loop_capabilities(first)
    first.user_message = "activate"
    active = registry.active_loop_capabilities(first)[0]
    assert registry.active_loop_capabilities(first)[0] is active
    second = UnifiedContext(user_message="activate")
    assert registry.active_loop_capabilities(second)[0] is not active
    assert len(calls) == 2


def test_manifest_dependency_order_and_path_ownership():
    from build_support import owner

    rows = catalog.manifests()
    for name, row in rows.items():
        order = catalog.dependency_order([name])
        assert order[-1] == name
        for prefix in row["paths"]:
            assert owner(prefix) == catalog.module_for_path(prefix) == name
        for kind in ("capabilities", "loops"):
            for spec in row[kind].values():
                relative = spec["class_path"].split(":")[0].replace(".", "/") + ".py"
                assert catalog.module_for_path(relative) == name


def test_service_callbacks_remain_paired_for_partial_startup():
    from deeptutor.modules.services import module_service_callbacks

    starts = module_service_callbacks("start", None)
    stops = module_service_callbacks("stop", None)
    assert len(starts) == len(stops)
    for start, stop in zip(starts, stops):
        assert start.args[0].replace(":start_", ":stop_") == stop.args[0]


@pytest.mark.parametrize("failure_stage", ["install", "selection"])
def test_failed_install_rolls_back_new_packages_without_touching_selection(
    monkeypatch, failure_stage
):
    from types import SimpleNamespace

    from deeptutor.__version__ import __version__

    monkeypatch.setattr(lifecycle, "source_checkout", lambda: False)
    packages = [SimpleNamespace(metadata={"Name": "deeptutor"}, version=__version__)]
    monkeypatch.setattr(lifecycle.metadata, "distributions", lambda: list(packages))
    calls = []

    def pip(argv):
        calls.append(argv)
        if "--report" in argv:
            Path(argv[argv.index("--report") + 1]).write_text(
                json.dumps(
                    {
                        "install": [
                            {
                                "metadata": {"name": "deeptutor-solve", "version": __version__},
                                "download_info": {"url": "file:///fixture.whl"},
                            }
                        ]
                    }
                )
            )
        elif "wheel" in argv:
            (Path(argv[argv.index("--wheel-dir") + 1]) / "fixture.whl").touch()
        elif "install" in argv:
            packages.append(
                SimpleNamespace(metadata={"Name": "deeptutor-solve"}, version=__version__)
            )
            if failure_stage == "install":
                raise lifecycle.ModuleLifecycleError("fixture install failed")
        elif "uninstall" in argv:
            assert argv[-1] == "deeptutor-solve"
            packages.pop()
        return ""

    monkeypatch.setattr(lifecycle, "_pip", pip)
    if failure_stage == "selection":

        def reject_selection(_enabled):
            raise lifecycle.ModuleLifecycleError("fixture selection failed")

        monkeypatch.setattr(lifecycle, "_save_selection", reject_selection)
    with pytest.raises(lifecycle.ModuleLifecycleError, match=f"fixture {failure_stage} failed"):
        lifecycle.change("install", "solve")
    assert len(packages) == 1
    assert not catalog.state_path().exists()
    assert "uninstall" in calls[-1]


@pytest.mark.parametrize("action", ["install", "uninstall"])
def test_invalid_state_never_modifies_packages(action, monkeypatch):
    catalog.state_path().write_text('{"schema_version":1,"enabled":{"solve":"invalid"}}')
    monkeypatch.setattr(lifecycle, "source_checkout", lambda: False)
    monkeypatch.setattr(lifecycle, "_pip", lambda _argv: pytest.fail("pip mutated invalid state"))
    with pytest.raises(ValueError, match="Invalid module selection"):
        lifecycle.change(action, "solve")


def test_shared_home_is_locked_across_python_environments(tmp_path, monkeypatch):
    with lifecycle.environment_lease():
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "different-environment"))
        with pytest.raises(lifecycle.ModuleLifecycleError, match="in use"):
            with lifecycle.environment_lease(exclusive=True):
                pytest.fail("Another interpreter changed a live deployment")


def test_enable_rejects_version_mismatch(monkeypatch):
    monkeypatch.setattr(lifecycle, "source_checkout", lambda: False)
    monkeypatch.setattr(lifecycle, "installed", lambda _name: True)
    monkeypatch.setattr(lifecycle.metadata, "version", lambda _name: "0.0.0")
    with pytest.raises(lifecycle.ModuleLifecycleError, match="must match core"):
        lifecycle.change("enable", "solve")
    assert not catalog.state_path().exists()


def test_optional_tool_requires_both_owners(monkeypatch):
    present = {"core", "research"}
    monkeypatch.setattr(catalog, "installed", lambda name: name in present)
    assert not catalog.contribution_enabled("tools", "knowledge_frontier")
    present.update(catalog.dependency_order(["knowledge"]))
    assert catalog.contribution_enabled("tools", "knowledge_frontier")
    present.remove("research")
    assert not catalog.contribution_enabled("tools", "knowledge_frontier")


def test_uninstall_checks_external_distribution_dependents(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(lifecycle, "source_checkout", lambda: False)
    monkeypatch.setattr(lifecycle, "dependents", lambda *a, **kw: [])
    monkeypatch.setattr(
        lifecycle.metadata,
        "distributions",
        lambda: [
            SimpleNamespace(
                metadata={"Name": "third-party-tutor"}, requires=["deeptutor-solve>=1.0"]
            )
        ],
    )
    assert lifecycle.plan("uninstall", "solve")["blocked_by"] == ["third-party-tutor"]
