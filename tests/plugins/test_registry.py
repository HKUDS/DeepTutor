"""Registry tests use metadata-only fake distributions and never import plugins."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from deeptutor.plugins.manifest import permission_digest
from deeptutor.plugins.registry import PluginRegistry


def _manifest(plugin_id: str = "org.author.example", deeptutor: str = ">=1.6.0,<2") -> dict:
    return {
        "schema_version": "deeptutor.plugin/v1",
        "id": plugin_id,
        "name": "Example Plugin",
        "version": "1.0.0",
        "description_i18n": {"en": "Example extension package"},
        "author": "Author Name",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://github.com/author/example",
        "compatibility": {"deeptutor": deeptutor, "api": {"tool": "1"}},
        "permissions": {"network": ["https://api.example.com"]},
        "extensions": [{"type": "tool", "id": "example_tool", "entry_point": "example.tool:tool"}],
    }


def _dist(tmp_path: Path, raw: dict | None = None, name: str = "example-plugin") -> SimpleNamespace:
    package_dir = tmp_path / name
    package_dir.mkdir()
    path = package_dir / "deeptutor.plugin.json"
    path.write_text(json.dumps(raw if raw is not None else _manifest()), encoding="utf-8")
    file_ref = SimpleNamespace(name=path.name, path=path.name)
    return SimpleNamespace(
        files=[file_ref],
        locate_file=lambda ref: package_dir / ref.path,
        metadata={"Name": name},
    )


def test_registry_reads_manifest_without_importing_plugin(tmp_path) -> None:
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[_dist(tmp_path)],
        deeptutor_version="1.6.0",
    )

    records = registry.list_plugins(include_catalog=False)

    assert [record.id for record in records] == ["org.author.example"]
    assert records[0].status == "approval-required"
    assert records[0].manifest is not None
    assert records[0].manifest.extensions[0].id == "example_tool"


def test_registry_reports_incompatible_and_broken_plugins(tmp_path) -> None:
    incompatible = _dist(
        tmp_path,
        _manifest("org.author.future", deeptutor=">=2.0.0"),
        "future-plugin",
    )
    broken = _dist(tmp_path, {"id": "org.author.broken"}, "broken-plugin")
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[incompatible, broken],
        deeptutor_version="1.6.0",
    )

    records = {record.id: record for record in registry.list_plugins(include_catalog=False)}

    assert records["org.author.future"].status == "incompatible"
    assert "requires DeepTutor" in records["org.author.future"].error
    assert records["org.author.broken"].status == "broken"


def test_registry_gates_web_and_app_extension_api_contracts(tmp_path) -> None:
    raw = _manifest()
    raw["compatibility"]["api"] = {
        "http_route": "1",
        "frontend_page": "1",
        "persistence_schema": "1",
        "app_connector": "1",
    }
    raw["extensions"] = [
        {"type": extension_type, "id": f"example_{extension_type}", **declaration}
        for extension_type, declaration in (
            (
                "http_route",
                {
                    "entry_point": "example.worker",
                    "path": "/echo",
                    "methods": ["GET"],
                    "auth": "admin",
                },
            ),
            ("frontend_page", {"path": "/page", "auth": "authenticated"}),
            ("persistence_schema", {"schema": "schemas/example.json", "operations": ["read"]}),
            ("app_connector", {"operations": ["import"]}),
        )
    ]
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[_dist(tmp_path, raw, "web-plugin")],
        deeptutor_version="1.6.0",
    )

    record = registry.get_plugin("org.author.example")
    assert record is not None
    assert record.status == "approval-required"

    raw["compatibility"]["api"]["http_route"] = "2"
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[_dist(tmp_path, raw, "web-plugin-v2")],
        deeptutor_version="1.6.0",
    )
    record = registry.get_plugin("org.author.example")
    assert record is not None
    assert record.status == "incompatible"
    assert record.error == "requires http_route API newer than this build"


def test_approve_enable_disable_persists_local_state(tmp_path) -> None:
    state_path = tmp_path / "plugins.json"
    registry = PluginRegistry(
        state_path=state_path,
        installed_distributions=[_dist(tmp_path)],
        deeptutor_version="1.6.0",
    )
    record = registry.get_plugin("org.author.example")
    assert record is not None and record.manifest is not None

    approved = registry.approve("org.author.example")
    disabled = registry.set_enabled("org.author.example", False)
    enabled = registry.set_enabled("org.author.example", True)

    assert approved.status == "enabled"
    assert disabled.status == "disabled"
    assert enabled.status == "enabled"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "version": 2,
        "disabled": [],
        "plugins": {
            "org.author.example": {
                "manifest": record.manifest.to_dict(),
                "installation": None,
                "history": [],
                "approval": {
                    "digest": permission_digest(record.manifest.permissions),
                    "approved_at": state["plugins"]["org.author.example"]["approval"][
                        "approved_at"
                    ],
                },
            }
        },
    }


def test_registry_migrates_legacy_state(tmp_path) -> None:
    state_path = tmp_path / "plugins.json"
    state_path.write_text(json.dumps({"version": 1, "disabled": ["old"]}), encoding="utf-8")
    registry = PluginRegistry(
        state_path=state_path,
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )

    migrated = registry.state_snapshot()

    assert migrated == {
        "version": 2,
        "disabled": ["old"],
        "plugins": {},
    }
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "disabled": ["old"],
    }


def test_registry_marks_managed_version_deprecated_from_catalog(tmp_path) -> None:
    manifest = _manifest()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "deeptutor.plugin-catalog/v2",
                "meta": {
                    "generated_at": "2026-09-08T00:00:00Z",
                    "reviewed_at": "2026-09-08T00:00:00Z",
                    "reviewers": ["maintainer"],
                },
                "entries": [
                    {
                        **{
                            key: value
                            for key, value in manifest.items()
                            if key not in {"schema_version", "extensions"}
                        },
                        "status": "deprecated",
                        "artifact": {
                            "kind": "python-package",
                            "requirement": "example-plugin==1.0.0",
                            "sha256": "0" * 64,
                            "url": "https://example.com/example-1.0.0.whl",
                            "size_bytes": 128,
                            "platform_tags": ["py3-none-any"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "plugins.json"
    registry = PluginRegistry(
        state_path=state_path,
        catalog_path=catalog_path,
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    state = registry.state_snapshot()
    state["plugins"]["org.author.example"] = {
        "manifest": manifest,
        "installation": {
            "version": "1.0.0",
            "artifact_path": str(tmp_path / "example.whl"),
            "artifact_sha256": "0" * 64,
            "venv_path": str(tmp_path / "venv"),
            "python_path": str(tmp_path / "venv" / "bin" / "python"),
            "installed_at": "2026-09-08T00:00:00Z",
            "dependencies": [],
        },
        "history": [],
    }
    registry.replace_state(state)

    record = registry.get_plugin("org.author.example")

    assert record is not None
    assert record.status == "deprecated"
