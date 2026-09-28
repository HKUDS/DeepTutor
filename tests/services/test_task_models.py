"""The task service: configured like the LLM, inherited when empty."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.model_selection.tasks import task_service_configured


def _catalog(service: ModelCatalogService, **task: Any) -> dict[str, Any]:
    catalog = service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "llm-1",
            "name": "OpenAI",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-live",
            "models": [{"id": "llm-model", "model": "gpt-5"}],
        }
    ]
    catalog["services"]["llm"]["active_profile_id"] = "llm-1"
    catalog["services"]["llm"]["active_model_id"] = "llm-model"
    catalog["services"]["task"].update(task)
    return catalog


def test_the_task_service_exists_and_starts_empty(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    catalog = service.load()

    assert catalog["services"]["task"] == {
        "active_profile_id": None,
        "active_model_id": None,
        "profiles": [],
    }
    assert not task_service_configured(catalog)


def test_an_empty_task_service_inherits(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    catalog = service.save(_catalog(service))

    assert not task_service_configured(catalog)


def test_a_configured_task_service_is_used(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-live",
                    "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    assert task_service_configured(catalog)


def test_a_profile_without_a_model_id_still_inherits(tmp_path: Path) -> None:
    """Half-configured is not configured — a blank model would resolve to nothing."""
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "api_key": "sk-live",
                    "models": [{"id": "task-model", "model": ""}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    assert not task_service_configured(catalog)


def test_the_task_service_resolves_its_own_model(tmp_path: Path) -> None:
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-task",
                    "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    task = resolve_llm_runtime_config(catalog, service=service, service_name="task")
    llm = resolve_llm_runtime_config(catalog, service=service)

    assert task.model == "gpt-5-mini"
    assert llm.model == "gpt-5"


def test_the_short_lived_per_task_pins_are_dropped(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = _catalog(service)
    catalog["services"]["llm"]["tasks"] = {
        "session_title": {"profile_id": "llm-1", "model_id": "llm-model"}
    }

    saved = service.save(catalog)

    assert "tasks" not in saved["services"]["llm"]


def _with_task_model(service: ModelCatalogService, **task: Any) -> dict[str, Any]:
    """A catalog whose task service names a small model of its own."""
    return _catalog(
        service,
        profiles=[
            {
                "id": "task-1",
                "name": "OpenAI",
                "binding": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-task",
                "models": [
                    {"id": "task-model", "model": "gpt-5-mini"},
                    {"id": "task-nano", "model": "gpt-5-nano"},
                ],
            }
        ],
        active_profile_id="task-1",
        active_model_id="task-model",
        **task,
    )


def test_a_task_without_an_override_follows_the_global_model(tmp_path: Path) -> None:
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.model_selection.tasks import TaskKind, catalog_for_task

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(_with_task_model(service))

    resolved = catalog_for_task(catalog, TaskKind.SESSION_TITLE)

    assert resolved is catalog
    assert task_service_configured(catalog, kind=TaskKind.SESSION_TITLE)
    assert (
        resolve_llm_runtime_config(resolved, service=service, service_name="task").model
        == "gpt-5-mini"
    )


def test_a_task_can_pin_its_own_model(tmp_path: Path) -> None:
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.model_selection.tasks import TaskKind, catalog_for_task

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _with_task_model(
            service,
            overrides={
                "reading_translation": {
                    "mode": "profiles",
                    "active_profile_id": "task-1",
                    "active_model_id": "task-nano",
                }
            },
        )
    )

    pinned = catalog_for_task(catalog, TaskKind.READING_TRANSLATION)
    other = catalog_for_task(catalog, TaskKind.SESSION_TITLE)

    assert resolve_llm_runtime_config(pinned, service=service, service_name="task").model == (
        "gpt-5-nano"
    )
    assert resolve_llm_runtime_config(other, service=service, service_name="task").model == (
        "gpt-5-mini"
    )
    # The stored catalog is never rewritten in place by resolving one task.
    assert catalog["services"]["task"]["active_model_id"] == "task-model"


def test_a_task_can_follow_the_chat_model_while_the_rest_do_not(tmp_path: Path) -> None:
    from deeptutor.services.model_selection.tasks import TaskKind, catalog_for_task

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _with_task_model(service, overrides={"reading_quiz": {"mode": "inherit"}})
    )

    assert not task_service_configured(catalog, kind=TaskKind.READING_QUIZ)
    assert task_service_configured(catalog, kind=TaskKind.SESSION_TITLE)
    # Inheriting is a no-op scope, so the quiz keeps running on the chat model.
    assert catalog_for_task(catalog, TaskKind.READING_QUIZ)["services"]["task"]["mode"] == (
        "inherit"
    )


def test_a_task_can_reference_a_chat_model(tmp_path: Path) -> None:
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.model_selection.tasks import TaskKind, catalog_for_task

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _with_task_model(
            service,
            overrides={
                "chat_starters": {
                    "mode": "reference",
                    "selection": {"profile_id": "llm-1", "model_id": "llm-model"},
                }
            },
        )
    )

    resolved = catalog_for_task(catalog, TaskKind.CHAT_STARTERS)

    assert task_service_configured(catalog, kind=TaskKind.CHAT_STARTERS)
    assert (
        resolve_llm_runtime_config(resolved, service=service, service_name="task").model == "gpt-5"
    )


def test_a_half_written_override_follows_the_global_model(tmp_path: Path) -> None:
    """Never fail a title over a malformed pin — the global choice is the answer."""
    from deeptutor.services.model_selection.tasks import TaskKind, task_override

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _with_task_model(
            service,
            overrides={
                "session_title": {"mode": "profiles", "active_profile_id": "task-1"},
                "chat_starters": {"mode": "reference"},
                "chat_ask_hint": {"mode": "global"},
                "mastery_goal_name": "gpt-5-nano",
            },
        )
    )

    for kind in (
        TaskKind.SESSION_TITLE,
        TaskKind.CHAT_STARTERS,
        TaskKind.CHAT_ASK_HINT,
        TaskKind.MASTERY_GOAL_NAME,
    ):
        assert task_override(catalog, kind) is None


def test_overrides_survive_a_catalog_round_trip(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    service.save(_with_task_model(service, overrides={"session_title": {"mode": "inherit"}}))

    reloaded = ModelCatalogService(path=tmp_path / "model_catalog.json").load()

    assert reloaded["services"]["task"]["overrides"] == {"session_title": {"mode": "inherit"}}


def test_a_pin_for_a_retired_kind_is_dropped(tmp_path: Path) -> None:
    """Removing a TaskKind must not strand the model its old pin pointed at."""
    from deeptutor.services.model_selection.tasks import TaskKind, catalog_for_task

    path = tmp_path / "model_catalog.json"
    service = ModelCatalogService(path=path)
    pin = {"mode": "profiles", "active_profile_id": "task-1", "active_model_id": "task-nano"}
    catalog = _with_task_model(service, overrides={"reading_openers": pin})
    # Written as an older version left it, not through save(), which would prune.
    path.write_text(json.dumps(catalog), encoding="utf-8")

    reloaded = ModelCatalogService(path=path).load()

    assert "overrides" not in reloaded["services"]["task"]
    assert "overrides" not in json.loads(path.read_text(encoding="utf-8"))["services"]["task"]
    assert catalog_for_task(reloaded, TaskKind.READING_ASK_HINT) is reloaded


def test_pruning_retired_pins_keeps_the_live_ones(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    live = {"mode": "inherit"}
    catalog = service.save(
        _with_task_model(
            service, overrides={"session_title": live, "reading_openers": {"mode": "inherit"}}
        )
    )

    assert catalog["services"]["task"]["overrides"] == {"session_title": live}


def test_every_task_model_call_site_names_a_kind() -> None:
    """The settings page lists TaskKind, so a call site with no kind would hide.

    ``task_llm_scope()`` with no argument is a TypeError at runtime, but this
    catches it at test time and, more usefully, catches a call site that passes
    something other than a TaskKind member.
    """
    import re

    from deeptutor.services.model_selection.tasks import TaskKind

    root = Path(__file__).resolve().parents[2] / "deeptutor"
    calls = []
    for path in root.rglob("*.py"):
        if path.name == "tasks.py" and path.parent.name == "model_selection":
            continue
        for match in re.finditer(r"task_llm_scope\(([^)]*)\)", path.read_text()):
            calls.append((path.name, match.group(1).strip()))

    assert calls, "no task model call sites found — did the module move?"
    named = {f"TaskKind.{member.name}" for member in TaskKind}
    assert {argument for _, argument in calls} <= named, calls
