"""DeepTutor orchestration for the LightRAG 1.5 native document pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
import shutil
import traceback
from typing import Any, Callable, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.index_versioning import (
    list_kb_versions,
    resolve_storage_dir_for_rebuild,
)
from deeptutor.services.rag.kb_paths import resolve_kb_dir

from . import block_policy, engine, indexing_policy, ingress, storage
from . import config as lr_config
from .indexing_policy import (
    IndexingLLMSnapshot,
    IndexingPolicyError,
    effective_policy,
    freeze_default_snapshot,
    resolve_write_snapshot,
)
from .worker import OwnerLoopBridge, run_in_worker_loop

logger = logging.getLogger(__name__)
DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


@dataclass(frozen=True)
class BatchOutcome:
    requested: int
    preflight_failed: dict[str, str] = field(default_factory=dict)
    accepted: int = 0
    processed: tuple[str, ...] = ()
    failed: dict[str, str] = field(default_factory=dict)
    nonterminal: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    track_id: str = ""
    vlm_used: bool = False
    indexing_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (
            self.requested > 0
            and len(self.processed) == self.requested
            and not self.preflight_failed
            and not self.failed
            and not self.nonterminal
            and not self.missing
        )


class LightRagBatchError(RuntimeError):
    def __init__(self, outcome: BatchOutcome) -> None:
        self.outcome = outcome
        failures = {**outcome.preflight_failed, **outcome.failed}
        detail = "; ".join(f"{name}: {error}" for name, error in sorted(failures.items()))
        message = (
            f"LightRAG batch incomplete: added {len(outcome.processed)}, "
            f"failed {len(failures)}, missing {len(outcome.missing)}, "
            f"nonterminal {len(outcome.nonterminal)}"
        )
        super().__init__(f"{message}: {detail}" if detail else message)


class LightRagNeedsReindexError(RuntimeError):
    """Raised when an append targets a pre-native LightRAG index."""


def _status_text(row: Any) -> str:
    status = getattr(row, "status", None)
    value = getattr(status, "value", status)
    return str(value or "").strip().lower()


def _row_name(row: Any) -> str:
    return Path(str(getattr(row, "file_path", "") or "")).name


def _row_error(row: Any) -> str:
    for key in ("error_msg", "error"):
        value = getattr(row, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _status_text(row) or "unknown LightRAG failure"


class LightRagPipeline:
    def __init__(self, kb_base_dir: Optional[str] = None, **_: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._status_poll_seconds = 0.2
        self._status_no_progress_seconds = 600.0

    def _ensure_available(self) -> None:
        if not lr_config.is_lightrag_available():
            raise lr_config.LightRagNotAvailableError(
                "LightRAG is not installed. Install it with "
                "`pip install 'deeptutor[rag-lightrag]'` to use LightRAG knowledge bases."
            )

    def _resolve_mode(self, kb_name: str, kwargs: dict[str, Any]) -> str:
        from ..modes import resolve_kb_mode

        return resolve_kb_mode(
            self.kb_base_dir,
            kb_name,
            storage.PROVIDER,
            explicit=kwargs.get("mode"),
            supported=lr_config.SUPPORTED_MODES,
            default=lr_config.DEFAULT_MODE,
        )

    def _stage_documents(
        self,
        working_dir: Path,
        file_paths: List[str],
        *,
        vision_available: bool,
    ) -> tuple[list[ingress.StagedDocument], dict[str, str]]:
        from deeptutor.services.parsing import get_parse_service

        parse_service = get_parse_service()
        staged: list[ingress.StagedDocument] = []
        failures: dict[str, str] = {}
        seen: set[str] = set()
        for raw_path in file_paths:
            path = Path(raw_path)
            name = path.name
            if name in seen:
                failures[name] = "duplicate canonical basename in request"
                continue
            seen.add(name)
            try:
                parsed = parse_service.parse(path)
                item = ingress.freeze_document(working_dir, path, parsed)
                if "i" in item.process_options and not vision_available:
                    item = replace(item, process_options=item.process_options.replace("i", ""))
                staged.append(item)
            except Exception as exc:
                failures[name or str(path)] = str(exc)
        return staged, failures

    async def _reconcile(
        self,
        rag: Any,
        staged: list[ingress.StagedDocument],
        preflight_failed: dict[str, str],
        track_id: str,
        io_bridge: OwnerLoopBridge,
        progress_callback: Callable[[int, int], Any] | None,
    ) -> BatchOutcome:
        expected = {item.canonical_name: item for item in staged}
        last_snapshot: tuple[tuple[str, str], ...] | None = None
        last_progress = asyncio.get_running_loop().time()
        terminal_count = 0
        while True:
            io_bridge.raise_if_cancelled()
            rows = await rag.aget_docs_by_track_id(track_id)
            if not isinstance(rows, dict):
                raise engine.LightRagContractError("aget_docs_by_track_id must return an object")
            by_name: dict[str, tuple[str, Any]] = {}
            duplicates: set[str] = set()
            for doc_id, row in rows.items():
                name = _row_name(row)
                if name in by_name:
                    duplicates.add(name)
                by_name[name] = (str(doc_id), row)
            if duplicates:
                raise engine.LightRagContractError(
                    f"track_id returned duplicate canonical basenames: {sorted(duplicates)}"
                )

            snapshot = tuple(
                sorted((name, _status_text(row)) for name, (_, row) in by_name.items())
            )
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                last_progress = asyncio.get_running_loop().time()
            processed = tuple(
                sorted(
                    name
                    for name, (_, row) in by_name.items()
                    if name in expected and _status_text(row) == "processed"
                )
            )
            failed = {
                name: _row_error(row)
                for name, (_, row) in by_name.items()
                if name in expected and _status_text(row) == "failed"
            }
            unknown = {
                name: _status_text(row)
                for name, (_, row) in by_name.items()
                if name in expected
                and _status_text(row)
                not in {
                    "pending",
                    "parsing",
                    "analyzing",
                    "processing",
                    "preprocessed",
                    "processed",
                    "failed",
                }
            }
            active = {
                name: _status_text(row)
                for name, (_, row) in by_name.items()
                if name in expected
                and _status_text(row)
                in {"pending", "parsing", "analyzing", "processing", "preprocessed"}
            }
            missing = tuple(sorted(set(expected) - set(by_name)))
            current_terminal = len(processed) + len(failed)
            if progress_callback is not None and current_terminal != terminal_count:
                terminal_count = current_terminal
                await io_bridge.call(
                    progress_callback, terminal_count, len(expected) + len(preflight_failed)
                )
            if not active and not missing:
                outcome = BatchOutcome(
                    requested=len(expected) + len(preflight_failed),
                    preflight_failed=preflight_failed,
                    accepted=len(expected),
                    processed=processed,
                    failed=failed,
                    nonterminal=unknown,
                    missing=(),
                    track_id=track_id,
                )
                for name in processed:
                    item = expected[name]
                    if item.audit_ledger is not None:
                        doc_id = by_name[name][0]
                        block_policy.write_decision_ledger(
                            Path(rag.working_dir), doc_id, item.audit_ledger
                        )
                return replace(
                    outcome,
                    vlm_used=any("i" in getattr(item, "process_options", "") for item in staged),
                )
            if unknown:
                return BatchOutcome(
                    requested=len(expected) + len(preflight_failed),
                    preflight_failed=preflight_failed,
                    accepted=len(expected),
                    processed=processed,
                    failed=failed,
                    nonterminal=unknown,
                    missing=missing,
                    track_id=track_id,
                )
            if (
                asyncio.get_running_loop().time() - last_progress
                >= self._status_no_progress_seconds
            ):
                return BatchOutcome(
                    requested=len(expected) + len(preflight_failed),
                    preflight_failed=preflight_failed,
                    accepted=len(expected),
                    processed=processed,
                    failed=failed,
                    nonterminal=active,
                    missing=missing,
                    track_id=track_id,
                )
            await asyncio.sleep(self._status_poll_seconds)

    async def _run_indexing(
        self,
        working_dir: Path,
        file_paths: List[str],
        progress_callback: Callable[[int, int], Any] | None,
        snapshot: IndexingLLMSnapshot | None = None,
    ) -> BatchOutcome:
        if snapshot is None:
            snapshot = freeze_default_snapshot()

        async def job(io_bridge: OwnerLoopBridge) -> BatchOutcome:
            io_bridge.raise_if_cancelled()
            staged, preflight_failed = self._stage_documents(
                working_dir,
                file_paths,
                vision_available=snapshot.vision_available,
            )
            if not staged:
                raise LightRagBatchError(
                    BatchOutcome(requested=len(file_paths), preflight_failed=preflight_failed)
                )
            try:
                rag = engine.build_rag(
                    working_dir,
                    io_bridge=io_bridge,
                    enable_vlm=any("i" in item.process_options for item in staged),
                    indexing_snapshot=snapshot,
                )
            except BaseException:
                for item in staged:
                    ingress.remove_unaccepted(item)
                raise
            failed = True
            accepted = False
            enqueue_started = False
            cleanup: list[ingress.StagedDocument] = []
            try:
                await engine.initialize(rag)
                enqueue_started = True
                track_id = await engine.enqueue(rag, staged)
                if not isinstance(track_id, str) or not track_id.strip():
                    raise engine.LightRagContractError(
                        "LightRAG enqueue did not return a valid track_id"
                    )
                accepted = True
                await rag.apipeline_process_enqueue_documents()
                outcome = await self._reconcile(
                    rag,
                    staged,
                    preflight_failed,
                    track_id,
                    io_bridge,
                    progress_callback,
                )
                if not outcome.complete:
                    raise LightRagBatchError(outcome)
                failed = False
                return outcome
            except BaseException:
                if not enqueue_started:
                    cleanup = staged
                elif not accepted:
                    try:
                        cleanup = await engine.confirmed_unaccepted(rag, staged)
                    except BaseException:
                        self.logger.exception(
                            "Could not confirm which LightRAG documents were rejected; "
                            "retaining all staged ingress"
                        )
                raise
            finally:
                try:
                    await engine.finalize(rag, cancel_pending=failed)
                except BaseException:
                    if not failed:
                        raise
                    self.logger.exception("LightRAG cleanup failed while indexing was aborting")
                finally:
                    for item in cleanup:
                        ingress.remove_unaccepted(item)

        outcome = await run_in_worker_loop(job)
        return replace(outcome, indexing_policy=snapshot.persisted_policy())

    def _remove_zero_accepted_candidate(self, root_dir: Path) -> None:
        if not root_dir.is_dir() or storage.has_any_doc_status(root_dir):
            return
        for ingress_dir in (ingress.pending_root(root_dir), ingress.bundles_root(root_dir)):
            if ingress_dir.is_dir() and any(path.is_file() for path in ingress_dir.rglob("*")):
                return
        shutil.rmtree(root_dir)

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        snapshot = kwargs.get("indexing_snapshot")
        if snapshot is None:
            policy = effective_policy(
                kb_dir,
                base_dir=self.kb_base_dir,
                kb_name=kb_name,
            )
            if policy is not None and policy.get("policy") == "pending_pinned":
                snapshot = indexing_policy.snapshot_from_persisted(policy)
            else:
                snapshot = freeze_default_snapshot()
        root_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
        try:
            outcome = await self._run_indexing(
                root_dir, file_paths, kwargs.get("progress_callback"), snapshot
            )
            if not storage.has_output(root_dir):
                raise RuntimeError(f"LightRAG did not produce a ready index for {kb_name!r}")
            policy = dict(outcome.indexing_policy)
            policy["vlm_used"] = outcome.vlm_used
            storage.write_meta(root_dir, indexing_policy=policy)
            self._clear_pending_policy(kb_name)
            return outcome.complete
        except asyncio.CancelledError:
            raise
        except LightRagBatchError as exc:
            if exc.outcome.accepted == 0:
                self._remove_zero_accepted_candidate(root_dir)
            raise
        except Exception:
            self._remove_zero_accepted_candidate(root_dir)
            raise

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self._ensure_available()
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        existing = storage.latest_published_root(kb_dir)
        versions = list_kb_versions(kb_dir)
        explicit = kwargs.get("indexing_snapshot")
        if explicit is not None and (existing is not None or versions):
            raise IndexingPolicyError(
                "An explicit LightRAG indexing model cannot override an existing index; "
                "run a full re-index."
            )
        if existing is None and versions:
            raise LightRagNeedsReindexError(
                "This LightRAG index is legacy, unpublished, or corrupt and must be rebuilt "
                "before appending."
            )
        snapshot = resolve_write_snapshot(
            kb_dir,
            base_dir=self.kb_base_dir,
            kb_name=kb_name,
            explicit=explicit,
        )
        if existing is not None:
            root_dir = existing
            is_update = True
        else:
            root_dir = resolve_storage_dir_for_rebuild(kb_dir, None)
            is_update = False
        try:
            outcome = await self._run_indexing(
                root_dir, file_paths, kwargs.get("progress_callback"), snapshot
            )
            if not storage.has_output(root_dir):
                raise RuntimeError(f"LightRAG did not produce a ready index for {kb_name!r}")
            policy = dict(outcome.indexing_policy)
            policy["vlm_used"] = outcome.vlm_used
            if not is_update:
                storage.write_meta(root_dir, indexing_policy=policy)
                self._clear_pending_policy(kb_name)
            else:
                try:
                    storage.write_meta(root_dir, indexing_policy=policy)
                    self._clear_pending_policy(kb_name)
                except Exception:
                    self.logger.warning(
                        "LightRAG append completed but metadata refresh failed; preserving the "
                        "existing published policy",
                        exc_info=True,
                    )
            return outcome.complete
        except LightRagBatchError as exc:
            if not is_update and exc.outcome.accepted == 0:
                self._remove_zero_accepted_candidate(root_dir)
            raise
        except Exception:
            if not is_update:
                self._remove_zero_accepted_candidate(root_dir)
            raise

    def _clear_pending_policy(self, kb_name: str) -> None:
        """Best-effort cleanup after version metadata became authoritative."""
        try:
            from deeptutor.knowledge.manager import KnowledgeBaseManager

            manager = KnowledgeBaseManager(base_dir=self.kb_base_dir)
            entry = manager.config.get("knowledge_bases", {}).get(kb_name) or {}
            if "pending_indexing_policy" in entry:
                entry.pop("pending_indexing_policy", None)
                manager._save_config()
        except Exception:
            self.logger.warning(
                "Published LightRAG policy for %s but could not clear pending cache",
                kb_name,
                exc_info=True,
            )

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        root_dir = storage.latest_published_root(kb_dir)
        if root_dir is None:
            return {
                "query": query,
                "answer": "This LightRAG knowledge base must be rebuilt for the native pipeline.",
                "content": "",
                "sources": [],
                "provider": storage.PROVIDER,
                "needs_reindex": True,
            }
        mode = self._resolve_mode(kb_name, kwargs)
        try:
            self._ensure_available()

            async def job(io_bridge: OwnerLoopBridge):
                rag = engine.build_rag(root_dir, io_bridge=io_bridge)
                failed = True
                try:
                    await engine.initialize(rag)
                    result = await engine.query_with_sources(rag, query, mode)
                    failed = False
                    return result
                finally:
                    await engine.finalize(rag, cancel_pending=failed)

            answer, sources = await run_in_worker_loop(job)
        except lr_config.LightRagNotAvailableError as exc:
            return self._error_result(query, exc, error_type="not_configured")
        except Exception as exc:
            self.logger.error("LightRAG search failed: %s", exc)
            self.logger.error(traceback.format_exc())
            return self._error_result(query, exc, error_type="retrieval_error")
        return {
            "query": query,
            "answer": answer,
            "content": answer,
            "sources": sources,
            "provider": storage.PROVIDER,
            "mode": mode,
        }

    def _error_result(self, query: str, exc: Exception, *, error_type: str) -> Dict[str, Any]:
        return {
            "query": query,
            "answer": str(exc),
            "content": "",
            "sources": [],
            "provider": storage.PROVIDER,
            "error_type": error_type,
        }

    async def delete(self, kb_name: str, **kwargs) -> bool:
        kb_dir = resolve_kb_dir(self.kb_base_dir, kb_name)
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            return True
        return False


__all__ = [
    "BatchOutcome",
    "LightRagBatchError",
    "LightRagNeedsReindexError",
    "LightRagPipeline",
]
