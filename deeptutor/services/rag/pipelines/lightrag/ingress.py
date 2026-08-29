"""Freeze DeepTutor parse results into version-local LightRAG ingress bundles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.parsing.types import ParsedDocument

from . import block_policy

PARSER_BRIDGE_SCHEMA = 1
INGRESS_DIRNAME = "deeptutor_ingress"
PENDING_DIRNAME = "pending"
BUNDLES_DIRNAME = "bundles"
MANIFEST_FILENAME = "manifest.json"


class IngressError(RuntimeError):
    """Raised when an ingress bundle crosses or violates its trust boundary."""


@dataclass(frozen=True)
class StagedDocument:
    canonical_name: str
    source_path: Path
    bundle_dir: Path
    manifest_path: Path
    process_options: str
    chunk_options: dict[str, Any]
    audit_ledger: dict[str, Any] | None


def ingress_root(working_dir: Path) -> Path:
    return Path(working_dir) / INGRESS_DIRNAME


def pending_root(working_dir: Path) -> Path:
    return ingress_root(working_dir) / PENDING_DIRNAME


def bundles_root(working_dir: Path) -> Path:
    return ingress_root(working_dir) / BUNDLES_DIRNAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_regular_file(root: Path, path: Path, *, label: str) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise IngressError(f"Bundle root must be an ordinary directory: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise IngressError(f"{label} escapes its bundle root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise IngressError(f"{label} must not traverse a symbolic link: {current}")
    if path.is_symlink():
        raise IngressError(f"{label} must not be a symbolic link: {path}")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (FileNotFoundError, ValueError) as exc:
        raise IngressError(f"{label} escapes its bundle root: {path}") from exc
    stat = resolved.stat()
    if not resolved.is_file() or stat.st_nlink != 1:
        raise IngressError(f"{label} must be an ordinary, unlinked file: {path}")
    return resolved


def _copy_regular(source: Path, target: Path, *, allowed_root: Path | None = None) -> str:
    if source.is_symlink() or not source.is_file():
        raise IngressError(f"Source is not an ordinary file: {source}")
    resolved_source = source.resolve(strict=True)
    if resolved_source.stat().st_nlink != 1:
        raise IngressError(f"Source must not be hard-linked: {source}")
    if allowed_root is not None:
        try:
            resolved_source.relative_to(allowed_root.resolve(strict=True))
        except ValueError as exc:
            raise IngressError(f"Source escapes allowed root: {source}") from exc
    source_digest = _sha256(resolved_source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with resolved_source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    if target.is_symlink() or os.path.samefile(resolved_source, target):
        raise IngressError(f"Frozen copy must not share the source file: {target}")
    target_digest = _sha256(target)
    if target_digest != source_digest:
        raise IngressError(f"Digest drift while freezing {source.name}")
    if target.stat().st_nlink != 1:
        raise IngressError(f"Frozen copy has unexpected hard links: {target}")
    return target_digest


def _write_new_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(data).hexdigest()


def _asset_files(asset_dir: Path | None) -> list[tuple[Path, Path]]:
    if asset_dir is None:
        return []
    root = Path(asset_dir)
    if root.is_symlink() or not root.is_dir():
        raise IngressError(f"Parser asset directory is not an ordinary directory: {root}")
    files: list[tuple[Path, Path]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise IngressError(f"Parser asset is a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise IngressError(f"Parser asset is not an ordinary file: {path}")
        files.append((path, path.relative_to(root)))
    return files


def _freeze_asset_paths(
    blocks: list[dict[str, Any]],
    asset_dir: Path | None,
    asset_files: list[tuple[Path, Path]],
) -> list[dict[str, Any]]:
    """Rewrite parser-owned asset paths to bundle-relative copied paths."""
    frozen = deepcopy(blocks)
    if asset_dir is None:
        return frozen
    root = Path(asset_dir).resolve(strict=True)
    by_source = {source.resolve(strict=True): relative for source, relative in asset_files}
    by_relative = {relative: relative for _, relative in asset_files}
    for index, block in enumerate(frozen):
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or block.get("label") or "").lower()
        if kind not in {"image", "picture", "drawing", "chart"}:
            continue
        for key in ("img_path", "path"):
            raw = block.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw)
            relative: Path | None = None
            if path.is_absolute():
                try:
                    resolved = path.resolve(strict=True)
                except FileNotFoundError as exc:
                    raise IngressError(f"Block {index} asset does not exist: {raw}") from exc
                relative = by_source.get(resolved)
            elif ".." not in path.parts:
                relative = by_relative.get(path)
                if relative is None:
                    candidate = root / path
                    try:
                        relative = by_source.get(candidate.resolve(strict=True))
                    except FileNotFoundError:
                        relative = None
            if relative is None:
                raise IngressError(f"Block {index} asset is outside the frozen asset set: {raw}")
            block[key] = relative.as_posix()
    return frozen


def freeze_document(working_dir: Path, source: Path, parsed: ParsedDocument) -> StagedDocument:
    """Copy one parsed document into an immutable, digest-verified bundle."""
    source = Path(source)
    canonical_name = source.name
    if not canonical_name or canonical_name in {".", ".."}:
        raise IngressError(f"Document has no canonical basename: {source}")
    pending = pending_root(working_dir)
    bundles = bundles_root(working_dir)
    pending.mkdir(parents=True, exist_ok=True)
    bundles.mkdir(parents=True, exist_ok=True)
    staged_source = pending / canonical_name
    archived_source = pending / "__parsed__" / canonical_name
    final_bundle = bundles / f"{canonical_name}.bundle"
    if staged_source.exists() or archived_source.exists() or final_bundle.exists():
        raise IngressError(f"Canonical basename already exists in this version: {canonical_name}")

    temp_bundle = bundles / f".{canonical_name}.{uuid.uuid4().hex}.tmp"
    temp_bundle.mkdir()
    try:
        asset_files = _asset_files(parsed.asset_dir)
        source_digest = _sha256(source.resolve(strict=True))
        staged_digest = _copy_regular(source, staged_source)
        if source_digest != staged_digest:
            raise IngressError(f"Source changed while staging {canonical_name}")

        markdown = parsed.markdown.encode("utf-8")
        markdown_rel = Path("markdown.utf8")
        markdown_digest = _write_new_bytes(temp_bundle / markdown_rel, markdown)

        decision = None
        blocks_rel: Path | None = None
        blocks_digest: str | None = None
        frozen_blocks: list[dict[str, Any]] | None = None
        if parsed.blocks:
            decision = block_policy.prepare_content_list(
                parsed.blocks,
                engine=parsed.engine,
                source_hash=parsed.source_hash,
                parser_signature=parsed.parser_signature,
            )
            frozen_blocks = _freeze_asset_paths(
                decision.content_list, parsed.asset_dir, asset_files
            )
            blocks_rel = Path("blocks.json")
            blocks_bytes = json.dumps(
                frozen_blocks, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            blocks_digest = _write_new_bytes(temp_bundle / blocks_rel, blocks_bytes)
        elif not parsed.markdown.strip():
            raise IngressError(f"Parsed document is empty: {canonical_name}")

        asset_records: list[dict[str, Any]] = []
        for asset, relative in asset_files:
            target = temp_bundle / "assets" / relative
            digest = _copy_regular(asset, target, allowed_root=Path(parsed.asset_dir))
            asset_records.append(
                {"path": target.relative_to(temp_bundle).as_posix(), "sha256": digest}
            )

        kinds = {
            str(block.get("type") or block.get("label") or "").lower()
            for block in (frozen_blocks or [])
            if isinstance(block, dict)
        }
        modalities = "".join(
            flag
            for flag, names in (
                ("i", {"image", "picture", "drawing", "chart"}),
                ("t", {"table"}),
                ("e", {"equation", "formula"}),
            )
            if kinds & names
        )
        process_options = f"P{modalities}" if frozen_blocks else "F"
        chunk_options = (
            {"paragraph_semantic": {"chunk_token_size": 1200}}
            if frozen_blocks
            else {"fixed_token": {}}
        )
        manifest = {
            "parser_bridge_schema": PARSER_BRIDGE_SCHEMA,
            "canonical_filename": canonical_name,
            "parser": {
                "engine": parsed.engine,
                "source_hash": parsed.source_hash,
                "parser_signature": parsed.parser_signature,
            },
            "source": {
                "path": str(Path("..") / ".." / PENDING_DIRNAME / canonical_name),
                "sha256": staged_digest,
            },
            "markdown": {"path": markdown_rel.as_posix(), "sha256": markdown_digest},
            "blocks": (
                {"path": blocks_rel.as_posix(), "sha256": blocks_digest}
                if blocks_rel is not None
                else None
            ),
            "assets": asset_records,
            "process_options": process_options,
            "chunk_options": chunk_options,
            "block_policy": decision.ledger if decision is not None else None,
        }
        atomic_write_json(temp_bundle / MANIFEST_FILENAME, manifest)
        os.replace(temp_bundle, final_bundle)
        return StagedDocument(
            canonical_name=canonical_name,
            source_path=staged_source,
            bundle_dir=final_bundle,
            manifest_path=final_bundle / MANIFEST_FILENAME,
            process_options=process_options,
            chunk_options=chunk_options,
            audit_ledger=decision.ledger if decision is not None else None,
        )
    except BaseException:
        shutil.rmtree(temp_bundle, ignore_errors=True)
        if staged_source.exists() and not staged_source.is_symlink():
            staged_source.unlink()
        raise


def load_verified_bundle(working_dir: Path, canonical_name: str) -> tuple[dict[str, Any], Path]:
    """Load and digest-verify one published bundle by canonical basename."""
    if Path(canonical_name).name != canonical_name or Path(canonical_name).is_absolute():
        raise IngressError(f"Invalid canonical basename: {canonical_name!r}")
    bundle = bundles_root(working_dir) / f"{canonical_name}.bundle"
    manifest_path = bundle / MANIFEST_FILENAME
    manifest = json.loads(
        _contained_regular_file(bundle, manifest_path, label="manifest").read_text(encoding="utf-8")
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("parser_bridge_schema") != PARSER_BRIDGE_SCHEMA
    ):
        raise IngressError(f"Unsupported parser bridge manifest: {manifest_path}")
    if manifest.get("canonical_filename") != canonical_name:
        raise IngressError(f"Bundle basename mismatch: {canonical_name}")

    records: list[tuple[str, dict[str, Any]]] = []
    for key in ("markdown", "blocks"):
        record = manifest.get(key)
        if record is not None:
            if not isinstance(record, dict):
                raise IngressError(f"Malformed {key} record in {manifest_path}")
            records.append((key, record))
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise IngressError(f"Malformed assets record in {manifest_path}")
    records.extend(("asset", record) for record in assets if isinstance(record, dict))
    if len(records) != 1 + int(manifest.get("blocks") is not None) + len(assets):
        raise IngressError(f"Malformed asset entry in {manifest_path}")
    for label, record in records:
        rel = Path(str(record.get("path") or ""))
        if rel.is_absolute() or ".." in rel.parts:
            raise IngressError(f"Unsafe {label} path in {manifest_path}")
        path = _contained_regular_file(bundle, bundle / rel, label=label)
        if _sha256(path) != record.get("sha256"):
            raise IngressError(f"Digest mismatch for {label}: {path}")
    return manifest, bundle


def remove_unaccepted(staged: StagedDocument) -> None:
    """Remove only a pre-enqueue source/bundle whose doc_status does not exist."""
    if staged.source_path.exists() and not staged.source_path.is_symlink():
        staged.source_path.unlink()
    shutil.rmtree(staged.bundle_dir, ignore_errors=True)


__all__ = [
    "BUNDLES_DIRNAME",
    "INGRESS_DIRNAME",
    "IngressError",
    "PARSER_BRIDGE_SCHEMA",
    "PENDING_DIRNAME",
    "StagedDocument",
    "bundles_root",
    "freeze_document",
    "ingress_root",
    "load_verified_bundle",
    "pending_root",
    "remove_unaccepted",
]
