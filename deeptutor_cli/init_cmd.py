"""Interactive runtime settings initializer.

``deeptutor init`` walks the user through a four-step wizard (ports → LLM →
embedding → review) that writes the same files as the Web Settings page.

Heavy lifting (provider menu, live ``/models`` fetch, connectivity probe,
review panel) lives in :mod:`deeptutor_cli.init_wizard`. This module is
intentionally thin so the order of steps is easy to read top-to-bottom.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer

from deeptutor.runtime.home import DEEPTUTOR_HOME_ENV, get_runtime_home

from . import init_wizard as wiz


def _reset_runtime_singletons() -> None:
    """Drop cached service instances so the new DEEPTUTOR_HOME takes effect.

    ``deeptutor init`` may pass ``--home`` to target a different workspace; the
    singletons cache paths from the *previous* PathService and will silently
    write to the wrong place if not cleared.
    """
    try:
        from deeptutor.services.path_service import PathService

        PathService.reset_instance()
    except Exception:
        pass
    try:
        from deeptutor.services.config.runtime_settings import RuntimeSettingsService

        RuntimeSettingsService._instances.clear()
    except Exception:
        pass
    try:
        from deeptutor.services.config.model_catalog import ModelCatalogService

        ModelCatalogService._instances.clear()
    except Exception:
        pass


def _ensure_model_service(catalog: dict, service_name: str, profile_id: str, model_id: str):
    """Locate or create the default profile + model rows we'll mutate in place."""
    services = catalog.setdefault("services", {})
    service = services.setdefault(
        service_name,
        {"active_profile_id": profile_id, "active_model_id": model_id, "profiles": []},
    )
    profiles = service.setdefault("profiles", [])
    profile = next(
        (item for item in profiles if item.get("id") == service.get("active_profile_id")), None
    )
    if profile is None:
        profile = {
            "id": profile_id,
            "name": "Default LLM Endpoint"
            if service_name == "llm"
            else "Default Embedding Endpoint",
            "binding": "openai",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [],
        }
        profiles.append(profile)
        service["active_profile_id"] = profile_id
    models = profile.setdefault("models", [])
    model = next(
        (item for item in models if item.get("id") == service.get("active_model_id")), None
    )
    if model is None:
        model = {"id": model_id, "name": "Default Model", "model": ""}
        models.append(model)
        service["active_model_id"] = model_id
    return profile, model


def _llm_step(
    console: Console,
    strings: dict,
    current_profile: dict,
    current_model: dict,
) -> wiz.LLMChoice:
    spec = wiz.select_llm_provider(
        console,
        strings,
        current_binding=str(current_profile.get("binding") or "openai"),
    )

    if spec is not None:
        binding = spec.name
        default_base = spec.default_api_base or str(current_profile.get("base_url") or "")
        display_provider = spec.label
        env_key = spec.env_key
    else:
        binding = (
            typer.prompt(
                strings["init.binding"],
                default=str(current_profile.get("binding") or "openai"),
            ).strip()
            or "openai"
        )
        default_base = str(current_profile.get("base_url") or "")
        display_provider = "Custom"
        env_key = ""

    edit_base = typer.confirm(strings["init.edit_base_url"], default=not bool(default_base))
    if edit_base:
        base_url = typer.prompt(strings["init.new_base_url"], default=default_base or "")
    else:
        base_url = default_base
        wiz.info(console, f"Base URL · {base_url or '(empty)'}")

    api_key = wiz.capture_api_key(
        console,
        strings,
        env_key=env_key,
        current=str(current_profile.get("api_key") or ""),
    )

    models = wiz.fetch_models(
        console,
        strings,
        base_url=base_url,
        api_key=api_key,
        binding=binding,
    )
    if not models:
        models = list(wiz.LLM_FALLBACK_MODELS.get(binding, ()))

    model = wiz.select_model(
        console,
        strings,
        models=models,
        current=str(current_model.get("model") or ""),
    )

    choice = wiz.LLMChoice(
        binding=binding,
        base_url=base_url,
        api_key=api_key,
        model=model,
        display_provider=display_provider,
    )

    if typer.confirm(strings["init.probe_offer"], default=True):
        _probe_llm_with_retry(console, strings, choice)

    return choice


