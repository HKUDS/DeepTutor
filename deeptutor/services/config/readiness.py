"""Value-free capability readiness matrix for the Settings overview.

The matrix deliberately exposes identities, booleans, and stable reason codes
only.  Provider URLs, model names, credentials, and exception text stay on the
server.  Network probes are limited to configured infrastructure backends and
selected remote document parsers; model providers are never called here.

Readiness is not the same thing as correctness.  Most of what DeepTutor can be
configured with is optional: nobody has to own a video model, and a parser that
is not installed is not a fault.  Every row therefore carries ``required`` --
whether the install genuinely depends on it -- and the snapshot grades what it
found into three severities instead of treating every non-green row as a
problem:

``blocker``
    Something the install *needs* is not usable (no chat model; the selected
    document parser is broken).
``warning``
    Something the operator *did* configure or select does not work.  An
    optional capability that was simply never set up never lands here.
``suggestion``
    Purely advisory -- a better option is available but nothing is wrong.
"""

from __future__ import annotations

import asyncio
from collections import Counter
import importlib.util
from typing import Any, Literal

from deeptutor.services.config.model_catalog import SERVICE_NAMES
from deeptutor.tools.builtin import USER_TOGGLEABLE_TOOL_NAMES

ReadinessState = Literal[
    "enabled_verified",
    "available_disabled",
    "unavailable",
    "misconfigured",
    "not_selected",
]

SCHEMA_VERSION = "deeptutor.settings-readiness/v2"
READINESS_STATES: tuple[ReadinessState, ...] = (
    "enabled_verified",
    "available_disabled",
    "unavailable",
    "misconfigured",
    "not_selected",
)

Severity = Literal["blocker", "warning", "suggestion"]
SEVERITIES: tuple[Severity, ...] = ("blocker", "warning", "suggestion")

#: States in which a capability is either running or one toggle away from it.
USABLE_STATES: frozenset[str] = frozenset({"enabled_verified", "available_disabled"})

#: Every stable reason code this module can attach to a row or a notice.
#: The Settings UI carries one translated sentence per code, so a code that
#: ships without an entry here (and there) reaches users as a raw identifier.
#: ``tests/services/config/test_readiness.py`` walks this module's AST to keep
#: the set honest; the four parser reasons come from engine readiness reports
#: rather than from a literal in this file.
DETAIL_CODES: frozenset[str] = frozenset(
    {
        # Nothing to explain -- the row is running.
        "configuration_verified",
        "remote_endpoint_verified",
        "knowledge_base_ready",
        "visualizer_ready",
        "tool_ready",
        "video_provider_ready",
        "coordination_ready",
        # Catalog services
        "active_profile_not_selected",
        "active_profile_missing",
        "active_model_not_selected",
        "active_model_missing",
        "model_identifier_missing",
        "provider_not_selected",
        "required_credential_missing",
        # Document parsers, including the engines' own readiness reasons
        "selected_parser_unavailable",
        "selected_parser_unreachable",
        "selected_parser_unknown",
        "parser_not_ready",
        "parser_probe_failed",
        "parser_not_selected",
        "parser_package_missing",
        "not_configured",
        "update_required",
        "models_missing",
        "cli_missing",
        # Knowledge bases
        "no_knowledge_base",
        "knowledge_base_building",
        "knowledge_base_needs_reindex",
        "rag_prerequisite_missing",
        "knowledge_base_not_ready",
        # Visualizers
        "visualizer_disabled",
        "visualizer_not_installed",
        "visualizer_runtime_missing",
        # Chat tools
        "tool_disabled",
        "tool_backend_not_configured",
        "enabled_tool_backend_failing",
        "tool_backend_unavailable",
        # Video learning
        "video_provider_not_selected",
        "video_provider_not_configured",
        "selected_video_provider_not_configured",
        "selected_video_provider_unknown",
        # Runtime coordination
        "coordination_not_selected",
        "redis_url_missing",
        "redis_unreachable",
        "redis_not_configured",
        "multiple_workers_require_redis",
        "redis_available_but_memory_selected",
    }
)

