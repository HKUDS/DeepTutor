"""
CLI Config Command
==================

View and update DeepTutor configuration.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("providers")
    def config_providers() -> None:
        """List supported setup providers and their defaults as JSON."""
        import json

        from .setup_config import provider_options

        console.print_json(json.dumps(provider_options()))

    @app.command("apply")
    def config_apply(
        file: Path = typer.Argument(
            ..., help="Setup JSON file (see docs-for-user/AGENT_SETUP.md)."
        ),
        home: Path | None = typer.Option(None, "--home", help="Runtime workspace root."),
        check: bool = typer.Option(
            False, "--check", help="Validate without writing settings or contacting providers."
        ),
    ) -> None:
        """Apply LLM, embedding, search, and port configuration without prompts."""
        import json

        from pydantic import ValidationError

        from .setup_config import (
            SetupConfig,
            apply_setup,
            prepare_profiles,
            prepare_system,
            select_runtime_home,
        )

        try:
            config = SetupConfig.model_validate(json.loads(file.read_text(encoding="utf-8")))
            profiles = prepare_profiles(config)
            runtime_home = select_runtime_home(home)
            system = prepare_system(config)
            if not check:
                apply_setup(profiles, system)
        except ValidationError as exc:
            # Never include input values: a rejected literal api_key may be a secret.
            errors = [
                {"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
                for error in exc.errors(include_input=False, include_url=False)
            ]
            console.print_json(json.dumps({"ok": False, "errors": errors}))
            raise typer.Exit(code=2) from None
        except (OSError, ValueError) as exc:
            console.print_json(json.dumps({"ok": False, "error": str(exc)}))
            raise typer.Exit(code=2) from None

        console.print_json(
            json.dumps(
                {
                    "ok": True,
                    "status": "validated" if check else "applied",
                    "runtime_home": str(runtime_home),
                    "sections": [
                        name
                        for name in ("llm", "embedding", "search", "system")
                        if getattr(config, name) is not None
                    ],
                }
            )
        )

    @app.command("show")
    def config_show(
        home: Path | None = typer.Option(None, "--home", help="Runtime workspace root."),
    ) -> None:
        """Show current configuration."""
        import json

        if home is not None:
            from .setup_config import select_runtime_home

            select_runtime_home(home)

        from deeptutor.services.config import (
            load_config_with_main,
            load_system_settings,
            resolve_embedding_runtime_config,
            resolve_llm_runtime_config,
            resolve_search_runtime_config,
        )

        system_settings = load_system_settings()
        llm_runtime = resolve_llm_runtime_config()
        search_runtime = resolve_search_runtime_config()
        llm_info = {
            "binding_hint": llm_runtime.binding_hint,
            "provider": llm_runtime.provider_name,
            "provider_mode": llm_runtime.provider_mode,
            "model": llm_runtime.model,
            "base_url": llm_runtime.effective_url,
            "api_version": llm_runtime.api_version,
            "extra_headers": {name: "***" for name in llm_runtime.extra_headers},
            "api_key": "***" if llm_runtime.api_key else "(not set)",
        }
        try:
            embedding_runtime = resolve_embedding_runtime_config()
            embedding_info = {
                "status": "configured",
                "binding_hint": embedding_runtime.binding_hint,
                "provider": embedding_runtime.provider_name,
                "provider_mode": embedding_runtime.provider_mode,
                "model": embedding_runtime.model,
                "base_url": embedding_runtime.effective_url,
                "api_version": embedding_runtime.api_version,
                "extra_headers": {name: "***" for name in embedding_runtime.extra_headers},
                "api_key": "***" if embedding_runtime.api_key else "(not set)",
                "dimension": embedding_runtime.dimension,
            }
        except ValueError as exc:
            embedding_info = {
                "status": "not_configured",
                "message": str(exc),
            }

        try:
            main_cfg = load_config_with_main("main.yaml")
        except Exception:
            main_cfg = {}

        console.print_json(
            json.dumps(
                {
                    "ports": {
                        "backend": system_settings["backend_port"],
                        "frontend": system_settings["frontend_port"],
                    },
                    "llm": llm_info,
                    "embedding": embedding_info,
                    "search": {
                        "provider": search_runtime.provider or "(optional)",
                        "requested_provider": search_runtime.requested_provider or "(optional)",
                        "status": search_runtime.status,
                        "fallback_reason": search_runtime.fallback_reason,
                        "base_url": search_runtime.base_url,
                        "proxy": search_runtime.proxy,
                        "api_key": "***" if search_runtime.api_key else "(not set)",
                    },
                    "language": main_cfg.get("system", {}).get("language", "en"),
                    "tools": list(main_cfg.get("tools", {}).keys()),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