def _probe_llm_with_retry(console: Console, strings: dict, choice: wiz.LLMChoice) -> None:
    """Run the probe; on failure, offer a single retry with a fresh API key."""
    while True:
        wiz.info(console, strings["init.probe_running"].format(what=choice.display_provider))
        ok_result, elapsed_ms, error = wiz.probe_llm(
            base_url=choice.base_url,
            api_key=choice.api_key,
            binding=choice.binding,
            model=choice.model,
        )
        choice.probed = True
        choice.probe_ok = ok_result
        choice.probe_ms = elapsed_ms
        if ok_result:
            wiz.ok(
                console,
                strings["init.probe_ok"].format(what=choice.display_provider, ms=elapsed_ms),
            )
            return
        wiz.fail(
            console, strings["init.probe_fail"].format(what=choice.display_provider, error=error)
        )
        if not typer.confirm(strings["init.probe_retry"], default=False):
            return
        choice.api_key = typer.prompt(
            strings["init.api_key_prompt"], default="", hide_input=True, show_default=False
        )


def _embedding_step(
    console: Console,
    strings: dict,
    catalog: dict,
    llm_api_key: str,
) -> wiz.EmbeddingChoice | None:
    """Returns ``None`` when the user picks ``[s] Skip``."""

    from deeptutor.services.config.embedding_endpoint import (
        EMBEDDING_PROVIDER_LABELS,
        normalize_embedding_endpoint_for_display,
    )
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

    current_profile = (catalog.get("services", {}).get("embedding", {}).get("profiles") or [{}])[
        0
    ] or {}
    current_binding = str(current_profile.get("binding") or "openai")

    provider_pick = wiz.select_embedding_provider(console, strings, current=current_binding)
    if provider_pick == wiz.SKIP_SENTINEL:
        wiz.info(console, strings["init.skipped"])
        return None
    if provider_pick is None:
        provider = typer.prompt(strings["init.binding"], default=current_binding or "openai")
    else:
        provider = provider_pick

    spec = EMBEDDING_PROVIDERS.get(provider)
    display_provider = (
        spec.label if spec else EMBEDDING_PROVIDER_LABELS.get(provider, provider.title())
    )
    default_endpoint = spec.default_api_base if spec else str(current_profile.get("base_url") or "")

    edit_endpoint = typer.confirm(strings["init.edit_base_url"], default=not bool(default_endpoint))
    endpoint = (
        typer.prompt(strings["init.embedding_endpoint"], default=default_endpoint)
        if edit_endpoint
        else default_endpoint
    )
    endpoint = normalize_embedding_endpoint_for_display(provider, endpoint)
    if not edit_endpoint:
        wiz.info(console, f"Endpoint · {endpoint or '(empty)'}")

    # Reuse the LLM key by default — most users share creds across services.
    masked = wiz._mask_secret(llm_api_key)
    if llm_api_key and typer.confirm(
        strings["init.api_key_reuse_llm"].format(masked=masked), default=True
    ):
        api_key = llm_api_key
    else:
        api_key = typer.prompt(
            strings["init.embedding_api_key"], default="", hide_input=True, show_default=False
        )

    # Try live ``/models`` first; fall back to the curated list (spec default
    # first, then EMBEDDING_FALLBACK_MODELS) when the fetch returns nothing.
    models = wiz.fetch_embedding_models(
        console, strings, endpoint=endpoint, api_key=api_key, provider=provider
    )
    if not models:
        models = list(wiz.EMBEDDING_FALLBACK_MODELS.get(provider, ()))
        if spec and spec.default_model and spec.default_model not in models:
            models = [spec.default_model] + models
    model = wiz.select_model(
        console,
        strings,
        models=models,
        current=str((current_profile.get("models") or [{}])[0].get("model") or ""),
        custom_prompt_label=strings["init.embedding_model"],
    )
    dimension = typer.prompt(strings["init.embedding_dimension"], default="")

    choice = wiz.EmbeddingChoice(
        binding=provider,
        base_url=endpoint,
        api_key=api_key,
        model=model,
        dimension=str(dimension or "").strip(),
        display_provider=display_provider,
    )

    if typer.confirm(strings["init.probe_offer"], default=True):
        wiz.info(console, strings["init.probe_running"].format(what=display_provider))
        ok_result, elapsed_ms, error = wiz.probe_embedding(
            base_url=choice.base_url, api_key=choice.api_key, model=choice.model
        )
        choice.probed = True
        choice.probe_ok = ok_result
        choice.probe_ms = elapsed_ms
        if ok_result:
            wiz.ok(console, strings["init.probe_ok"].format(what=display_provider, ms=elapsed_ms))
        else:
            wiz.fail(console, strings["init.probe_fail"].format(what=display_provider, error=error))

    return choice


