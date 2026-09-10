from __future__ import annotations

import json

import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.services.config.model_catalog import SERVICE_NAMES
from deeptutor.services.config.readiness import (
    DETAIL_CODES,
    PARSER_REPORT_REASONS,
    READINESS_STATES,
    catalog_service_rows,
    coordination_rows,
    document_parser_rows,
    readiness_snapshot,
    tool_rows,
    visualizer_rows,
)


def _notice_codes(snapshot: dict, severity: str) -> list[str]:
    return [notice["code"] for notice in snapshot["notices"] if notice["severity"] == severity]


def _empty_catalog() -> dict:
    return {
        "services": {
            name: {"active_profile_id": None, "active_model_id": None, "profiles": []}
            for name in SERVICE_NAMES
        }
    }


def test_catalog_readiness_is_value_free_and_detects_stale_selection() -> None:
    catalog = _empty_catalog()
    catalog["services"]["llm"] = {
        "active_profile_id": "missing-profile",
        "active_model_id": "secret-model-id",
        "profiles": [
            {
                "id": "other-profile",
                "api_key": "secret-api-key",
                "base_url": "https://secret.example.test/v1",
                "models": [{"id": "secret-model-id", "model": "secret-model-name"}],
            }
        ],
    }

    rows = catalog_service_rows(catalog)

    llm = next(row for row in rows if row["id"] == "catalog.llm")
    assert llm["state"] == "misconfigured"
    assert llm["detail_code"] == "active_profile_missing"
    serialized = json.dumps(rows)
    assert "secret-api-key" not in serialized
    assert "secret.example.test" not in serialized
    assert "secret-model-name" not in serialized


def test_selected_remote_parser_must_be_installed_ready_and_reachable() -> None:
    entries = [
        {"id": "tika", "name": "Tika", "available": True},
        {"id": "docling", "name": "Docling", "available": False},
    ]

    unreachable = document_parser_rows(
        entries,
        "tika",
        {"tika": {"ready": True}},
        selected_remote_reachable=False,
    )
    unavailable = document_parser_rows(
        entries,
        "docling",
        {"tika": {"ready": True}},
    )

    assert unreachable[0]["state"] == "misconfigured"
    assert unreachable[0]["detail_code"] == "selected_parser_unreachable"
    assert unavailable[1]["state"] == "misconfigured"
    assert unavailable[1]["detail_code"] == "selected_parser_unavailable"


def test_optional_capability_left_unconfigured_is_not_reported_as_a_fault() -> None:
    """A fresh install owes nobody a video model.

    Everything in this scenario is untouched default state: no chat model, no
    image model, and the imagegen/videogen tools still switched on because
    that is how they ship.  Only the chat model -- the one thing the install
    cannot run without -- may be graded as a problem.
    """

    catalog_rows = catalog_service_rows(_empty_catalog())
    dependency_rows = {row["id"]: row for row in catalog_rows}
    tools = tool_rows(["imagegen", "videogen"], dependency_rows)
    snapshot = readiness_snapshot(catalog_rows + tools)

    videogen_tool = next(row for row in tools if row["id"] == "tool.videogen")
    assert videogen_tool["state"] == "unavailable"
    assert videogen_tool["detail_code"] == "tool_backend_not_configured"

    assert _notice_codes(snapshot, "blocker") == ["active_profile_not_selected"]
    assert [notice["row_id"] for notice in snapshot["notices"]] == ["catalog.llm"]
    assert _notice_codes(snapshot, "warning") == []


def test_embedding_only_becomes_required_once_a_knowledge_base_exists() -> None:
    without_kb = readiness_snapshot(catalog_service_rows(_empty_catalog()))
    with_kb = readiness_snapshot(
        catalog_service_rows(_empty_catalog(), required_services=frozenset({"llm", "embedding"}))
    )

    assert [notice["row_id"] for notice in without_kb["notices"]] == ["catalog.llm"]
    assert [notice["row_id"] for notice in with_kb["notices"]] == [
        "catalog.llm",
        "catalog.embedding",
    ]


