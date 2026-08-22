"""PageIndex Cloud and OSS knowledge-base lifecycle.

Both providers use turn-scoped PageIndex SDK tools: Cloud delegates its transport
to the SDK, while OSS binds the same interface to the KB's Local Library. Neither
provider answers through ``RAGPipeline.search``.
"""

from __future__ import annotations

from .pipeline import PageIndexPipeline


def _bound_pageindex_provider(kb_name: str | None) -> str | None:
    if not kb_name:
        return None
    try:
        from deeptutor.multi_user.knowledge_access import resolve_kb
        from deeptutor.services.rag.provider_binding import resolve_bound_provider

        resource = resolve_kb(kb_name, require_write=False)
        return resolve_bound_provider(resource.base_dir, resource.name)
    except Exception:
        return None


def is_pageindex_kb(kb_name: str | None) -> bool:
    from deeptutor.services.rag.factory import PAGEINDEX_OSS_PROVIDER, PAGEINDEX_PROVIDER

    return _bound_pageindex_provider(kb_name) in {PAGEINDEX_PROVIDER, PAGEINDEX_OSS_PROVIDER}


def validate_pageindex_oss_selection(knowledge_bases: list[str]) -> None:
    from deeptutor.services.rag.factory import PAGEINDEX_OSS_PROVIDER

    selected = [
        name
        for name in dict.fromkeys(str(item or "").strip() for item in knowledge_bases)
        if name and _bound_pageindex_provider(name) == PAGEINDEX_OSS_PROVIDER
    ]
    if len(selected) > 1:
        raise ValueError(
            "Select at most one PageIndex OSS knowledge base per request. "
            f"Selected: {', '.join(selected)}"
        )


__all__ = ["PageIndexPipeline", "is_pageindex_kb", "validate_pageindex_oss_selection"]
