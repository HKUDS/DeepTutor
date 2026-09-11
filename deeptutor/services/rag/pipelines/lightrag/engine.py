"""Exact-version adapter over the LightRAG 1.5 native Python SDK."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
import hashlib
from importlib.metadata import PackageNotFoundError, version
import inspect
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_MODE,
    build_embedding_func,
    build_llm_model_func,
    build_vision_model_func,
    constructor_kwargs_from_settings,
    indexing_kwargs_from_settings,
    normalize_mode,
    query_kwargs_from_settings,
    resolve_lightrag_query_llm_config,
)
from .ingress import IngressError, StagedDocument, pending_root
from .worker import OwnerLoopBridge

LIGHTRAG_DISTRIBUTION = "lightrag-hku"
LIGHTRAG_VERSION = "1.5.7"
PARSER_ENGINE = "deeptutor"


class LightRagContractError(RuntimeError):
    """Raised when the pinned SDK returns a shape DeepTutor cannot trust."""


def installed_version() -> str:
    try:
        return version(LIGHTRAG_DISTRIBUTION)
    except PackageNotFoundError as exc:
        raise LightRagContractError(
            "LightRAG is not installed. Install `deeptutor[rag-lightrag]`."
        ) from exc


def _require_exact_version() -> None:
    current = installed_version()
    if current != LIGHTRAG_VERSION:
        raise LightRagContractError(
            f"DeepTutor requires {LIGHTRAG_DISTRIBUTION}=={LIGHTRAG_VERSION}; found {current}"
        )


def _validate_component(value: str, *, label: str) -> str:
    path = Path(str(value or ""))
    if path.is_absolute() or ".." in path.parts or path.name != str(value):
        raise IngressError(f"{label} must be a canonical basename: {value!r}")
    if not path.name or path.name in {".", ".."}:
        raise IngressError(f"{label} is empty or invalid")
    return path.name


def _safe_candidate(root: Path, candidate: Path) -> Path | None:
    if candidate.is_symlink() or not candidate.is_file():
        return None
    resolved_root = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise IngressError(
            f"LightRAG source resolver escaped version ingress: {candidate}"
        ) from exc
    return resolved


def _controlled_class():
    from lightrag import LightRAG

    class DeepTutorLightRAG(LightRAG):
        def _resolve_source_file_for_parser(
            self,
            file_path: str,
            *,
            source_file: str | None = None,
            parser_engine: str | None = None,
        ) -> str:
            if parser_engine not in (None, PARSER_ENGINE):
                raise IngressError(
                    f"Unsupported parser engine for DeepTutor ingress: {parser_engine}"
                )
            name = _validate_component(file_path, label="file_path")
            if source_file is not None:
                source_name = _validate_component(source_file, label="source_file")
                if source_name != name:
                    raise IngressError(
                        f"LightRAG source hints disagree: {name!r} != {source_name!r}"
                    )
            root = pending_root(Path(self.working_dir))
            root.mkdir(parents=True, exist_ok=True)
            matches = [
                resolved
                for candidate in (root / name, root / "__parsed__" / name)
                if (resolved := _safe_candidate(root, candidate)) is not None
            ]
            if len(matches) != 1:
                reason = "missing" if not matches else "ambiguous"
                raise IngressError(f"Version-local LightRAG source is {reason}: {name}")
            return str(matches[0])

    return DeepTutorLightRAG


_SUFFIXES = frozenset(
    {
        "txt",
        "md",
        "mdx",
        "pdf",
        "doc",
        "docx",
        "ppt",
        "pptx",
        "xls",
        "xlsx",
        "rtf",
        "odt",
        "tex",
        "epub",
        "html",
        "htm",
        "csv",
        "json",
        "xml",
        "yaml",
        "yml",
        "log",
        "conf",
        "ini",
        "properties",
        "sql",
        "sh",
        "c",
        "h",
        "cpp",
        "hpp",
        "py",
        "java",
        "js",
        "ts",
        "swift",
        "go",
        "rb",
        "php",
        "css",
        "scss",
        "less",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "gif",
        "bmp",
        "tiff",
    }
)


def _register_parser() -> None:
    from lightrag.parser.registry import ParserSpec, register_parser

    register_parser(
        ParserSpec(
            engine_name=PARSER_ENGINE,
            impl="deeptutor.services.rag.pipelines.lightrag.parser:DeepTutorParser",
            suffixes=_SUFFIXES,
            queue_group="native",
        )
    )


def workspace_for(working_dir: Path) -> str:
    identity = str(Path(working_dir).resolve()).encode("utf-8")
    return f"deeptutor_{hashlib.sha256(identity).hexdigest()[:16]}"


def build_rag(
    working_dir: Path,
    *,
    io_bridge: OwnerLoopBridge | None = None,
    enable_vlm: bool = False,
    indexing_snapshot: Any | None = None,
) -> Any:
    """Construct one exact-version, version-isolated LightRAG instance."""
    _require_exact_version()
    _register_parser()
    from lightrag.llm_roles import RoleLLMConfig

    llm_adapter_kwargs: dict[str, Any] = {}
    embedding_adapter_kwargs: dict[str, Any] = {}
    if io_bridge is not None:
        llm_adapter_kwargs["io_bridge"] = io_bridge
        embedding_adapter_kwargs["io_bridge"] = io_bridge
    from .indexing_policy import cache_identity_for_config

    query_config = resolve_lightrag_query_llm_config()
    query_func = build_llm_model_func(
        **llm_adapter_kwargs,
        llm_config=query_config,
    )
    query_identity = cache_identity_for_config(query_config)
    query_metadata = {
        "binding": query_config.binding,
        "model": query_identity,
    }
    constructor = {
        "working_dir": str(Path(working_dir)),
        "workspace": workspace_for(working_dir),
        "llm_model_func": query_func,
        "llm_model_name": query_identity,
        "embedding_func": build_embedding_func(**embedding_adapter_kwargs),
        "auto_manage_storages_states": False,
        "vlm_process_enable": bool(enable_vlm),
        **indexing_kwargs_from_settings(),
        **constructor_kwargs_from_settings(),
    }
    role_configs: dict[str, Any] = {
        "keyword": RoleLLMConfig(func=query_func, metadata=query_metadata),
        "query": RoleLLMConfig(func=query_func, metadata=query_metadata),
    }
    if indexing_snapshot is not None:
        from .indexing_policy import cache_identity

        snapshot_kwargs = {
            **llm_adapter_kwargs,
            "llm_config": indexing_snapshot.config,
            "owner": indexing_snapshot.owner,
        }
        metadata = {
            "binding": indexing_snapshot.config.binding,
            "model": cache_identity(indexing_snapshot),
            "host": indexing_snapshot.descriptor.get("endpoint"),
        }
        role_configs["extract"] = RoleLLMConfig(
            func=build_llm_model_func(**snapshot_kwargs), metadata=metadata
        )
    if enable_vlm:
        if indexing_snapshot is None:
            raise LightRagContractError(
                "LightRAG vision indexing requires a frozen indexing-model policy."
            )
        vision_kwargs = llm_adapter_kwargs
        metadata = None
        if indexing_snapshot is not None:
            from .indexing_policy import cache_identity

            vision_kwargs = {
                **llm_adapter_kwargs,
                "llm_config": indexing_snapshot.config,
                "owner": indexing_snapshot.owner,
            }
            metadata = {
                "binding": indexing_snapshot.config.binding,
                "model": cache_identity(indexing_snapshot),
                "host": indexing_snapshot.descriptor.get("endpoint"),
            }
        role_configs["vlm"] = RoleLLMConfig(
            func=build_vision_model_func(**vision_kwargs), metadata=metadata
        )
    if role_configs:
        constructor["role_llm_configs"] = role_configs
    return _controlled_class()(**constructor)


async def initialize(rag: Any) -> None:
    result = rag.initialize_storages()
    if inspect.isawaitable(result):
        await result


async def enqueue(rag: Any, staged: list[StagedDocument]) -> str:
    if not staged:
        raise ValueError("Cannot enqueue an empty LightRAG batch")
    return await rag.apipeline_enqueue_documents(
        [""] * len(staged),
        file_paths=[item.canonical_name for item in staged],
        docs_format="pending_parse",
        parse_engine=PARSER_ENGINE,
        process_options=[item.process_options for item in staged],
        chunk_options=[item.chunk_options for item in staged],
    )


def _document_id(canonical_name: str) -> str:
    from lightrag.utils import compute_mdhash_id
    from lightrag.utils_pipeline import (
        has_known_document_source,
        normalize_document_file_path,
    )

    source = normalize_document_file_path(canonical_name)
    if not has_known_document_source(source):
        raise LightRagContractError(
            f"LightRAG cannot derive a stable document ID for {canonical_name!r}"
        )
    return compute_mdhash_id(source, prefix="doc-")


async def confirmed_unaccepted(rag: Any, staged: list[StagedDocument]) -> list[StagedDocument]:
    """Return documents whose missing doc_status row was strictly confirmed."""
    ids_by_name = {item.canonical_name: _document_id(item.canonical_name) for item in staged}
    rows = await rag.doc_status.get_docs_by_ids(
        list(ids_by_name.values()),
        strict=True,
    )
    if not isinstance(rows, dict):
        raise LightRagContractError("doc_status.get_docs_by_ids must return an object")
    return [item for item in staged if ids_by_name[item.canonical_name] not in rows]


def _managed_queue_funcs(rag: Any) -> Iterable[Callable[..., Any]]:
    role_funcs = getattr(rag, "role_llm_funcs", {})
    candidates: list[object] = list(role_funcs.values()) if isinstance(role_funcs, Mapping) else []
    embedding = getattr(rag, "embedding_func", None)
    candidates.append(getattr(embedding, "func", None))
    candidates.append(getattr(rag, "rerank_model_func", None))
    seen: set[int] = set()
    for candidate in candidates:
        if callable(candidate) and id(candidate) not in seen:
            seen.add(id(candidate))
            yield candidate


async def _shutdown_queues(rag: Any, *, cancel_pending: bool) -> None:
    shutdowns: list[Awaitable[Any]] = []
    for func in _managed_queue_funcs(rag):
        shutdown = getattr(func, "shutdown", None)
        if callable(shutdown):
            result = shutdown(graceful=not cancel_pending, timeout=5.0)
            if inspect.isawaitable(result):
                shutdowns.append(result)
    if shutdowns:
        results = await asyncio.gather(*shutdowns, return_exceptions=True)
        failures = [item for item in results if isinstance(item, BaseException)]
        if failures:
            raise RuntimeError(
                f"Failed to shut down {len(failures)} LightRAG queue(s)"
            ) from failures[0]


async def finalize(rag: Any, *, cancel_pending: bool) -> None:
    await _shutdown_queues(rag, cancel_pending=cancel_pending)
    result = rag.finalize_storages()
    if inspect.isawaitable(result):
        await result


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise LightRagContractError(f"LightRAG query {label} must be a string")
    return value


def _records(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise LightRagContractError(f"LightRAG query data.{key} must be an object array")
    return value


def _query_sources(data: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    references = _records(data, "references")
    ref_paths = {
        str(item.get("reference_id")): str(item.get("file_path") or item.get("source") or "")
        for item in references
        if item.get("reference_id") is not None
    }
    sources: list[dict[str, Any]] = []

    def add(kind: str, record: dict[str, Any], rank: int) -> None:
        ref = str(record.get("reference_id") or "")
        path = str(record.get("file_path") or ref_paths.get(ref, ""))
        if kind == "chunk":
            stable_id = str(record.get("chunk_id") or "")
            title = Path(path).name if path else "LightRAG chunk"
            content = _string(record.get("content", ""), label="chunk content")
        elif kind == "entity":
            stable_id = str(record.get("entity_name") or record.get("entity_id") or "")
            title = stable_id or "LightRAG entity"
            content = _string(record.get("description", ""), label="entity description")
        else:
            src_id = str(record.get("src_id") or "")
            tgt_id = str(record.get("tgt_id") or "")
            stable_id = str(record.get("relation_id") or f"{src_id}->{tgt_id}")
            title = stable_id or "LightRAG relationship"
            content = _string(record.get("description", ""), label="relationship description")
        item = {
            "kind": kind,
            "title": title,
            "content": content,
            "source": path,
            "page": str(record.get("page") or ""),
            "reference_id": ref,
            "rank": rank,
        }
        if kind == "chunk":
            item["chunk_id"] = stable_id
        elif kind == "entity":
            item.update(
                {
                    "entity_id": stable_id,
                    "entity_name": str(record.get("entity_name") or ""),
                    "entity_type": str(record.get("entity_type") or ""),
                    "source_id": str(record.get("source_id") or ""),
                }
            )
        else:
            item.update(
                {
                    "relation_id": stable_id,
                    "src_id": str(record.get("src_id") or ""),
                    "tgt_id": str(record.get("tgt_id") or ""),
                    "keywords": record.get("keywords"),
                    "weight": record.get("weight"),
                    "source_id": str(record.get("source_id") or ""),
                }
            )
        sources.append(item)

    for kind, key in (
        ("chunk", "chunks"),
        ("entity", "entities"),
        ("relationship", "relationships"),
    ):
        for record in _records(data, key):
            add(kind, record, len(sources) + 1)
    for reference in references:
        reference_id = str(reference.get("reference_id") or "")
        path = str(reference.get("file_path") or reference.get("source") or "")
        sources.append(
            {
                "kind": "reference",
                "title": Path(path).name if path else reference_id or "LightRAG reference",
                "content": "",
                "source": path,
                "page": str(reference.get("page") or ""),
                "reference_id": reference_id,
                "rank": len(sources) + 1,
                "reference": reference,
            }
        )
    sources.append(
        {
            "kind": "query_metadata",
            "title": "LightRAG query metadata",
            "content": "",
            "source": "",
            "page": "",
            "reference_id": "",
            "rank": len(sources) + 1,
            "metadata": metadata,
        }
    )
    return sources


async def query_with_sources(
    rag: Any, question: str, mode: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    from lightrag import QueryParam

    param = QueryParam(
        mode=normalize_mode(mode) or DEFAULT_MODE,
        stream=False,
        include_references=True,
        **query_kwargs_from_settings(),
    )
    result = await rag.aquery_llm(question, param=param)
    if not isinstance(result, dict):
        raise LightRagContractError("LightRAG query response must be an object")
    if result.get("status") != "success":
        message = result.get("message")
        raise LightRagContractError(
            str(message).strip()
            if isinstance(message, str) and message.strip()
            else "LightRAG retrieval failed"
        )
    response = result.get("llm_response")
    data = result.get("data")
    metadata = result.get("metadata")
    if (
        not isinstance(response, dict)
        or not isinstance(data, dict)
        or not isinstance(metadata, dict)
    ):
        raise LightRagContractError("LightRAG query response is missing structured fields")
    if response.get("is_streaming") is not False:
        raise LightRagContractError("LightRAG returned streaming output for a non-streaming query")
    content = _string(response.get("content"), label="llm_response.content")
    return content, _query_sources(data, metadata)


__all__ = [
    "LIGHTRAG_DISTRIBUTION",
    "LIGHTRAG_VERSION",
    "LightRagContractError",
    "PARSER_ENGINE",
    "build_rag",
    "confirmed_unaccepted",
    "enqueue",
    "finalize",
    "initialize",
    "installed_version",
    "query_with_sources",
    "workspace_for",
]