def _search_step(
    console: Console,
    strings: dict,
    catalog: dict,
) -> wiz.SearchChoice | None:
    """Returns ``None`` when the user picks ``[s] Skip``.

    A ``provider == "none"`` result is NOT skip — it's "explicitly disable
    web search". We still write that into the catalog so agents stop trying.
    """

    current_profile = (catalog.get("services", {}).get("search", {}).get("profiles") or [{}])[
        0
    ] or {}
    current_provider = str(current_profile.get("provider") or "tavily")

    spec = wiz.select_search_provider(console, strings, current=current_provider)
    if spec is None:
        wiz.info(console, strings["init.skipped"])
        return None

    if spec.name == "none":
        wiz.info(console, strings["init.search_disabled_note"])
        return wiz.SearchChoice(provider="none", label=spec.label)

    api_key = ""
    if spec.requires_api_key:
        env_key, env_name = wiz.search_api_key_from_env(spec.env_keys)
        if env_key:
            masked = wiz._mask_secret(env_key)
            offer = strings["init.api_key_env_detected"].format(env_var=env_name, masked=masked)
            if typer.confirm(offer, default=True):
                api_key = env_key
        if not api_key:
            current_key = str(current_profile.get("api_key") or "")
            if current_key:
                masked = wiz._mask_secret(current_key)
                if typer.confirm(
                    strings["init.api_key_reuse_llm"].format(masked=masked), default=True
                ):
                    api_key = current_key
        if not api_key:
            api_key = typer.prompt(
                strings["init.search_api_key_prompt"],
                default="",
                hide_input=True,
                show_default=False,
            )
    else:
        wiz.info(console, strings["init.search_no_key_note"].format(label=spec.label))

    base_url = ""
    if spec.requires_base_url:
        default_url = str(current_profile.get("base_url") or "") or spec.default_base_url
        base_url = typer.prompt(strings["init.search_base_url_prompt"], default=default_url)

    return wiz.SearchChoice(
        provider=spec.name,
        label=spec.label,
        api_key=api_key,
        base_url=base_url,
    )


def _ensure_search_service(catalog: dict, profile_id: str) -> dict:
    """Locate or create the default search profile we'll mutate in place."""
    services = catalog.setdefault("services", {})
    service = services.setdefault(
        "search",
        {"active_profile_id": profile_id, "profiles": []},
    )
    profiles = service.setdefault("profiles", [])
    profile = next(
        (item for item in profiles if item.get("id") == service.get("active_profile_id")), None
    )
    if profile is None:
        profile = {
            "id": profile_id,
            "name": "Default Search",
            "provider": "brave",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "proxy": "",
            "models": [],
        }
        profiles.append(profile)
        service["active_profile_id"] = profile_id
    return profile


