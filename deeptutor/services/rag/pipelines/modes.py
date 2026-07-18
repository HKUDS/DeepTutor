"""Shared retrieval-mode resolution for mode-aware pipelines (LightRAG, GraphRAG).

Resolution order, first valid wins:

1. an explicit ``mode`` kwarg (a one-off override on the search call),
2. the KB's own ``search_mode`` (``kb_config.json`` → ``knowledge_bases[kb]``),
3. the engine's global default mode set from the engine card
   (``kb_config.json`` → ``defaults.provider_modes[provider]``),
4. the engine's built-in default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from deeptutor.knowledge.config_store import KBConfigStore


def resolve_kb_mode(
    kb_base_dir: str | Path,
    kb_name: Optional[str],
    provider: str,
    *,
    explicit: Any = None,
    supported: Sequence[str],
    default: str,
) -> str:
    """Resolve the retrieval mode; see the module docstring for the order.

    A missing ``kb_config.json`` contributes no candidates; a corrupt one
    raises ``KBConfigCorruptionError`` instead of silently dropping the
    user's configured mode.
    """
    candidates: list[Any] = [explicit]
    data = KBConfigStore(Path(kb_base_dir) / "kb_config.json").read()
    knowledge_bases = data.get("knowledge_bases")
    if kb_name and isinstance(knowledge_bases, dict):
        entry = knowledge_bases.get(kb_name)
        if isinstance(entry, dict):
            candidates.append(entry.get("search_mode"))
    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        provider_modes = defaults.get("provider_modes")
        if isinstance(provider_modes, dict):
            candidates.append(provider_modes.get(provider))

    supported_set = {m.lower() for m in supported}
    for candidate in candidates:
        norm = (str(candidate) if candidate else "").strip().lower()
        if norm in supported_set:
            return norm
    return default


__all__ = ["resolve_kb_mode"]
