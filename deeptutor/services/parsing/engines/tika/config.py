"""Tika engine config (read-side adapter over the v2 settings slice)."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_TIKA,
    load_document_parsing_settings,
)

DEFAULT_TIKA_SERVER_URL = "http://localhost:9998"


@dataclass(frozen=True)
class TikaConfig:
    """Validated Tika configuration.

    Tika is remote-only: ``server_url`` is a Tika server (``tika-server`` /
    the docker image). There is no local package or model download.
    """

    server_url: str = DEFAULT_TIKA_SERVER_URL


def resolve_tika_config() -> TikaConfig:
    slice_ = (
        load_document_parsing_settings().get("engines", {}).get(DOCUMENT_PARSING_ENGINE_TIKA, {})
    )
    return TikaConfig(
        server_url=str(slice_.get("server_url") or DEFAULT_TIKA_SERVER_URL).rstrip("/")
        or DEFAULT_TIKA_SERVER_URL,
    )


__all__ = ["DEFAULT_TIKA_SERVER_URL", "TikaConfig", "resolve_tika_config"]
