"""Machine-readable description of what a DeepTutor install can be told to be.

Every knob the setup capability is allowed to change is one :class:`SettingSpec`
row here, and each row carries its own ``read`` / ``choices`` / ``write`` /
``probe``. That keeps the agent-facing tools
(:mod:`deeptutor.capabilities.setup.tools`) completely generic: they walk this
table instead of branching per setting, so a new knob becomes reachable by
adding a row — never by editing a tool, a prompt, or the API.

Rows derive their options from the modules that already own them (the parsing
engine registry, the model catalog, the search provider table), so this file
adds a *description* of the writable surface without becoming a second source
of truth for what a valid value is.

Three fields exist because changing a setting is not free:

``scope``
    ``personal`` rows live in the caller's own ``settings/interface.json``;
    ``global`` rows live in the shared deployment settings and are
    administrator-only. This mirrors where the files already are — a personal
    row is one that :class:`~deeptutor.services.path_service.PathService`
    already resolves per user, a global row is one read through
    :func:`~deeptutor.services.config.loader.get_runtime_settings_dir`.

``effect``
    What the user must still do for the change to take hold: ``instant``
    (nothing), ``restart`` (the value is only injected into subprocess env at
    launch), or ``reindex`` (derived data — embeddings — no longer matches the
    new setting). The setup agent is required to report this; keeping it as
    data rather than prompt etiquette is what makes that reliable.

``probe``
    An optional pre-commit connectivity check run against a *candidate*
    catalog that was never written to disk. Rows that can silently break the
    assistant's own next turn define one, and
    :func:`~deeptutor.capabilities.setup.apply.apply_setting` refuses to commit
    a value whose probe fails. Without it an agent could switch the chat model
    to something unreachable and take away its own power supply, leaving the
    user stranded mid-conversation with no way to ask for a fix.

Secrets are deliberately unrepresentable here: no row accepts an API key.
Credentials reach the server through the frontend's own card (see
``request_credential`` in the setup capability) so they never enter the model's
context, the conversation history, or the session transcript on disk.

Imports of the rest of DeepTutor are deferred into the row callables on
purpose: this module is imported from ``deeptutor.capabilities``, and a
top-level import of the model catalog or the parsing engines would close an
import cycle through ``services.config.__init__``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Scope = Literal["personal", "global"]
Effect = Literal["instant", "restart", "reindex"]

# Areas group rows for ``inspect_setup`` so the agent can ask about one part of
# the install ("what's my parsing set up like?") without reading everything.
Area = Literal["interface", "models", "parsing"]


@dataclass(frozen=True, slots=True)
class SettingChoice:
    """One selectable value, shaped so it can be rendered as an ask_user option.

    ``label`` / ``description`` map onto the ``{label, description}`` pair the
    ``ask_user`` card already renders, so a proposal never needs to reformat.
    ``available`` is False for a choice that is legal but not usable yet — a
    parsing engine whose package is not installed — which the setup agent turns
    into an install offer rather than hiding.
    """

    value: str
    label: str
    description: str = ""
    available: bool = True
    current: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a pre-commit connectivity check."""

    ok: bool
    detail: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One writable knob, self-contained enough that tools stay generic."""

    key: str
    area: Area
    scope: Scope
    effect: Effect
    label: str
    summary: str
    read: Callable[[], str]
    choices: Callable[[], tuple[SettingChoice, ...]]
    write: Callable[[str], None]
    # Optional extra validation beyond "the value is one of ``choices``".
    # Returns an error message, or None when the value is acceptable.
    validate: Callable[[str], str | None] | None = None
    # Pre-commit connectivity check against a candidate that is not on disk.
    probe: Callable[[str], Awaitable[ProbeResult]] | None = None
    # Human-readable consequence, surfaced verbatim by the agent alongside the
    # ``effect`` code so the user learns what they still have to do.
    effect_detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def current_choice(self) -> SettingChoice | None:
        current = self.read()
        for choice in self.choices():
            if choice.value == current:
                return choice
        return None


# --------------------------------------------------------------------------
# interface.json rows (personal scope)
# --------------------------------------------------------------------------

_LANGUAGE_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("en", "English", "Interface and replies in English."),
    ("zh", "简体中文", "Interface and replies in Simplified Chinese."),
)

_THEME_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("snow", "Default", "Pure-white neutral theme."),
    ("light", "Light", "Warm light theme."),
    ("dark", "Dark", "Dark theme."),
    ("glass", "Glass", "Translucent theme with blur."),
)


def _read_ui(key: str, default: str) -> Callable[[], str]:
    def _read() -> str:
        from deeptutor.services.settings.interface_settings import get_ui_settings

        value = get_ui_settings().get(key, default)
        return str(value or default)

    return _read


def _write_ui(key: str) -> Callable[[str], None]:
    def _write(value: str) -> None:
        from deeptutor.services.settings.interface_settings import set_ui_setting

        set_ui_setting(key, value)

    return _write


def _static_choices(
    rows: tuple[tuple[str, str, str], ...],
    current: Callable[[], str],
) -> Callable[[], tuple[SettingChoice, ...]]:
    def _choices() -> tuple[SettingChoice, ...]:
        active = current()
        return tuple(
            SettingChoice(value=value, label=label, description=desc, current=value == active)
            for value, label, desc in rows
        )

    return _choices


def _interface_specs() -> list[SettingSpec]:
    language_read = _read_ui("language", "en")
    response_read = _read_ui("response_language", "en")
    theme_read = _read_ui("theme", "snow")
    return [
        SettingSpec(
            key="interface.language",
            area="interface",
            scope="personal",
            effect="instant",
            label="Interface language",
            summary="Language of the DeepTutor UI (menus, buttons, settings).",
            read=language_read,
            choices=_static_choices(_LANGUAGE_CHOICES, language_read),
            write=_write_ui("language"),
        ),
        SettingSpec(
            key="interface.response_language",
            area="interface",
            scope="personal",
            effect="instant",
            label="Reply language",
            summary="Language the assistant writes its answers in.",
            read=response_read,
            choices=_static_choices(_LANGUAGE_CHOICES, response_read),
            write=_write_ui("response_language"),
            effect_detail="Applies from the next turn onwards.",
        ),
        SettingSpec(
            key="interface.theme",
            area="interface",
            scope="personal",
            effect="instant",
            label="Theme",
            summary="Visual theme of the web interface.",
            read=theme_read,
            choices=_static_choices(_THEME_CHOICES, theme_read),
            write=_write_ui("theme"),
        ),
    ]


# --------------------------------------------------------------------------
# document_parsing.json rows (global scope)
# --------------------------------------------------------------------------


def _read_parsing_engine() -> str:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service

    settings = get_runtime_settings_service().load_document_parsing()
    return str(settings.get("engine") or "text_only")


def _write_parsing_engine(value: str) -> None:
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service

    service = get_runtime_settings_service()
    settings = service.load_document_parsing()
    settings["engine"] = value
    service.save_document_parsing(settings)


def _parsing_engine_choices() -> tuple[SettingChoice, ...]:
    """Engine options, with availability answered by the engine registry itself.

    ``list_engines`` reports whether each engine's package actually imports, so
    an engine that merely *could* be installed still appears — the setup agent
    turns an unavailable choice into an install offer instead of pretending the
    engine does not exist.
    """
    from deeptutor.services.parsing.engines._install import installable_engines
    from deeptutor.services.parsing.engines.factory import list_engines

    active = _read_parsing_engine()
    installable = installable_engines()
    out: list[SettingChoice] = []
    for engine in list_engines():
        engine_id = str(engine.get("id") or "")
        if not engine_id:
            continue
        available = bool(engine.get("available"))
        description = str(engine.get("description") or "")
        if not available:
            description = (
                f"{description} Not installed yet"
                f"{'; can be installed in one step.' if engine_id in installable else '.'}"
            ).strip()
        out.append(
            SettingChoice(
                value=engine_id,
                label=str(engine.get("name") or engine_id),
                description=description,
                available=available,
                current=engine_id == active,
            )
        )
    return tuple(out)


def _validate_parsing_engine(value: str) -> str | None:
    from deeptutor.services.parsing.engines.factory import is_engine_available

    if is_engine_available(value):
        return None
    return (
        f"The '{value}' engine is not installed, so selecting it would break document "
        "parsing. Install it first with run_setup_job."
    )


def _parsing_specs() -> list[SettingSpec]:
    return [
        SettingSpec(
            key="document_parsing.engine",
            area="parsing",
            scope="global",
            effect="instant",
            label="Document parsing engine",
            summary=(
                "Which engine converts uploaded PDFs and Office files into text. "
                "Heavier engines read layout, tables and formulas more faithfully."
            ),
            read=_read_parsing_engine,
            choices=_parsing_engine_choices,
            write=_write_parsing_engine,
            validate=_validate_parsing_engine,
            effect_detail=(
                "Applies to documents parsed from now on; already-parsed documents keep "
                "their existing text until they are re-uploaded."
            ),
        )
    ]


# --------------------------------------------------------------------------
# model_catalog.json rows (global scope)
# --------------------------------------------------------------------------

# ``llm`` and ``embedding`` select a profile *and* a model, so their value is
# the composite below; ``search`` selects a profile alone.
_COMPOSITE_SEPARATOR = "::"


def _compose(profile_id: str, model_id: str) -> str:
    return f"{profile_id}{_COMPOSITE_SEPARATOR}{model_id}"


def _decompose(value: str) -> tuple[str, str]:
    profile_id, _, model_id = str(value or "").partition(_COMPOSITE_SEPARATOR)
    return profile_id, model_id


def _catalog_service():
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    return get_model_catalog_service()


def _read_catalog_model(service_name: str) -> Callable[[], str]:
    def _read() -> str:
        service = _catalog_service()
        catalog = service.load()
        profile = service.get_active_profile(catalog, service_name)
        model = service.get_active_model(catalog, service_name)
        if not profile:
            return ""
        return _compose(str(profile.get("id") or ""), str((model or {}).get("id") or ""))

    return _read


def _catalog_model_choices(service_name: str) -> Callable[[], tuple[SettingChoice, ...]]:
    def _choices() -> tuple[SettingChoice, ...]:
        service = _catalog_service()
        catalog = service.load()
        active = _read_catalog_model(service_name)()
        out: list[SettingChoice] = []
        for profile in catalog.get("services", {}).get(service_name, {}).get("profiles", []) or []:
            profile_id = str(profile.get("id") or "")
            profile_name = str(profile.get("name") or profile_id)
            binding = str(profile.get("binding") or "")
            for model in profile.get("models", []) or []:
                model_id = str(model.get("id") or "")
                value = _compose(profile_id, model_id)
                model_name = str(model.get("name") or model.get("model") or model_id)
                out.append(
                    SettingChoice(
                        value=value,
                        label=f"{model_name} · {profile_name}",
                        description=f"Served by {binding or 'an OpenAI-compatible endpoint'}.",
                        current=value == active,
                    )
                )
        return tuple(out)

    return _choices


def _write_catalog_model(service_name: str) -> Callable[[str], None]:
    def _write(value: str) -> None:
        profile_id, model_id = _decompose(value)

        def _mutate(catalog: dict[str, Any]) -> None:
            service = catalog.setdefault("services", {}).setdefault(service_name, {})
            service["active_profile_id"] = profile_id
            service["active_model_id"] = model_id

        _catalog_service().update(_mutate)
        _clear_runtime_caches()

    return _write


def _read_catalog_profile(service_name: str) -> Callable[[], str]:
    def _read() -> str:
        service = _catalog_service()
        profile = service.get_active_profile(service.load(), service_name)
        return str((profile or {}).get("id") or "")

    return _read


def _catalog_profile_choices(service_name: str) -> Callable[[], tuple[SettingChoice, ...]]:
    def _choices() -> tuple[SettingChoice, ...]:
        from deeptutor.services.config.provider_runtime import SEARCH_PROVIDERS

        service = _catalog_service()
        catalog = service.load()
        active = _read_catalog_profile(service_name)()
        out: list[SettingChoice] = []
        for profile in catalog.get("services", {}).get(service_name, {}).get("profiles", []) or []:
            profile_id = str(profile.get("id") or "")
            provider = str(profile.get("provider") or "")
            spec = SEARCH_PROVIDERS.get(provider)
            has_key = bool(str(profile.get("api_key") or "").strip())
            needs_key = bool(spec and spec.requires_api_key)
            description = f"{spec.label} provider." if spec else f"{provider} provider."
            if needs_key and not has_key:
                description += " No API key stored yet."
            out.append(
                SettingChoice(
                    value=profile_id,
                    label=str(profile.get("name") or provider or profile_id),
                    description=description,
                    available=not (needs_key and not has_key),
                    current=profile_id == active,
                )
            )
        return tuple(out)

    return _choices


def _write_catalog_profile(service_name: str) -> Callable[[str], None]:
    def _write(value: str) -> None:
        def _mutate(catalog: dict[str, Any]) -> None:
            service = catalog.setdefault("services", {}).setdefault(service_name, {})
            service["active_profile_id"] = value

        _catalog_service().update(_mutate)
        _clear_runtime_caches()

    return _write


def _clear_runtime_caches() -> None:
    """Drop resolved-config caches so a committed change takes effect at once.

    Without this the running process keeps answering from the config it
    resolved before the write, and the user is told the model changed while
    the next turn still runs on the old one.
    """
    try:
        from deeptutor.services.llm import clear_llm_config_cache

        clear_llm_config_cache()
    except Exception:  # noqa: BLE001 - best effort; a stale cache is not fatal
        pass


def _candidate_catalog(service_name: str, value: str, *, with_model: bool) -> dict[str, Any]:
    """Catalog as it *would* be, without writing anything to disk.

    ``resolve_*_runtime_config`` accepts an explicit catalog, which is what
    makes probe-before-commit possible: the candidate selection is resolved and
    exercised while the stored configuration is still untouched.
    """
    from copy import deepcopy

    catalog = deepcopy(_catalog_service().load())
    service = catalog.setdefault("services", {}).setdefault(service_name, {})
    if with_model:
        profile_id, model_id = _decompose(value)
        service["active_profile_id"] = profile_id
        service["active_model_id"] = model_id
    else:
        service["active_profile_id"] = value
    return catalog


# A probe runs inside a live chat turn, with the user waiting on it, so it is
# bounded far more tightly than an ordinary model call. The runtime's own
# defaults are wrong here in both directions: ``max_retries`` is 8 with a 5s
# base delay, and each attempt carries a 120s transport timeout, so an endpoint
# that accepts the connection and then hangs would keep the turn — and the whole
# conversation — waiting sixteen minutes before reporting a failure the user
# could have been told about in twenty seconds. One attempt, hard deadline.
_PROBE_TIMEOUT_SECONDS = 25.0
_PROBE_MAX_RETRIES = 0


def _timed_out(started: float) -> ProbeResult:
    import time

    return ProbeResult(
        ok=False,
        detail=(
            f"No response within {int(_PROBE_TIMEOUT_SECONDS)}s. The endpoint may be "
            "unreachable from this machine, or the address may be wrong."
        ),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


async def _probe_llm(value: str) -> ProbeResult:
    """Smallest real completion against the candidate selection."""
    import asyncio
    import time

    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.llm import complete as llm_complete
    from deeptutor.services.llm import get_token_limit_kwargs

    started = time.monotonic()
    try:
        resolved = resolve_llm_runtime_config(
            catalog=_candidate_catalog("llm", value, with_model=True)
        )
        if not resolved.model:
            return ProbeResult(ok=False, detail="No model resolved from that selection.")
        await asyncio.wait_for(
            llm_complete(
                model=resolved.model,
                prompt="ping",
                system_prompt="Reply with the single word OK.",
                binding=resolved.binding,
                api_key=resolved.api_key or "sk-no-key-required",
                base_url=resolved.effective_url or resolved.base_url or "",
                api_version=resolved.api_version,
                temperature=0.0,
                extra_headers=resolved.extra_headers,
                reasoning_effort=resolved.reasoning_effort,
                max_retries=_PROBE_MAX_RETRIES,
                **get_token_limit_kwargs(resolved.model, max_tokens=64),  # type: ignore[arg-type]
            ),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return _timed_out(started)
    except Exception as exc:  # noqa: BLE001 - any failure means "do not commit"
        return ProbeResult(
            ok=False,
            detail=_redact(str(exc))[:300],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    # An empty completion is deliberately accepted: the probe verifies that the
    # endpoint and credentials work, not that the model is talkative. A
    # reasoning model can legitimately spend the whole 64-token budget thinking.
    return ProbeResult(ok=True, elapsed_ms=int((time.monotonic() - started) * 1000))


async def _probe_embedding(value: str) -> ProbeResult:
    """Embed one short string with the candidate selection."""
    import asyncio
    import time

    from deeptutor.services.config.provider_runtime import resolve_embedding_runtime_config
    from deeptutor.services.embedding.client import EmbeddingClient
    from deeptutor.services.embedding.config import EmbeddingConfig

    started = time.monotonic()
    try:
        resolved = resolve_embedding_runtime_config(
            catalog=_candidate_catalog("embedding", value, with_model=True)
        )
        if not resolved.model:
            return ProbeResult(ok=False, detail="No embedding model resolved from that selection.")
        # ``dim=0`` / ``send_dimensions=False`` mirror the settings smoke test:
        # sending no ``dimensions=`` parameter keeps Matryoshka models from
        # simply echoing back whatever width we asked for.
        client = EmbeddingClient(
            EmbeddingConfig(
                model=resolved.model,
                api_key=resolved.api_key,
                base_url=resolved.base_url,
                effective_url=resolved.effective_url,
                binding=resolved.binding,
                provider_name=resolved.provider_name,
                provider_mode=resolved.provider_mode,
                api_version=resolved.api_version,
                extra_headers=resolved.extra_headers,
                dim=0,
                send_dimensions=False,
                # Clamped to the probe budget rather than the configured
                # timeout, which is sized for indexing a whole corpus.
                request_timeout=max(1, min(resolved.request_timeout, int(_PROBE_TIMEOUT_SECONDS))),
                batch_size=max(1, resolved.batch_size),
                batch_delay=max(0.0, resolved.batch_delay),
            )
        )
        vectors = await asyncio.wait_for(client.embed(["ping"]), timeout=_PROBE_TIMEOUT_SECONDS)
        if not vectors or not vectors[0]:
            return ProbeResult(ok=False, detail="The endpoint returned an empty embedding.")
    except (TimeoutError, asyncio.TimeoutError):
        return _timed_out(started)
    except Exception as exc:  # noqa: BLE001 - any failure means "do not commit"
        return ProbeResult(
            ok=False,
            detail=_redact(str(exc))[:300],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    return ProbeResult(ok=True, elapsed_ms=int((time.monotonic() - started) * 1000))


def _redact(text: str) -> str:
    """Strip anything that looks like a bearer token out of an error string.

    Provider errors often echo the request headers back. The setup agent puts
    probe failures in front of the model verbatim so it can explain them, so
    this is the boundary where a leaked key would enter the context.
    """
    import re

    redacted = re.sub(r"(sk-|Bearer\s+)[A-Za-z0-9_\-]{8,}", r"\1***", text)
    return re.sub(r"[A-Za-z0-9_\-]{32,}", "***", redacted)


def _catalog_specs() -> list[SettingSpec]:
    return [
        SettingSpec(
            key="catalog.llm",
            area="models",
            scope="global",
            effect="instant",
            label="Chat model",
            summary="The language model that answers in chat and drives every capability.",
            read=_read_catalog_model("llm"),
            choices=_catalog_model_choices("llm"),
            write=_write_catalog_model("llm"),
            probe=_probe_llm,
            effect_detail="Applies from the next turn onwards.",
        ),
        SettingSpec(
            key="catalog.embedding",
            area="models",
            scope="global",
            effect="reindex",
            label="Embedding model",
            summary="The model that turns documents into vectors for knowledge-base search.",
            read=_read_catalog_model("embedding"),
            choices=_catalog_model_choices("embedding"),
            write=_write_catalog_model("embedding"),
            probe=_probe_embedding,
            effect_detail=(
                "Existing knowledge bases were indexed with the previous model and must be "
                "rebuilt before they can be searched again — vectors from two different "
                "models are not comparable."
            ),
        ),
        SettingSpec(
            key="catalog.search",
            area="models",
            scope="global",
            effect="instant",
            label="Web search provider",
            summary="Which service answers web_search calls.",
            read=_read_catalog_profile("search"),
            choices=_catalog_profile_choices("search"),
            write=_write_catalog_profile("search"),
            effect_detail="Applies from the next search onwards.",
        ),
    ]


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def setting_specs() -> dict[str, SettingSpec]:
    """All writable rows, keyed by ``key``, in stable presentation order.

    Built per call rather than at import time: every row closes over deferred
    imports, and building lazily keeps this module importable from
    ``deeptutor.capabilities`` without closing an import cycle.
    """
    rows = [*_interface_specs(), *_parsing_specs(), *_catalog_specs()]
    return {spec.key: spec for spec in rows}


def get_setting_spec(key: str) -> SettingSpec | None:
    return setting_specs().get(str(key or "").strip())


def specs_for_area(area: str) -> tuple[SettingSpec, ...]:
    wanted = str(area or "").strip().lower()
    return tuple(spec for spec in setting_specs().values() if not wanted or spec.area == wanted)


SETTING_AREAS: tuple[str, ...] = ("interface", "models", "parsing")

__all__ = [
    "SETTING_AREAS",
    "Area",
    "Effect",
    "ProbeResult",
    "Scope",
    "SettingChoice",
    "SettingSpec",
    "get_setting_spec",
    "setting_specs",
    "specs_for_area",
]
