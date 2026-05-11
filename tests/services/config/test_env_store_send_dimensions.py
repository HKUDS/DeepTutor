"""Tests for ``EMBEDDING_SEND_DIMENSIONS`` round-tripping through ``EnvStore``.

Covers:

* ``_render_optional_bool`` / ``_coerce_optional_bool`` helpers
* ``EnvStore.render_from_catalog`` produces the expected env string
* ``EnvStore.write`` skips the key entirely when the value is empty (so
  ``unset`` users keep getting the default Auto behaviour)
* ``EnvStore.as_summary`` exposes ``send_dimensions`` in the embedding dict
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config.env_store import ENV_KEY_ORDER, EnvStore, _render_optional_bool
from deeptutor.services.config.provider_runtime import _coerce_optional_bool


@pytest.fixture(autouse=True)
def _clean_env_store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``EnvStore`` mutates ``os.environ`` on load/write — isolate each test."""
    import os

    sentinel = object()
    original = {key: os.environ.get(key, sentinel) for key in ENV_KEY_ORDER}
    for key in ENV_KEY_ORDER:
        monkeypatch.delenv(key, raising=False)
    yield
    for key, value in original.items():
        if value is sentinel:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value  # type: ignore[assignment]


def _embedding_catalog(send_dimensions: object | None) -> dict:
    model: dict = {
        "id": "embedding-m",
        "name": "Default Embedding Model",
        "model": "text-embedding-3-large",
        "dimension": "3072",
    }
    if send_dimensions is not None:
        model["send_dimensions"] = send_dimensions
    return {
        "version": 1,
        "services": {
            "llm": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "embedding": {
                "active_profile_id": "embedding-p",
                "active_model_id": "embedding-m",
                "profiles": [
                    {
                        "id": "embedding-p",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-x",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [model],
                    }
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (None, ""),
        ("", ""),
        ("TRUE", "true"),
        ("False", "false"),
        ("yes", "true"),
        ("no", "false"),
        ("garbage", ""),
    ],
)
def test_render_optional_bool(value: object, expected: str) -> None:
    assert _render_optional_bool(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (None, None),
        ("", None),
        ("true", True),
        ("FALSE", False),
        ("on", True),
        ("off", False),
        ("garbage", None),
    ],
)
def test_coerce_optional_bool(value: object, expected: bool | None) -> None:
    assert _coerce_optional_bool(value) is expected


# ---------------------------------------------------------------------------
# render_from_catalog
# ---------------------------------------------------------------------------


def test_render_from_catalog_emits_explicit_true(tmp_path: Path) -> None:
    env = EnvStore(path=tmp_path / ".env")
    rendered = env.render_from_catalog(_embedding_catalog(send_dimensions=True))
    assert rendered["EMBEDDING_SEND_DIMENSIONS"] == "true"


def test_render_from_catalog_emits_explicit_false(tmp_path: Path) -> None:
    env = EnvStore(path=tmp_path / ".env")
    rendered = env.render_from_catalog(_embedding_catalog(send_dimensions=False))
    assert rendered["EMBEDDING_SEND_DIMENSIONS"] == "false"


def test_render_from_catalog_emits_empty_when_unset(tmp_path: Path) -> None:
    env = EnvStore(path=tmp_path / ".env")
    rendered = env.render_from_catalog(_embedding_catalog(send_dimensions=None))
    # Field absent in catalog → empty string in render dict (signals "Auto").
    assert rendered["EMBEDDING_SEND_DIMENSIONS"] == ""


# ---------------------------------------------------------------------------
# write() — empty values are dropped from the .env file
# ---------------------------------------------------------------------------


def test_write_drops_send_dimensions_key_when_empty(tmp_path: Path) -> None:
    env = EnvStore(path=tmp_path / ".env")
    env.write(env.render_from_catalog(_embedding_catalog(send_dimensions=None)))
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "EMBEDDING_SEND_DIMENSIONS" not in text
    # Sanity: other embedding keys are still present.
    assert "EMBEDDING_MODEL=text-embedding-3-large" in text


def test_write_persists_send_dimensions_when_set(tmp_path: Path) -> None:
    env = EnvStore(path=tmp_path / ".env")
    env.write(env.render_from_catalog(_embedding_catalog(send_dimensions=False)))
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "EMBEDDING_SEND_DIMENSIONS=false" in text


def test_write_preserves_provider_specific_embedding_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=gemini-existing\n", encoding="utf-8")
    env = EnvStore(path=env_path)

    env.write(env.render_from_catalog(_embedding_catalog(send_dimensions=None)))

    text = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=gemini-existing" in text


def test_write_preserves_deployment_network_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "CORS_ORIGIN=https://app.example.com",
                "CORS_ORIGINS=https://foo.example.com,https://bar.example.com",
                "DISABLE_SSL_VERIFY=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = EnvStore(path=env_path)

    env.write(env.render_from_catalog(_embedding_catalog(send_dimensions=None)))

    text = env_path.read_text(encoding="utf-8")
    assert "CORS_ORIGIN=https://app.example.com" in text
    assert "CORS_ORIGINS=https://foo.example.com,https://bar.example.com" in text
    assert "DISABLE_SSL_VERIFY=true" in text


# ---------------------------------------------------------------------------
# as_summary() — round-trip from .env back into the embedding dict
# ---------------------------------------------------------------------------


def test_as_summary_reads_send_dimensions(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "EMBEDDING_BINDING=openai",
                "EMBEDDING_MODEL=text-embedding-3-large",
                "EMBEDDING_DIMENSION=3072",
                "EMBEDDING_SEND_DIMENSIONS=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = EnvStore(path=env_path)
    summary = env.as_summary()
    assert summary.embedding["send_dimensions"] == "false"


def test_as_summary_returns_empty_when_unset(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("EMBEDDING_BINDING=openai\n", encoding="utf-8")
    env = EnvStore(path=env_path)
    summary = env.as_summary()
    assert summary.embedding["send_dimensions"] == ""