def test_enabled_tool_whose_configured_backend_broke_is_a_warning() -> None:
    """The other half of the rule: a selection that *was* made and now fails."""

    visualizers = visualizer_rows(
        [
            {
                "id": "manim_video",
                "display_name": "Manim animation",
                "installed": True,
                "enabled": True,
            }
        ],
        manim_available=False,
    )
    dependency_rows = {row["id"]: row for row in visualizers}
    dependency_rows["catalog.imagegen"] = {
        "id": "catalog.imagegen",
        "state": "misconfigured",
    }

    tools = tool_rows(["geogebra_analysis", "imagegen"], dependency_rows)
    snapshot = readiness_snapshot(visualizers + tools)

    # Installed-and-on by default with no manim package: unavailable, not a fault.
    assert visualizers[0]["state"] == "unavailable"
    assert visualizers[0]["detail_code"] == "visualizer_runtime_missing"
    imagegen = next(row for row in tools if row["id"] == "tool.imagegen")
    assert imagegen["state"] == "misconfigured"
    assert imagegen["detail_code"] == "enabled_tool_backend_failing"
    assert _notice_codes(snapshot, "warning") == ["enabled_tool_backend_failing"]
    assert _notice_codes(snapshot, "blocker") == []


def test_redis_available_while_memory_selected_is_only_a_suggestion() -> None:
    rows, extra = coordination_rows(
        backend="memory",
        backend_workers=1,
        redis_configured=True,
        redis_reachable=True,
    )
    snapshot = readiness_snapshot(rows, extra_notices=extra)

    assert rows[1]["state"] == "available_disabled"
    # A single-worker install runs fine on in-memory coordination, so nothing
    # here is broken and ``ok`` stays true.
    assert snapshot["ok"] is True
    assert snapshot["notices"] == [
        {
            "code": "redis_available_but_memory_selected",
            "row_id": "runtime.coordination.redis",
            "section": "runtime",
            "severity": "suggestion",
        }
    ]
    assert set(snapshot["summary"]) == set(READINESS_STATES)


def test_selected_coordination_backend_that_cannot_run_blocks() -> None:
    rows, extra = coordination_rows(
        backend="redis",
        backend_workers=2,
        redis_configured=True,
        redis_reachable=False,
    )
    snapshot = readiness_snapshot(rows, extra_notices=extra)

    assert snapshot["ok"] is False
    assert _notice_codes(snapshot, "blocker") == ["redis_unreachable"]


@pytest.mark.asyncio
async def test_readiness_endpoint_is_admin_guarded_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guarded = False
    expected = {"schema_version": "deeptutor.settings-readiness/v2", "rows": []}

    def require_admin() -> None:
        nonlocal guarded
        guarded = True

    async def build() -> dict:
        return expected

    monkeypatch.setattr(settings_router, "_require_settings_admin", require_admin)
    monkeypatch.setattr("deeptutor.services.config.readiness.build_settings_readiness", build)

    assert await settings_router.get_settings_readiness() is expected
    assert guarded is True


def test_every_detail_code_this_module_emits_is_declared() -> None:
    """Codes are user-facing copy in disguise.

    Each one is looked up as a translated sentence in Settings, so a code that
    exists only in a branch of this file reaches the user as a raw identifier.
    Walk the module and prove the declared set is complete.
    """

    import ast
    import inspect

    from deeptutor.services.config import readiness as module

    tree = ast.parse(inspect.getsource(module))
    emitted: set[str] = set()
    for node in ast.walk(tree):
        # `detail_code = "..."` / `detail: str = "..."`
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in {"detail_code", "redis_detail"}
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    emitted.add(node.value.value)
        # `readiness_row(id, section, label, state, "detail_code", ...)`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "readiness_row"
            and len(node.args) >= 5
            and isinstance(node.args[4], ast.Constant)
            and isinstance(node.args[4].value, str)
        ):
            emitted.add(node.args[4].value)
        # Notice dicts carry their code under "code".
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    emitted.add(value.value)

    # Guards the walk itself: a broken pattern must fail loudly, not vacuously.
    assert len(emitted) >= 25, f"only found {len(emitted)} codes in the module"
    # ``readiness_snapshot`` falls back to the bare state name when a row
    # somehow arrives without a code, which is not itself a documented code.
    undeclared = emitted - DETAIL_CODES - {"misconfigured"}
    assert undeclared == set(), sorted(undeclared)
    assert PARSER_REPORT_REASONS <= DETAIL_CODES


def test_declared_row_labels_cover_the_label_tables() -> None:
    """The two label tables feed rows directly, so they cannot drift silently."""

    from deeptutor.services.config.readiness import (
        _SERVICE_LABELS,
        _TOOL_LABELS,
        TRANSLATABLE_ROW_LABELS,
    )

    from_tables = set(_SERVICE_LABELS.values()) | set(_TOOL_LABELS.values())
    assert from_tables <= TRANSLATABLE_ROW_LABELS, sorted(from_tables - TRANSLATABLE_ROW_LABELS)