#: Reason codes that reach a parser row from an engine's readiness report.
PARSER_REPORT_REASONS: frozenset[str] = frozenset(
    {"not_configured", "update_required", "models_missing", "cli_missing"}
)

#: Catalog services the install cannot do without.  Everything else -- speech,
#: image and video generation, even web search -- is opt-in, and reporting it
#: as a fault for being unset is how a readiness view turns into noise.
#: ``embedding`` joins this set only once a knowledge base exists to need it.
REQUIRED_CATALOG_SERVICES: frozenset[str] = frozenset({"llm"})

_SERVICE_LABELS = {
    "llm": "Chat model",
    "task": "Task model",
    "embedding": "Embedding model",
    "search": "Web search",
    "tts": "Text to speech",
    "stt": "Speech to text",
    "imagegen": "Image generation",
    "videogen": "Video generation",
}

_TOOL_LABELS = {
    "brainstorm": "Brainstorm tool",
    "web_search": "Web search tool",
    "paper_search": "Paper search tool",
    "reason": "Reason tool",
    "geogebra_analysis": "GeoGebra tool",
    "imagegen": "Image generation tool",
    "videogen": "Video generation tool",
}

#: Row labels this module writes itself, as opposed to names that come from
#: user data (knowledge bases) or third-party catalogs (parser engines,
#: visualizer manifests).  The Settings UI runs each through ``t()``, so these
#: are the strings that need a locale entry to avoid an English row in a
#: Chinese page.  ``tests/settings-readiness-i18n.test.ts`` enforces that.
TRANSLATABLE_ROW_LABELS: frozenset[str] = frozenset(
    {
        "Chat model",
        "Task model",
        "Embedding model",
        "Web search",
        "Text to speech",
        "Speech to text",
        "Image generation",
        "Video generation",
        "Brainstorm tool",
        "Web search tool",
        "Paper search tool",
        "Reason tool",
        "GeoGebra tool",
        "Image generation tool",
        "Video generation tool",
        "Selected parser",
        "Knowledge bases",
        "Native YouTube",
        "Invidious",
        "Selected video provider",
        "In-memory turn coordination",
        "Redis turn coordination",
    }
)


_TOOL_DEPENDENCIES = {
    "web_search": "catalog.search",
    "reason": "catalog.task",
    "geogebra_analysis": "visualizer.geogebra",
    "imagegen": "catalog.imagegen",
    "videogen": "catalog.videogen",
}


def readiness_row(
    row_id: str,
    section: str,
    label: str,
    state: ReadinessState,
    detail_code: str,
    *,
    enabled: bool,
    available: bool,
    configured: bool,
    verified: bool,
    required: bool = False,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "section": section,
        "label": label,
        "state": state,
        "detail_code": detail_code,
        "enabled": enabled,
        "available": available,
        "configured": configured,
        "verified": verified,
        "required": required,
    }


