"""Per-knowledge-base embedding references and compatible legacy migration.

Persist catalog IDs and index identity only. Credentials are always resolved
from the current catalog; changing the global default never changes a binding.
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.services.embedding.config import EmbeddingConfig

from .embedding_signature import signature_from_config

EMBEDDING_PROVIDERS = {"llamaindex", "graphrag", "lightrag"}


def get_embedding_config(selection=None, *, catalog=None):
    # Config imports the RAG factory during package initialization.
    from deeptutor.services.embedding.config import get_embedding_config as resolve

    return resolve(selection, catalog=catalog)


def uses_bound_embedding(entry: dict) -> bool:
    from deeptutor.knowledge.kb_types import is_connected_kb

    return (
        not is_connected_kb(entry)
        and entry.get("rag_provider", "llamaindex") in EMBEDDING_PROVIDERS
    )


def load_catalog() -> dict:
    from deeptutor.services.config import get_model_catalog_service

    return get_model_catalog_service().load()


def default_selection(catalog: dict | None = None) -> dict | None:
    service = (
        (catalog if catalog is not None else load_catalog())
        .get("services", {})
        .get("embedding", {})
    )
    if service.get("active_profile_id") and service.get("active_model_id"):
        return {"profile_id": service["active_profile_id"], "model_id": service["active_model_id"]}
    return None


def binding_fields(selection: dict, config) -> dict:
    return {
        "embedding_selection": {
            "profile_id": selection["profile_id"],
            "model_id": selection["model_id"],
        },
        "embedding_model": config.model,
        "embedding_dim": config.dim,
        "embedding_signature": signature_from_config(config).hash(),
        "embedding_status": "ready",
        "embedding_mismatch": False,
    }


def migrate_binding(entry: dict, kb_dir: Path, catalog: dict | None = None) -> bool:
    """Pin only when existing evidence identifies a compatible catalog model.

    Older indexes without enough evidence retain their legacy read path. A
    successful full rebuild will pin the model that produced the new vectors.
    """
    if entry.get("embedding_selection") or not uses_bound_embedding(entry):
        return False
    from .index_versioning import list_kb_versions

    catalog = catalog if catalog is not None else load_catalog()
    versions = list_kb_versions(kb_dir)
    signatures = {v.get("embedding_signature") or v.get("signature") for v in versions}
    stored_signature = entry.get("embedding_signature")
    if stored_signature in EMBEDDING_PROVIDERS | {"legacy"}:
        stored_signature = None
    matches = []
    for profile in catalog.get("services", {}).get("embedding", {}).get("profiles", []):
        for model in profile.get("models", []):
            selection = {"profile_id": profile.get("id"), "model_id": model.get("id")}
            try:
                config = get_embedding_config(selection, catalog=catalog)
            except ValueError:
                continue
            signature = signature_from_config(config).hash()
            # Prefer the recorded index identity, not whichever version happens
            # to match today's global default.
            if stored_signature:
                matches_index = signature == stored_signature
            elif entry.get("embedding_model"):
                matches_index = (
                    config.model == entry["embedding_model"]
                    and (not entry.get("embedding_dim") or config.dim == entry["embedding_dim"])
                    and (
                        not signatures
                        or signature in signatures
                        or all(s in EMBEDDING_PROVIDERS | {"legacy"} or not s for s in signatures)
                    )
                )
            else:
                matches_index = signature in signatures
            if matches_index:
                matches.append((selection, config))
    if not matches:
        return False
    # Duplicate catalog entries for the same vector space are equivalent. If
    # there are different identities, leave the legacy binding unresolved.
    if len({signature_from_config(config).hash() for _, config in matches}) != 1:
        return False
    active = default_selection(catalog)
    selection, config = next((item for item in matches if item[0] == active), matches[0])
    entry.update(binding_fields(selection, config))
    return True


def binding_status(
    entry: dict, *, catalog: dict | None = None
) -> tuple[str, EmbeddingConfig | None]:
    selection = entry.get("embedding_selection")
    if not selection:
        return "legacy", None
    if not isinstance(selection, dict):
        return "missing", None
    catalog = catalog if catalog is not None else load_catalog()
    service = catalog.get("services", {}).get("embedding", {})
    profile = next(
        (p for p in service.get("profiles", []) if p.get("id") == selection.get("profile_id")), None
    )
    if not any(m.get("id") == selection.get("model_id") for m in (profile or {}).get("models", [])):
        return "missing", None
    try:
        config = get_embedding_config(selection, catalog=catalog)
    except ValueError:
        return "unconfigured", None
    if (
        entry.get("embedding_signature")
        and entry["embedding_signature"] != signature_from_config(config).hash()
    ):
        return "changed", config
    return "ready", config


def entry_signature(entry: dict):
    """Resolve a bound signature, falling back only for unbound legacy KBs."""
    from .embedding_signature import signature_from_embedding_config

    if not entry.get("embedding_selection"):
        return signature_from_embedding_config()
    status, config = binding_status(entry)
    return signature_from_config(config) if config is not None else None


def bound_graph_storage_root(kb_dir: Path, provider: str, fallback: Path | None) -> Path | None:
    """Keep graph reads on a compatible version if publishing a new binding failed."""
    from deeptutor.services.embedding.config import scoped_embedding_config

    from .index_probe import inspect_provider_version
    from .index_versioning import list_kb_versions

    config = scoped_embedding_config()
    if config is None or fallback is None:
        return fallback
    expected = signature_from_config(config).hash()
    versions = list_kb_versions(kb_dir)
    for version in versions:
        if version.get("embedding_signature") != expected or not version.get("ready"):
            continue
        root = Path(version["storage_path"])
        if provider == "lightrag":
            from .pipelines.lightrag.storage import meta_is_native_published

            if not meta_is_native_published(root):
                continue
        if inspect_provider_version(version, provider).ready:
            return root
    fallback_entry = next((v for v in versions if Path(v["storage_path"]) == fallback), {})
    if not fallback_entry.get("embedding_signature"):
        return fallback  # Older graph indexes did not record embedding identity.
    raise ValueError(
        "No index version matches the bound embedding model. Re-index this knowledge base."
    )


def reconcile_bindings(entries: dict, base_dir: Path) -> bool:
    """Refresh binding health without touching files or changing index identity."""
    changed = False
    try:
        catalog = load_catalog()
    except (ValueError, OSError):
        return False
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not uses_bound_embedding(entry):
            continue
        before = dict(entry)
        migrate_binding(entry, base_dir / name, catalog)
        if entry.get("embedding_selection"):
            state, _ = binding_status(entry, catalog=catalog)
            entry["embedding_status"] = state
            had_mismatch = bool(before.get("embedding_mismatch"))
            if state == "changed":
                entry["embedding_mismatch"] = True
                entry["needs_reindex"] = True
            elif state == "ready":
                entry.pop("embedding_mismatch", None)
                if had_mismatch:
                    entry["needs_reindex"] = False
            # Keep the legacy index picker supplied with the same version list.
            from .index_probe import inspect_kb_versions

            entry["index_versions"] = inspect_kb_versions(
                base_dir / name, entry.get("rag_provider")
            )
        changed = changed or before != entry
    return changed


def _service(base_dir):
    from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService

    return KnowledgeBaseConfigService(Path(base_dir) / "kb_config.json")


def persist_binding(base_dir, kb_name: str, selection: dict, config) -> None:
    _service(base_dir).set_kb_config(
        kb_name, {**binding_fields(selection, config), "needs_reindex": False}
    )


def with_kb_embedding(method):
    """Resolve and isolate the model for the entire async RAG operation."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        # search(query, kb_name); initialize/add_documents(kb_name, files).
        kb_name = kwargs.get("kb_name") or args[1 if method.__name__ == "search" else 0]
        service = _service(self.kb_base_dir)
        entry = service.get_kb_config(kb_name)
        entry["rag_provider"] = self._resolve_provider(kb_name)
        if not uses_bound_embedding(entry):
            return await method(self, *args, **kwargs)
        selection = kwargs.pop("embedding_selection", None)
        frozen_config = kwargs.pop("embedding_config", None)
        if frozen_config is None and entry["rag_provider"] == "lightrag":
            snapshot = kwargs.get("indexing_snapshot") or kwargs.get("accepted_indexing_snapshot")
            if snapshot is not None:
                frozen_config = snapshot.embedding_config
        explicit = selection is not None
        if not explicit:
            if migrate_binding(entry, Path(self.kb_base_dir) / kb_name):
                service.set_kb_config(
                    kb_name, {k: v for k, v in entry.items() if k.startswith("embedding_")}
                )
            selection = entry.get("embedding_selection")
            if not selection and method.__name__ != "initialize":
                from .index_versioning import list_kb_versions

                if list_kb_versions(Path(self.kb_base_dir) / kb_name):
                    # In particular, old GraphRAG indexes use the model in
                    # their saved settings.yaml. Do not overwrite that runtime
                    # with today's default when migration could not identify it.
                    return await method(self, *args, **kwargs)
        try:
            if selection:
                status, config = binding_status({**entry, "embedding_selection": selection})
                if status == "missing":
                    raise ValueError(
                        "The embedding model bound to this knowledge base was deleted. Select another embedding model to re-index it."
                    )
                if status == "unconfigured":
                    raise ValueError(
                        "The bound embedding model is not configured. Check its provider settings."
                    )
                if status == "changed" and not explicit:
                    raise ValueError(
                        "The bound embedding model configuration changed. Re-index this knowledge base before using it."
                    )
                if frozen_config is not None:
                    config = frozen_config
            else:
                selection = default_selection()
                if selection is None:
                    # Preserve legacy callers and installations without a
                    # configured catalog. The pipeline retains its own checks.
                    return await method(self, *args, **kwargs)
                config = get_embedding_config(selection)
        except ValueError as exc:
            if method.__name__ != "search":
                raise
            return {
                "query": kwargs.get("query", args[0] if args else ""),
                "answer": str(exc),
                "content": "",
                "error_type": "embedding_binding_unavailable",
            }
        from deeptutor.services.embedding.config import embedding_config_scope

        locked_publication = entry["rag_provider"] == "lightrag" and method.__name__ != "search"
        if locked_publication:
            expected_binding = (entry.get("embedding_selection"), entry.get("embedding_signature"))

            def validate_binding():
                current = service.get_kb_config(kb_name)
                if (
                    current.get("embedding_selection"),
                    current.get("embedding_signature"),
                ) != expected_binding:
                    raise ValueError(
                        "The knowledge-base embedding binding changed before indexing started; resubmit the operation."
                    )

            def publish_binding():
                persist_binding(self.kb_base_dir, kb_name, selection, config)

            # LightRAG invokes both callbacks under its existing write ownership.
            kwargs["validate_embedding_binding"] = validate_binding
            kwargs["publish_embedding_binding"] = publish_binding

        with embedding_config_scope(config):
            result = await method(self, *args, **kwargs)
            if result and method.__name__ != "search" and selection and not locked_publication:
                persist_binding(self.kb_base_dir, kb_name, selection, config)
            return result

    return wrapped
