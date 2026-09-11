"""Tika engine adapter implementing the ``Parser`` protocol.

Remote-only: a Tika 4 server emits Markdown, which is written to the canonical
IR. There is no local package or model download.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from .config import TikaConfig, resolve_tika_config
from .formats import MIN_TIKA_VERSION


class TikaParser:
    name = "tika"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    def resolve_config(self) -> TikaConfig:
        return resolve_tika_config()

    def supported_formats(self) -> frozenset[str]:
        # Tika content-sniffs more than a thousand formats and deployments may
        # add custom parsers. Empty means “delegate support detection to the
        # engine” in the Parser protocol, avoiding a stale DeepTutor whitelist.
        return frozenset()

    def signature(self, config: TikaConfig) -> ParserSignature:
        # Include the server compatibility floor so caches created by the old
        # plain-text Tika path are not reused after the Tika 4 Markdown switch.
        return ParserSignature.build("tika", f"remote-{MIN_TIKA_VERSION}:{config.server_url}", {})

    def is_ready(self, config: TikaConfig) -> ReadinessReport:
        if not (config.server_url or "").strip():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="Tika has no server URL configured.",
            )
        return ReadinessReport(ready=True)

    def verify(self, config: TikaConfig) -> tuple[bool, str]:
        """Live connectivity check for the Settings “Test” button."""
        from .remote import verify_remote

        return verify_remote(config)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: TikaConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from .remote import parse_remote

        parse_remote(source_path, workdir, config=config, on_output=on_output)


__all__ = ["TikaParser"]
