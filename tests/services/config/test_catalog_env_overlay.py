"""Regression: project-root .env must not overlay model catalog profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService


def _write_env(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def isolated_stores(tmp_path: Path) -> tuple[Path, Path]:
    catalog_path = tmp_path / "model_catalog.json"
    env_path = tmp_path / ".env"
    ModelCatalogService._instances.clear()
    return catalog_path, env_path


def test_user_added_second_profile_survives_reload(
    isolated_stores: tuple[Path, Path],
) -> None:
    catalog_path, env_path = isolated_stores
    # Env reflects the previous "Default" profile values.
    _write_env(
        env_path,
        [
            "EMBEDDING_BINDING=openai",
            "EMBEDDING_MODEL=text-embedding-3-large",
            "EMBEDDING_HOST=https://openrouter.ai/api/v1",
            "EMBEDDING_API_KEY=sk-default",
            "EMBEDDING_DIMENSION=",
        ],
    )

    # Simulate user state after Save Draft on a 2-profile catalog where the
    # user added "aliyun" with a DashScope URL.
    user_catalog: dict[str, Any] = {
        "services": {
            "llm": {
                "active_profile_id": "llm-profile-default",
                "active_model_id": "llm-model-default",
                "profiles": [
                    {
                        "id": "llm-profile-default",
                        "name": "Default LLM Endpoint",
                        "binding": "openai",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-llm",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [{"id": "llm-model-default", "name": "m", "model": "gpt"}],
                    }
                ],
            },
            "embedding": {
                # User-managed: 2 profiles, aliyun is active.
                "active_profile_id": "embedding-profile-1700000000",
                "active_model_id": "embedding-model-1700000000",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-default",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": "m",
                                "model": "text-embedding-3-large",
                                "dimension": "",
                            }
                        ],
                    },
                    {
                        "id": "embedding-profile-1700000000",
                        "name": "aliyun",
                        "binding": "aliyun",
                        # User typed the DashScope URL & key.
                        "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                        "api_key": "sk-dashscope",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-1700000000",
                                "name": "qwen3-vl-embedding",
                                "model": "qwen3-vl-embedding",
                                "dimension": "",
                            }
                        ],
                    },
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        }
    }
    catalog_path.write_text(json.dumps(user_catalog))

    service = ModelCatalogService(catalog_path)
    loaded = service.load()

    embedding_service = loaded["services"]["embedding"]
    aliyun = next(
        p for p in embedding_service["profiles"] if p["id"] == "embedding-profile-1700000000"
    )
    # The bug: env's openrouter URL was overlaying aliyun's DashScope URL.
    assert aliyun["base_url"].startswith("https://dashscope.aliyuncs.com/")
    assert aliyun["api_key"] == "sk-dashscope"
    assert aliyun["binding"] == "aliyun"
    # And the second profile is still there (not collapsed into a single one).
    assert len(embedding_service["profiles"]) == 2


def test_legacy_env_does_not_overlay_existing_single_default_profile(
    isolated_stores: tuple[Path, Path],
) -> None:
    """Once model_catalog.json exists, it is the source of truth."""
    catalog_path, env_path = isolated_stores

    _write_env(
        env_path,
        [
            "EMBEDDING_BINDING=openai",
            "EMBEDDING_MODEL=text-embedding-3-small",
            "EMBEDDING_HOST=https://api.openai.com/v1/embeddings",
            "EMBEDDING_API_KEY=sk-newkey",
        ],
    )

    pristine_catalog: dict[str, Any] = {
        "services": {
            "llm": {"active_profile_id": None, "profiles": []},
            "embedding": {
                "active_profile_id": "embedding-profile-default",
                "active_model_id": "embedding-model-default",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "stale-old-value",
                        "api_key": "stale-old-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": "stale",
                                "model": "stale-model",
                                "dimension": "",
                            }
                        ],
                    }
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        }
    }
    catalog_path.write_text(json.dumps(pristine_catalog))

    service = ModelCatalogService(catalog_path)
    loaded = service.load()

    profile = loaded["services"]["embedding"]["profiles"][0]
    assert profile["base_url"] == "stale-old-value"
    assert profile["api_key"] == "stale-old-key"
    assert profile["models"][0]["model"] == "stale-model"


def _write_single_embedding_profile_catalog(
    catalog_path: Path,
    *,
    binding: str,
    base_url: str,
) -> None:
    catalog_path.write_text(
        json.dumps(
            {
                "services": {
                    "llm": {"active_profile_id": None, "profiles": []},
                    "embedding": {
                        "active_profile_id": "embedding-profile-default",
                        "active_model_id": "embedding-model-default",
                        "profiles": [
                            {
                                "id": "embedding-profile-default",
                                "name": "Embedding",
                                "binding": binding,
                                "base_url": base_url,
                                "api_key": "sk-test",
                                "api_version": "",
                                "extra_headers": {},
                                "models": [
                                    {
                                        "id": "embedding-model-default",
                                        "name": "m",
                                        "model": "qwen/qwen3-embedding-8b",
                                    }
                                ],
                            }
                        ],
                    },
                    "search": {"active_profile_id": None, "profiles": []},
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("binding", "base_url", "expected"),
    [
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            "https://openrouter.ai/api/v1/embeddings",
        ),
        ("ollama", "http://localhost:11434", "http://localhost:11434/api/embed"),
        ("ollama", "http://localhost:11434/api", "http://localhost:11434/api/embed"),
        ("openai", "https://api.openai.com/v1", "https://api.openai.com/v1/embeddings"),
    ],
)
def test_embedding_legacy_base_is_migrated_to_visible_endpoint(
    isolated_stores: tuple[Path, Path],
    binding: str,
    base_url: str,
    expected: str,
) -> None:
    catalog_path, _env_path = isolated_stores
    _write_single_embedding_profile_catalog(catalog_path, binding=binding, base_url=base_url)

    loaded = ModelCatalogService(catalog_path).load()

    profile = loaded["services"]["embedding"]["profiles"][0]
    assert profile["base_url"] == expected
    saved = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert saved["services"]["embedding"]["profiles"][0]["base_url"] == expected


def test_embedding_custom_endpoint_is_not_migrated(
    isolated_stores: tuple[Path, Path],
) -> None:
    catalog_path, _env_path = isolated_stores
    _write_single_embedding_profile_catalog(
        catalog_path,
        binding="custom",
        base_url="https://proxy.example/root",
    )

    loaded = ModelCatalogService(catalog_path).load()

    assert (
        loaded["services"]["embedding"]["profiles"][0]["base_url"] == "https://proxy.example/root"
    )
