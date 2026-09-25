"""The task model — what DeepTutor runs on when nobody asked it to run.

A dozen calls happen without anyone requesting them: naming a conversation once
it has its first exchange, naming a mastery goal, writing the lines under a
composer, answering a lookup in the margin of a reading. All of them are short,
frequent and latency-visible, and none benefits from the model a learner picked
for their actual reasoning — a small fast model writes a four-word title just as
well and costs a fraction as much.

So the catalog carries a ``task`` service, shaped exactly like ``llm``:
providers with credentials, models under them, one of each in use. Configuring
it is the same act as configuring the LLM because it is the same kind of thing,
and a provider can be brought over from the LLM service rather than typed again.

Not every one of those calls wants the same model, though. Writing a title is
throwaway work; explaining a word a learner just looked up is not. So each call
site names itself with a :class:`TaskKind`, and ``services.task.overrides`` may
pin a kind to something other than the global choice. An absent override is the
common case and means *follow the global task model*.

Leaving the whole thing empty is the default. Then the scope below is a no-op
and every call resolves what it always did — for the title, the model the turn
itself is running on; for the starters, the active default. Failure inherits
too: a task profile pointing at nothing, a catalog that will not load, a
provider that no longer works — none of that is worth failing a title over.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Any

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.llm.config import LLMConfig

logger = logging.getLogger(__name__)

TASK_SERVICE = "task"

# Where per-kind pins live inside ``services.task``. Deliberately not
# ``services.llm.tasks``, the short-lived key the catalog still drops on load:
# that one hung two loose {profile, model} references off the *chat* service
# with nothing in the UI to show or change them. These hang off the task
# service, carry its own three modes, and every one of them is listed on the
# task models page.
TASK_OVERRIDES_KEY = "overrides"


class TaskKind(StrEnum):
    """One call DeepTutor makes on its own.

    Every ``task_llm_scope`` call site names one. That is what lets the settings
    page list what actually uses the task model instead of a hand-kept list that
    drifts: adding a call site means adding a member here, and the page grows a
    row for it.
    """

    SESSION_TITLE = "session_title"
    CHAT_STARTERS = "chat_starters"
    CHAT_ASK_HINT = "chat_ask_hint"
    MASTERY_ASK_HINT = "mastery_ask_hint"
    MASTERY_GOAL_NAME = "mastery_goal_name"
    READING_ASK_HINT = "reading_ask_hint"
    READING_QUIZ = "reading_quiz"
    READING_VOCABULARY = "reading_vocabulary"
    READING_TRANSLATION = "reading_translation"
    READING_GUIDANCE = "reading_guidance"


@dataclass(frozen=True)
class TaskKindSpec:
    """A kind and the surface it belongs to, for grouping on the settings page."""

    kind: TaskKind
    group: str


# Ordered as the settings page lists them: the surface a learner would look for
# first, then within it the call that runs most often.
TASK_KINDS: tuple[TaskKindSpec, ...] = (
    TaskKindSpec(TaskKind.SESSION_TITLE, "chat"),
    TaskKindSpec(TaskKind.CHAT_STARTERS, "chat"),
    TaskKindSpec(TaskKind.CHAT_ASK_HINT, "chat"),
    TaskKindSpec(TaskKind.MASTERY_GOAL_NAME, "mastery"),
    TaskKindSpec(TaskKind.MASTERY_ASK_HINT, "mastery"),
    TaskKindSpec(TaskKind.READING_ASK_HINT, "reading"),
    TaskKindSpec(TaskKind.READING_VOCABULARY, "reading"),
    TaskKindSpec(TaskKind.READING_TRANSLATION, "reading"),
    TaskKindSpec(TaskKind.READING_GUIDANCE, "reading"),
    TaskKindSpec(TaskKind.READING_QUIZ, "reading"),
)

# The three ways a task model can be chosen, global or per kind. A fourth state
# exists only per kind and is spelled by the *absence* of an override: follow
# whatever the global task model is.
TASK_MODES: frozenset[str] = frozenset({"inherit", "reference", "profiles"})


def task_kind_payload() -> list[dict[str, str]]:
    """The kind list as the settings page consumes it."""
    return [{"id": str(spec.kind), "group": spec.group} for spec in TASK_KINDS]


def _task_service(catalog: dict[str, Any]) -> dict[str, Any]:
    services = catalog.get("services")
    service = services.get(TASK_SERVICE) if isinstance(services, dict) else None
    return service if isinstance(service, dict) else {}


def task_override(catalog: dict[str, Any], kind: TaskKind | str | None) -> dict[str, Any] | None:
    """The pin for *kind*, or ``None`` when it follows the global choice.

    A malformed or half-written override reads as absent rather than as an
    error: these calls are not worth failing over, and the global model is the
    answer the user last agreed to.
    """
    if kind is None:
        return None
    overrides = _task_service(catalog).get(TASK_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return None
    override = overrides.get(str(kind))
    if not isinstance(override, dict):
        return None
    mode = override.get("mode")
    if mode not in TASK_MODES:
        return None
    if mode == "reference" and not override.get("selection"):
        return None
    if mode == "profiles" and not (
        override.get("active_profile_id") and override.get("active_model_id")
    ):
        return None
    return override


def catalog_for_task(catalog: dict[str, Any], kind: TaskKind | str | None) -> dict[str, Any]:
    """*catalog* with ``services.task`` reading as what this kind runs on.

    Overrides resolve by rewriting the service rather than by a second code
    path, so ``task_service_configured`` and ``resolve_llm_runtime_config``
    stay the single implementation of what each mode means.
    """
    override = task_override(catalog, kind)
    if override is None:
        return catalog
    patched = deepcopy(catalog)
    services = patched.setdefault("services", {})
    service = services.get(TASK_SERVICE)
    if not isinstance(service, dict):
        service = {"active_profile_id": None, "active_model_id": None, "profiles": []}
        services[TASK_SERVICE] = service
    mode = override["mode"]
    service["mode"] = mode
    service.pop("selection", None)
    if mode == "reference":
        service["selection"] = deepcopy(override["selection"])
    elif mode == "profiles":
        # Pointers into the task service's own profiles — the same pool the
        # global choice draws from, so a kind can pin a model the global one
        # does not use without configuring the provider twice.
        service["active_profile_id"] = override["active_profile_id"]
        service["active_model_id"] = override["active_model_id"]
    return patched


def task_service_configured(
    catalog: dict[str, Any] | None = None, *, kind: TaskKind | str | None = None
) -> bool:
    """Whether *kind* (or the global choice) names a model of its own."""
    try:
        loaded = catalog if catalog is not None else get_model_catalog_service().load()
        loaded = catalog_for_task(loaded, kind)
        service = _task_service(loaded)
        if service.get("mode") == "inherit":
            return False
        if service.get("mode") == "reference":
            from .llm import apply_llm_selection_to_catalog

            selection = service.get("selection")
            if not selection:
                return False
            apply_llm_selection_to_catalog(loaded, selection)
            return True
        profile_id = service.get("active_profile_id")
        profile = next(
            (
                item
                for item in service.get("profiles", []) or []
                if isinstance(item, dict) and item.get("id") == profile_id
            ),
            None,
        )
        if profile is None:
            return False
        model_id = service.get("active_model_id")
        return any(
            isinstance(model, dict)
            and model.get("id") == model_id
            and str(model.get("model") or "").strip()
            for model in profile.get("models", []) or []
        )
    except Exception:
        logger.debug("Task service lookup failed — inheriting", exc_info=True)
        return False


@contextmanager
def task_llm_scope(kind: TaskKind) -> Iterator[LLMConfig | None]:
    """Install the task model for *kind* for the duration of the block.

    Yields the config that was installed, or ``None`` when this kind inherits —
    which callers can log but never have to branch on. *kind* is required so
    that the settings page can list every call that runs on a task model; a new
    call site with no kind to name is a new :class:`TaskKind` member.
    """
    try:
        catalog = catalog_for_task(get_model_catalog_service().load(), kind)
    except Exception:
        logger.debug("Task catalog unreadable — inheriting", exc_info=True)
        yield None
        return

    if not task_service_configured(catalog):
        yield None
        return

    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.llm import config as llm_config_module

    from .runtime import llm_config_from_resolved

    try:
        config = llm_config_from_resolved(
            resolve_llm_runtime_config(catalog, service_name=TASK_SERVICE)
        )
        token = llm_config_module.set_scoped_llm_config(config)
    except Exception:
        # Configured but unusable. Inheriting is strictly better than not
        # writing a title at all.
        logger.debug("Task model activation failed — inheriting", exc_info=True)
        yield None
        return
    try:
        yield config
    finally:
        llm_config_module.reset_scoped_llm_config(token)


__all__ = [
    "TASK_KINDS",
    "TASK_MODES",
    "TASK_OVERRIDES_KEY",
    "TASK_SERVICE",
    "TaskKind",
    "TaskKindSpec",
    "catalog_for_task",
    "task_kind_payload",
    "task_llm_scope",
    "task_override",
    "task_service_configured",
]
