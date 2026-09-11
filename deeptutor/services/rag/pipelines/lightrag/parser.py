"""LightRAG parser that consumes frozen DeepTutor ingress bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path
import time

from lightrag.parser.base import BaseParser

from .ingress import IngressError, load_verified_bundle
from .sidecar import build_ir


class DeepTutorParser(BaseParser):
    """Third-party parser registered as ``deeptutor`` in LightRAG rc2."""

    engine_name = "deeptutor"

    async def parse(self, ctx):
        from lightrag.constants import (
            FULL_DOCS_FORMAT_LIGHTRAG,
            FULL_DOCS_FORMAT_RAW,
        )
        from lightrag.parser.base import ParseResult
        from lightrag.sidecar.writer import write_sidecar
        from lightrag.utils import strip_control_characters
        from lightrag.utils_pipeline import make_lightrag_doc_content, sidecar_uri_for

        resolved = ctx.resolve(self.engine_name)
        source = resolved.source_path
        if source.is_symlink() or not source.is_file():
            raise IngressError(f"Frozen ingress source is not an ordinary file: {source}")
        manifest, bundle = load_verified_bundle(Path(ctx.rag.working_dir), resolved.document_name)

        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        source_record = manifest.get("source")
        if not isinstance(source_record, dict) or digest.hexdigest() != source_record.get("sha256"):
            raise IngressError(f"Frozen source digest mismatch: {resolved.document_name}")

        markdown_record = manifest["markdown"]
        markdown = strip_control_characters(
            (bundle / markdown_record["path"]).read_text(encoding="utf-8")
        )
        if manifest.get("blocks") is None:
            if not markdown.strip():
                raise IngressError(f"Frozen RAW document is empty: {resolved.document_name}")
            await ctx.rag._persist_parsed_full_docs(
                ctx.doc_id,
                {
                    "content": markdown,
                    "file_path": ctx.file_path,
                    "parse_format": FULL_DOCS_FORMAT_RAW,
                    "parse_engine": self.engine_name,
                    "update_time": int(time.time()),
                },
            )
            await ctx.archive_source(str(source))
            return ParseResult(
                doc_id=ctx.doc_id,
                file_path=ctx.file_path,
                parse_format=FULL_DOCS_FORMAT_RAW,
                content=markdown,
                parse_engine=self.engine_name,
            )

        ir = build_ir(manifest, bundle)
        parsed_data = write_sidecar(
            ir,
            parsed_dir=resolved.parsed_dir,
            doc_id=ctx.doc_id,
            engine=self.engine_name,
        )
        await ctx.rag._persist_parsed_full_docs(
            ctx.doc_id,
            {
                "content": make_lightrag_doc_content(parsed_data["content"]),
                "file_path": ctx.file_path,
                "parse_format": FULL_DOCS_FORMAT_LIGHTRAG,
                "sidecar_location": sidecar_uri_for(resolved.parsed_dir),
                "parse_engine": self.engine_name,
                "update_time": int(time.time()),
            },
        )
        await ctx.archive_source(str(source))
        return ParseResult(
            doc_id=ctx.doc_id,
            file_path=ctx.file_path,
            parse_format=FULL_DOCS_FORMAT_LIGHTRAG,
            content=parsed_data["content"],
            blocks_path=parsed_data["blocks_path"],
            parse_engine=self.engine_name,
        )


__all__ = ["DeepTutorParser"]
