"""``api_format`` on LLM-shaped profiles and per-model capability overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService


def _service(tmp_path: Path) -> ModelCatalogService:
    return ModelCatalogService(path=tmp_path / "model_catalog.json")


def _saved_profiles(tmp_path: Path, profiles: list[dict[str, Any]], service: str = "llm"):
    catalog_service = _service(tmp_path)
    catalog = catalog_service.load()
    catalog["services"][service]["profiles"] = profiles
    saved = catalog_service.save(catalog)
    return {profile["id"]: profile for profile in saved["services"][service]["profiles"]}


def test_legacy_fields_derive_api_format_without_touching_binding(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [
            {"id": "a", "binding": "custom_anthropic", "wire_api": "auto", "models": []},
            {"id": "b", "binding": "custom", "wire_api": "responses", "models": []},
            {"id": "c", "binding": "custom", "wire_api": "chat_completions", "models": []},
            {"id": "d", "binding": "openai", "models": []},
            {"id": "e", "binding": "minimax_anthropic", "models": []},
        ],
    )
    assert saved["a"]["binding"] == "custom_anthropic"
    assert saved["a"]["api_format"] == "anthropic"
    assert saved["a"]["wire_api"] == "auto"
    assert (saved["b"]["api_format"], saved["b"]["wire_api"]) == ("openai_responses", "responses")
    assert (saved["c"]["api_format"], saved["c"]["wire_api"]) == ("openai_chat", "chat_completions")
    assert (saved["d"]["api_format"], saved["d"]["wire_api"]) == ("auto", "auto")
    assert saved["e"]["binding"] == "minimax_anthropic"
    assert saved["e"]["api_format"] == "anthropic"


def test_explicit_api_format_drives_wire_api(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [
            # A stale wire_api loses to the explicit format.
            {"id": "a", "binding": "minimax", "api_format": "anthropic", "wire_api": "responses"},
            {"id": "b", "binding": "custom", "api_format": "openai_chat"},
            {"id": "c", "binding": "custom", "api_format": "openai_responses", "wire_api": "auto"},
        ],
    )
    assert (saved["a"]["api_format"], saved["a"]["wire_api"]) == ("anthropic", "auto")
    assert (saved["b"]["api_format"], saved["b"]["wire_api"]) == ("openai_chat", "chat_completions")
    assert (saved["c"]["api_format"], saved["c"]["wire_api"]) == ("openai_responses", "responses")


def test_api_format_is_clamped_to_the_provider(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [
            {"id": "a", "binding": "openai", "api_format": "anthropic"},
            {"id": "b", "binding": "anthropic", "api_format": "openai_responses"},
            {"id": "c", "binding": "azure_openai", "api_format": "openai_responses"},
            {"id": "d", "binding": "custom", "api_format": "bogus"},
        ],
    )
    assert (saved["a"]["api_format"], saved["a"]["wire_api"]) == ("auto", "auto")
    assert (saved["b"]["api_format"], saved["b"]["wire_api"]) == ("anthropic", "auto")
    assert (saved["c"]["api_format"], saved["c"]["wire_api"]) == ("auto", "auto")
    assert saved["d"]["api_format"] == "auto"


def test_task_profiles_carry_an_api_format_too(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [{"id": "t", "binding": "custom", "wire_api": "responses", "models": []}],
        service="task",
    )
    assert (saved["t"]["api_format"], saved["t"]["wire_api"]) == ("openai_responses", "responses")


def test_embedding_profiles_are_left_alone(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [{"id": "e", "binding": "openai", "base_url": "https://api.openai.com/v1/embeddings"}],
        service="embedding",
    )
    assert "api_format" not in saved["e"]


def test_model_capabilities_keep_only_explicit_booleans(tmp_path: Path) -> None:
    saved = _saved_profiles(
        tmp_path,
        [
            {
                "id": "p",
                "binding": "custom",
                "models": [
                    {
                        "id": "m1",
                        "model": "x",
                        "capabilities": {"tools": True, "vision": "yes", "bogus": False},
                    },
                    {"id": "m2", "model": "y", "capabilities": {}},
                    {"id": "m3", "model": "z", "capabilities": "tools"},
                    {"id": "m4", "model": "w"},
                ],
            }
        ],
    )
    models = {model["id"]: model for model in saved["p"]["models"]}
    assert models["m1"]["capabilities"] == {"tools": True}
    assert "capabilities" not in models["m2"]
    assert "capabilities" not in models["m3"]
    assert "capabilities" not in models["m4"]


def test_normalization_is_idempotent(tmp_path: Path) -> None:
    catalog_service = _service(tmp_path)
    catalog = catalog_service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "a",
            "binding": "custom_anthropic",
            "models": [{"id": "m", "model": "x", "capabilities": {"tools": False}}],
        }
    ]
    first = catalog_service.save(catalog)
    second = catalog_service.save(first)
    assert first == second