def catalog_service_rows(
    catalog: dict[str, Any],
    *,
    required_services: frozenset[str] | set[str] = REQUIRED_CATALOG_SERVICES,
) -> list[dict[str, Any]]:
    """Classify catalog services without returning any configured value."""

    rows: list[dict[str, Any]] = []
    services = catalog.get("services") if isinstance(catalog.get("services"), dict) else {}
    for name in SERVICE_NAMES:
        required = name in required_services
        service = services.get(name) if isinstance(services.get(name), dict) else {}
        profiles = service.get("profiles") if isinstance(service.get("profiles"), list) else []
        active_profile_id = service.get("active_profile_id")
        if not active_profile_id:
            rows.append(
                readiness_row(
                    f"catalog.{name}",
                    "catalog",
                    _SERVICE_LABELS[name],
                    "not_selected",
                    "active_profile_not_selected",
                    enabled=False,
                    available=bool(profiles),
                    configured=False,
                    verified=False,
                    required=required,
                )
            )
            continue

        profile = next(
            (
                item
                for item in profiles
                if isinstance(item, dict) and item.get("id") == active_profile_id
            ),
            None,
        )
        if profile is None:
            rows.append(
                readiness_row(
                    f"catalog.{name}",
                    "catalog",
                    _SERVICE_LABELS[name],
                    "misconfigured",
                    "active_profile_missing",
                    enabled=True,
                    available=False,
                    configured=False,
                    verified=False,
                    required=required,
                )
            )
            continue

        if name == "search":
            provider = str(profile.get("provider") or "").strip()
            configured = bool(provider and provider != "none")
            missing_credential = None
            if configured:
                try:
                    from deeptutor.services.config.provider_runtime import (
                        search_missing_credential,
                    )

                    missing_credential = search_missing_credential(
                        provider,
                        str(profile.get("api_key") or "").strip(),
                        str(profile.get("base_url") or "").strip(),
                    )
                except Exception:
                    missing_credential = "unknown"
            state: ReadinessState = "enabled_verified"
            detail_code = "configuration_verified"
            if not configured:
                state = "not_selected"
                detail_code = "provider_not_selected"
            elif missing_credential:
                state = "misconfigured"
                detail_code = "required_credential_missing"
            rows.append(
                readiness_row(
                    f"catalog.{name}",
                    "catalog",
                    _SERVICE_LABELS[name],
                    state,
                    detail_code,
                    enabled=configured,
                    available=configured and not missing_credential,
                    configured=configured and not missing_credential,
                    verified=configured and not missing_credential,
                    required=required,
                )
            )
            continue

        models = profile.get("models") if isinstance(profile.get("models"), list) else []
        active_model_id = service.get("active_model_id")
        if not active_model_id:
            state = "not_selected"
            detail_code = "active_model_not_selected"
            model = None
        else:
            model = next(
                (
                    item
                    for item in models
                    if isinstance(item, dict) and item.get("id") == active_model_id
                ),
                None,
            )
            if model is None:
                state = "misconfigured"
                detail_code = "active_model_missing"
            elif not str(model.get("model") or "").strip():
                state = "misconfigured"
                detail_code = "model_identifier_missing"
            else:
                state = "enabled_verified"
                detail_code = "configuration_verified"
        ready = state == "enabled_verified"
        rows.append(
            readiness_row(
                f"catalog.{name}",
                "catalog",
                _SERVICE_LABELS[name],
                state,
                detail_code,
                enabled=bool(active_model_id),
                available=ready,
                configured=ready,
                verified=ready,
                required=required,
            )
        )
    return rows


