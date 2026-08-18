"""Selection rule shared by PageIndex OSS entry points."""

from __future__ import annotations


def validate_pageindex_oss_selection(knowledge_bases: list[str]) -> None:
    from deeptutor.multi_user.knowledge_access import resolve_kb
    from deeptutor.services.rag.factory import PAGEINDEX_OSS_PROVIDER
    from deeptutor.services.rag.provider_binding import resolve_bound_provider

    selected: list[str] = []
    for requested in knowledge_bases:
        name = str(requested or "").strip()
        if not name:
            continue
        try:
            resource = resolve_kb(name, require_write=False)
            provider = resolve_bound_provider(str(resource.base_dir), resource.name)
        except Exception:
            continue
        if provider == PAGEINDEX_OSS_PROVIDER and name not in selected:
            selected.append(name)
    if len(selected) > 1:
        raise ValueError(
            "Select at most one PageIndex OSS knowledge base per request. "
            f"Selected: {', '.join(selected)}"
        )


__all__ = ["validate_pageindex_oss_selection"]