def run_init(*, cli_only: bool = False, home: str | Path | None = None) -> None:
    runtime_home = get_runtime_home(home)
    runtime_home.mkdir(parents=True, exist_ok=True)
    import os

    os.environ[DEEPTUTOR_HOME_ENV] = str(runtime_home)
    _reset_runtime_singletons()

    from deeptutor.runtime.banner import labels_for, print_banner, resolve_language
    from deeptutor.services.config import get_model_catalog_service, get_runtime_settings_service
    from deeptutor.services.setup import init_user_directories

    init_user_directories(runtime_home)

    language = resolve_language()
    strings = labels_for(language)
    console = Console()
    # CLI-only: LLM, Embedding, Search, Review = 4 steps.
    # Full:     Ports, LLM, Embedding, Search, Review = 5 steps.
    total_steps = 4 if cli_only else 5

    try:
        print_banner(console, language=language, mode_key="init.mode")
        console.print(f"{strings['init.workspace']}: [bold]{runtime_home}[/bold]")
        console.print(f"[dim]{strings['init.note_settings_dir']}[/dim]")

        runtime = get_runtime_settings_service()
        system = runtime.load_system(include_process_overrides=False)

        # --- Step 1 (CLI mode skips ports) ---
        step_num = 0
        if not cli_only:
            step_num += 1
            wiz.step_header(
                console,
                strings["init.step_ports"].format(n=step_num, total=total_steps),
            )
            system["backend_port"] = int(
                typer.prompt(
                    strings["init.backend_port"],
                    default=str(system.get("backend_port") or 8001),
                )
            )
            system["frontend_port"] = int(
                typer.prompt(
                    strings["init.frontend_port"],
                    default=str(system.get("frontend_port") or 3782),
                )
            )

        # --- Step 2: LLM ---
        catalog_service = get_model_catalog_service()
        catalog = catalog_service.load()
        llm_profile, llm_model = _ensure_model_service(
            catalog, "llm", "llm-profile-default", "llm-model-default"
        )
        step_num += 1
        wiz.step_header(console, strings["init.step_llm"].format(n=step_num, total=total_steps))
        llm_choice = _llm_step(console, strings, llm_profile, llm_model)

        # Apply LLM choice back into the catalog draft.
        llm_profile["binding"] = llm_choice.binding
        llm_profile["base_url"] = llm_choice.base_url
        llm_profile["api_key"] = llm_choice.api_key
        llm_model["model"] = llm_choice.model
        llm_model["name"] = llm_choice.model or "Default Model"

        # --- Step 3: Embedding (skip via [s] inside the picker) ---
        embedding_choice: wiz.EmbeddingChoice | None = None
        step_num += 1
        wiz.step_header(
            console, strings["init.step_embedding"].format(n=step_num, total=total_steps)
        )
        embedding_choice = _embedding_step(console, strings, catalog, llm_choice.api_key)
        if embedding_choice is not None:
            emb_profile, emb_model = _ensure_model_service(
                catalog,
                "embedding",
                "embedding-profile-default",
                "embedding-model-default",
            )
            emb_profile["binding"] = embedding_choice.binding
            emb_profile["base_url"] = embedding_choice.base_url
            emb_profile["api_key"] = embedding_choice.api_key
            emb_model["model"] = embedding_choice.model
            emb_model["name"] = embedding_choice.model or "Default Embedding Model"
            if embedding_choice.dimension:
                emb_model["dimension"] = embedding_choice.dimension

        # --- Step 4: Search (skip via [s] inside the picker) ---
        search_choice: wiz.SearchChoice | None = None
        step_num += 1
        wiz.step_header(console, strings["init.step_search"].format(n=step_num, total=total_steps))
        search_choice = _search_step(console, strings, catalog)
        if search_choice is not None:
            search_profile = _ensure_search_service(catalog, "search-profile-default")
            search_profile["provider"] = search_choice.provider
            search_profile["api_key"] = search_choice.api_key
            search_profile["base_url"] = search_choice.base_url

        # --- Step 5: Review & save ---
        step_num += 1
        wiz.step_header(console, strings["init.step_review"].format(n=step_num, total=total_steps))
        wiz.render_review_panel(
            console,
            strings,
            llm=llm_choice,
            embedding=embedding_choice,
            search=search_choice,
            backend_port=None if cli_only else system.get("backend_port"),
            frontend_port=None if cli_only else system.get("frontend_port"),
        )
        if not typer.confirm(strings["init.confirm_save"], default=True):
            wiz.warn(console, strings["init.cancelled"])
            raise typer.Exit(code=1)

        if not cli_only:
            runtime.save_system(system)
        catalog_service.save(catalog)
        console.print()
        wiz.ok(console, strings["init.saved"])
        console.print(f"[dim]{strings['init.next_step']}[/dim]")

    except (KeyboardInterrupt, typer.Abort):
        console.print()
        wiz.warn(console, strings["init.cancelled"])
        raise typer.Exit(code=130)


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init_command(
        cli: bool = typer.Option(False, "--cli", help="Initialize for CLI-only use."),
        home: Path | None = typer.Option(None, "--home", help="Runtime workspace root."),
    ) -> None:
        """Create or update data/user/settings for this workspace."""

        run_init(cli_only=cli, home=home)