def document_parser_rows(
    entries: list[dict[str, Any]],
    selected_engine: str,
    readiness: dict[str, dict[str, Any]],
    *,
    selected_remote_reachable: bool | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for entry in entries:
        engine_id = str(entry.get("id") or "")
        if not engine_id:
            continue
        known_ids.add(engine_id)
        selected = engine_id == selected_engine
        installed = bool(entry.get("available"))
        report = readiness.get(engine_id) if isinstance(readiness.get(engine_id), dict) else {}
        ready = bool(report.get("ready"))
        if selected and not installed:
            state: ReadinessState = "misconfigured"
            detail_code = "selected_parser_unavailable"
        elif selected and not ready:
            state = "misconfigured"
            detail_code = str(report.get("reason") or "parser_not_ready")
        elif selected and selected_remote_reachable is False:
            state = "misconfigured"
            detail_code = "selected_parser_unreachable"
        elif selected:
            state = "enabled_verified"
            detail_code = (
                "remote_endpoint_verified"
                if selected_remote_reachable is True
                else "configuration_verified"
            )
        elif installed:
            state = "available_disabled"
            detail_code = "parser_not_selected"
        else:
            state = "unavailable"
            detail_code = "parser_package_missing"
        rows.append(
            readiness_row(
                f"parser.{engine_id}",
                "document_parsing",
                str(entry.get("name") or engine_id),
                state,
                detail_code,
                enabled=selected,
                available=installed,
                configured=ready,
                verified=state == "enabled_verified",
                # Uploads run through whichever engine is selected, so only
                # that one is load-bearing; the rest are alternatives.
                required=selected,
            )
        )

    if selected_engine and selected_engine not in known_ids:
        rows.append(
            readiness_row(
                f"parser.{selected_engine}",
                "document_parsing",
                "Selected parser",
                "misconfigured",
                "selected_parser_unknown",
                enabled=True,
                available=False,
                configured=False,
                verified=False,
                required=True,
            )
        )
    return rows


def knowledge_base_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return [
            readiness_row(
                "knowledge.none",
                "knowledge",
                "Knowledge bases",
                "not_selected",
                "no_knowledge_base",
                enabled=False,
                available=True,
                configured=False,
                verified=False,
            )
        ]

    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        status = str(entry.get("status") or "unknown").lower()
        needs_reindex = bool(entry.get("needs_reindex"))
        prerequisites_ready = bool(entry.get("prerequisites_ready", True))
        if status == "ready" and not needs_reindex and prerequisites_ready:
            state: ReadinessState = "enabled_verified"
            detail_code = "knowledge_base_ready"
        elif status in {"initializing", "processing"}:
            state = "unavailable"
            detail_code = "knowledge_base_building"
        elif needs_reindex:
            state = "misconfigured"
            detail_code = "knowledge_base_needs_reindex"
        elif not prerequisites_ready:
            state = "misconfigured"
            detail_code = "rag_prerequisite_missing"
        else:
            state = "misconfigured"
            detail_code = "knowledge_base_not_ready"
        rows.append(
            readiness_row(
                f"knowledge.{index}",
                "knowledge",
                str(entry.get("label") or f"Knowledge base {index + 1}"),
                state,
                detail_code,
                enabled=True,
                available=status == "ready",
                configured=not needs_reindex,
                verified=state == "enabled_verified",
            )
        )
    return rows


def visualizer_rows(
    entries: list[dict[str, Any]], *, manim_available: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        visualizer_id = str(entry.get("id") or "")
        if not visualizer_id:
            continue
        installed = bool(entry.get("installed"))
        enabled = bool(entry.get("enabled"))
        runtime_available = not visualizer_id.startswith("manim_") or manim_available
        # Installed visualizers are enabled by default, so "on but missing its
        # runtime package" is the shape of a fresh install rather than a choice
        # anyone made -- it reports as unavailable, not as a fault.
        if enabled and installed and runtime_available:
            state: ReadinessState = "enabled_verified"
            detail_code = "visualizer_ready"
        elif not installed:
            state = "unavailable"
            detail_code = "visualizer_not_installed"
        elif not runtime_available:
            state = "unavailable"
            detail_code = "visualizer_runtime_missing"
        else:
            state = "available_disabled"
            detail_code = "visualizer_disabled"
        rows.append(
            readiness_row(
                f"visualizer.{visualizer_id}",
                "visualizers",
                str(entry.get("display_name") or visualizer_id),
                state,
                detail_code,
                enabled=enabled,
                available=installed and runtime_available,
                configured=installed,
                verified=state == "enabled_verified",
            )
        )
    return rows


def tool_rows(
    enabled_tools: list[str], dependency_rows: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Classify the user-toggleable chat tools against their backing service.

    Every one of these tools is optional, and most of them lean on a service
    that is optional too.  Leaving a tool switched on while its backing model
    was never configured is the default state of a fresh install, not a fault:
    the tool is simply not offered.  So a missing backend reports as
    ``unavailable`` -- neutral -- and only a backend that *was* configured and
    is now broken is reported as ``misconfigured``.
    """

    enabled_set = set(enabled_tools)
    rows: list[dict[str, Any]] = []
    for tool_id in USER_TOGGLEABLE_TOOL_NAMES:
        enabled = tool_id in enabled_set
        dependency_id = _TOOL_DEPENDENCIES.get(tool_id)
        dependency = dependency_rows.get(dependency_id or "")
        dependency_state = str(dependency.get("state")) if dependency else ""
        dependency_ready = dependency is None or dependency_state in USABLE_STATES
        dependency_broken = dependency_state == "misconfigured"
        if enabled and dependency_ready:
            state: ReadinessState = "enabled_verified"
            detail_code = "tool_ready"
        elif enabled and dependency_broken:
            state = "misconfigured"
            detail_code = "enabled_tool_backend_failing"
        elif enabled:
            state = "unavailable"
            detail_code = "tool_backend_not_configured"
        elif dependency_ready:
            state = "available_disabled"
            detail_code = "tool_disabled"
        else:
            state = "unavailable"
            detail_code = "tool_backend_unavailable"
        rows.append(
            readiness_row(
                f"tool.{tool_id}",
                "tools",
                _TOOL_LABELS[tool_id],
                state,
                detail_code,
                enabled=enabled,
                available=dependency_ready,
                configured=dependency_ready,
                verified=state == "enabled_verified",
            )
        )
    return rows


def video_learning_rows(settings: dict[str, Any]) -> list[dict[str, Any]]:
    selected = str(settings.get("default_provider") or "youtube")
    invidious = settings.get("invidious") if isinstance(settings.get("invidious"), dict) else {}
    invidious_configured = bool(str(invidious.get("api_base_url") or "").strip())
    rows = [
        readiness_row(
            "video.youtube",
            "video_learning",
            "Native YouTube",
            "enabled_verified" if selected == "youtube" else "available_disabled",
            "video_provider_ready" if selected == "youtube" else "video_provider_not_selected",
            enabled=selected == "youtube",
            available=True,
            configured=True,
            verified=selected == "youtube",
        )
    ]
    if selected == "invidious" and not invidious_configured:
        state: ReadinessState = "misconfigured"
        detail_code = "selected_video_provider_not_configured"
    elif selected == "invidious":
        state = "enabled_verified"
        detail_code = "configuration_verified"
    elif invidious_configured:
        state = "available_disabled"
        detail_code = "video_provider_not_selected"
    else:
        state = "not_selected"
        detail_code = "video_provider_not_configured"
    rows.append(
        readiness_row(
            "video.invidious",
            "video_learning",
            "Invidious",
            state,
            detail_code,
            enabled=selected == "invidious",
            available=invidious_configured,
            configured=invidious_configured,
            verified=state == "enabled_verified",
        )
    )
    if selected not in {"youtube", "invidious"}:
        rows.append(
            readiness_row(
                "video.selected",
                "video_learning",
                "Selected video provider",
                "misconfigured",
                "selected_video_provider_unknown",
                enabled=True,
                available=False,
                configured=False,
                verified=False,
            )
        )
    return rows


def coordination_rows(
    *, backend: str, backend_workers: int, redis_configured: bool, redis_reachable: bool
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    memory_selected = backend == "memory"
    memory_misconfigured = memory_selected and backend_workers > 1
    memory_state: ReadinessState = (
        "misconfigured"
        if memory_misconfigured
        else "enabled_verified"
        if memory_selected
        else "available_disabled"
    )
    rows = [
        readiness_row(
            "runtime.coordination.memory",
            "runtime",
            "In-memory turn coordination",
            memory_state,
            "multiple_workers_require_redis"
            if memory_misconfigured
            else "coordination_ready"
            if memory_selected
            else "coordination_not_selected",
            enabled=memory_selected,
            available=True,
            configured=True,
            verified=memory_selected and not memory_misconfigured,
            required=memory_selected,
        )
    ]

    redis_selected = backend == "redis"
    if redis_selected and not redis_configured:
        redis_state: ReadinessState = "misconfigured"
        redis_detail = "redis_url_missing"
    elif redis_selected and not redis_reachable:
        redis_state = "misconfigured"
        redis_detail = "redis_unreachable"
    elif redis_selected:
        redis_state = "enabled_verified"
        redis_detail = "coordination_ready"
    elif redis_reachable:
        redis_state = "available_disabled"
        redis_detail = "coordination_not_selected"
    elif redis_configured:
        redis_state = "unavailable"
        redis_detail = "redis_unreachable"
    else:
        redis_state = "not_selected"
        redis_detail = "redis_not_configured"
    rows.append(
        readiness_row(
            "runtime.coordination.redis",
            "runtime",
            "Redis turn coordination",
            redis_state,
            redis_detail,
            enabled=redis_selected,
            available=redis_reachable,
            configured=redis_configured,
            verified=redis_selected and redis_reachable,
            required=redis_selected,
        )
    )

    notices: list[dict[str, str]] = []
    if memory_selected and redis_reachable:
        # Advisory only: single-worker installs run fine on in-memory
        # coordination, so this is an available upgrade, not a fault.
        notices.append(
            {
                "code": "redis_available_but_memory_selected",
                "row_id": "runtime.coordination.redis",
                "section": "runtime",
                "severity": "suggestion",
            }
        )
    return rows, notices


def _severity_rank(notice: dict[str, str]) -> int:
    severity = notice.get("severity", "warning")
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def row_severity(row: dict[str, Any]) -> Severity | None:
    """Grade one row, or return ``None`` when nothing is wrong with it.

    A required capability that cannot run blocks the install.  A selection the
    operator actually made and that does not work is a warning.  An optional
    capability that was never set up is neither.
    """

    state = str(row.get("state"))
    if row.get("required") and state not in USABLE_STATES:
        return "blocker"
    if state == "misconfigured":
        return "warning"
    return None


def readiness_snapshot(
    rows: list[dict[str, Any]], *, extra_notices: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    counts = Counter(str(row.get("state")) for row in rows)
    notices: list[dict[str, str]] = []
    for row in rows:
        severity = row_severity(row)
        if severity is None:
            continue
        notices.append(
            {
                "code": str(row.get("detail_code") or "misconfigured"),
                "row_id": str(row.get("id") or ""),
                "section": str(row.get("section") or ""),
                "severity": severity,
            }
        )
    notices.extend(extra_notices or [])
    notices.sort(key=_severity_rank)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not any(notice["severity"] in {"blocker", "warning"} for notice in notices),
        "summary": {state: counts.get(state, 0) for state in READINESS_STATES},
        "rows": rows,
        "notices": notices,
    }


async def _selected_remote_parser_reachable(
    engine_id: str, parser: Any, config: Any
) -> bool | None:
    try:
        if engine_id == "tika":
            from deeptutor.services.parsing.engines.tika.remote import verify_remote

            ok, _ = await asyncio.wait_for(
                asyncio.to_thread(verify_remote, config, 2.0), timeout=3.0
            )
            return bool(ok)
        if engine_id == "docling" and bool(getattr(config, "is_remote", False)):
            from deeptutor.services.parsing.engines.docling.remote import verify_remote

            ok, _ = await asyncio.wait_for(
                asyncio.to_thread(verify_remote, config, 2.0), timeout=3.0
            )
            return bool(ok)
        if engine_id == "mineru" and bool(getattr(config, "is_cloud", False)):
            import httpx

            async with httpx.AsyncClient(timeout=2.0, follow_redirects=True) as client:
                response = await client.get(str(getattr(config, "api_base_url", "") or ""))
            return response.status_code < 500
    except Exception:
        return False
    return None


async def _redis_reachable(redis_url: str) -> bool:
    if not redis_url:
        return False
    coordinator = None
    try:
        from deeptutor.runtime.coordination.redis import RedisCoordinator

        coordinator = RedisCoordinator(redis_url)
        return bool(await asyncio.wait_for(coordinator.health(), timeout=1.5))
    except Exception:
        return False
    finally:
        if coordinator is not None:
            try:
                await asyncio.wait_for(coordinator.close(), timeout=1.0)
            except Exception:
                pass


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


async def build_settings_readiness() -> dict[str, Any]:
    """Build the current admin-scoped readiness matrix."""

    from deeptutor.multi_user.knowledge_access import current_kb_manager
    from deeptutor.services.config import get_model_catalog_service, get_runtime_settings_service
    from deeptutor.services.parsing.engines.factory import get_parser, list_engines
    from deeptutor.services.rag.preflight import engine_preflight
    from deeptutor.services.settings.interface_settings import get_enabled_optional_tools
    from deeptutor.video_learning import load_video_learning_settings
    from deeptutor.visualizers.registry import get_visualizer_registry

    manager = current_kb_manager()
    kb_names = manager.list_knowledge_bases()

    rows: list[dict[str, Any]] = []
    # An embedding model is dead weight until something needs to be indexed,
    # and load-bearing the moment a knowledge base exists.
    catalog_rows = catalog_service_rows(
        get_model_catalog_service().load(),
        required_services=REQUIRED_CATALOG_SERVICES | ({"embedding"} if kb_names else set()),
    )
    rows.extend(catalog_rows)

    runtime_service = get_runtime_settings_service()
    parsing = runtime_service.load_document_parsing(include_process_overrides=True)
    parser_entries = list_engines()
    parser_readiness: dict[str, dict[str, Any]] = {}
    selected_engine = str(parsing.get("engine") or "")
    selected_remote_reachable: bool | None = None
    for entry in parser_entries:
        engine_id = str(entry.get("id") or "")
        if not entry.get("available") and engine_id != selected_engine:
            continue
        try:
            parser = get_parser(engine_id)
            config = parser.resolve_config()
            # Docling Serve is a complete backend in remote mode and does not
            # require the local ``docling`` package.  The static engine catalog
            # reports local-package availability, so refine the selected row
            # with its effective mode before classifying it.
            if engine_id == selected_engine and bool(getattr(config, "is_remote", False)):
                entry["available"] = True
            report = parser.is_ready(config)
            parser_readiness[engine_id] = {
                "ready": bool(report.ready),
                "reason": str(report.reason or ""),
            }
            if engine_id == selected_engine and report.ready:
                selected_remote_reachable = await _selected_remote_parser_reachable(
                    engine_id, parser, config
                )
        except Exception:
            parser_readiness[engine_id] = {
                "ready": False,
                "reason": "parser_probe_failed",
            }
    rows.extend(
        document_parser_rows(
            parser_entries,
            selected_engine,
            parser_readiness,
            selected_remote_reachable=selected_remote_reachable,
        )
    )

    default_kb = manager.get_default()
    knowledge_entries: list[dict[str, Any]] = []
    for name in kb_names:
        try:
            info = manager.get_info(name, refresh_config=False, default_name=default_kb)
            metadata = info.get("metadata") if isinstance(info.get("metadata"), dict) else {}
            provider = str(metadata.get("rag_provider") or "")
            try:
                prerequisites_ready = bool(engine_preflight(provider).get("ok"))
            except Exception:
                prerequisites_ready = False
            knowledge_entries.append(
                {
                    "label": name,
                    "status": info.get("status"),
                    "needs_reindex": bool(metadata.get("needs_reindex")),
                    "prerequisites_ready": prerequisites_ready,
                }
            )
        except Exception:
            knowledge_entries.append(
                {
                    "label": name,
                    "status": "error",
                    "needs_reindex": False,
                    "prerequisites_ready": False,
                }
            )
    rows.extend(knowledge_base_rows(knowledge_entries))

    visualizers = visualizer_rows(
        get_visualizer_registry().public_catalog(),
        manim_available=_module_available("manim"),
    )
    rows.extend(visualizers)
    dependency_rows = {str(row["id"]): row for row in (*catalog_rows, *visualizers)}
    rows.extend(tool_rows(get_enabled_optional_tools(), dependency_rows))
    rows.extend(video_learning_rows(load_video_learning_settings()))

    integrations = runtime_service.load_integrations(include_process_overrides=True)
    system = runtime_service.load_system(include_process_overrides=True)
    coordination = (
        integrations.get("turn_coordination")
        if isinstance(integrations.get("turn_coordination"), dict)
        else {}
    )
    redis_url = str(coordination.get("redis_url") or "")
    runtime_rows, runtime_notices = coordination_rows(
        backend=str(coordination.get("backend") or "memory"),
        backend_workers=max(1, int(system.get("backend_workers") or 1)),
        redis_configured=bool(redis_url),
        redis_reachable=await _redis_reachable(redis_url),
    )
    rows.extend(runtime_rows)
    return readiness_snapshot(rows, extra_notices=runtime_notices)


__all__ = [
    "DETAIL_CODES",
    "TRANSLATABLE_ROW_LABELS",
    "PARSER_REPORT_REASONS",
    "READINESS_STATES",
    "REQUIRED_CATALOG_SERVICES",
    "SCHEMA_VERSION",
    "SEVERITIES",
    "USABLE_STATES",
    "build_settings_readiness",
    "catalog_service_rows",
    "coordination_rows",
    "document_parser_rows",
    "knowledge_base_rows",
    "readiness_row",
    "readiness_snapshot",
    "row_severity",
    "tool_rows",
    "video_learning_rows",
    "visualizer_rows",
]
