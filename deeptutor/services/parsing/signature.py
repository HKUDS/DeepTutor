"""Stable identity of a parse configuration.

Mirrors :class:`~deeptutor.services.rag.index_versioning.EmbeddingSignature`:
only the fields that change the produced artifact go into the hash, so
re-parsing the same bytes with the same config hits cache, while a
backend/version/knob change yields a fresh signature dir and forces a re-parse.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


@dataclass(frozen=True)
class ParserSignature:
    """``(engine, engine_version, output-affecting params)`` identity.

    ``params`` is a sorted tuple of ``(key, value)`` strings so the hash is
    order-independent. Each engine decides which of its config knobs actually
    affect the output bytes and folds only those in via :meth:`build`
    (e.g. MinerU includes ``mode``/``model_version``/``language`` but never
    ``api_token`` or ``local_cli_path``).
    """

    engine: str
    engine_version: str
    params: tuple[tuple[str, str], ...]

    def hash(self) -> str:
        """Short hex digest used as the cache signature dir name."""
        payload = {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "params": [list(item) for item in self.params],
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def build(
        cls, engine: str, engine_version: str, params: Mapping[str, object]
    ) -> "ParserSignature":
        items = tuple(sorted((str(k), str(v)) for k, v in params.items()))
        return cls(engine=engine, engine_version=engine_version or "", params=items)


__all__ = ["ParserSignature"]
