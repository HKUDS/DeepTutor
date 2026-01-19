#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Incrementally add documents to existing knowledge base.
Improved version with Hash-based duplicate checking, robust error handling,
and architectural improvements for data integrity and vision support.
"""

import argparse
import asyncio
from datetime import datetime
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Any, Dict, List

from dotenv import load_dotenv

# Load LLM config early to ensure OPENAI_API_KEY env var is set before LightRAG imports
# This is critical because LightRAG reads os.environ["OPENAI_API_KEY"] directly
from src.services.llm.config import get_llm_config as _early_config_load  # noqa: F401

# Attempt imports for dynamic dependencies
try:
    from lightrag.utils import EmbeddingFunc
except ImportError:
    # This will be caught during runtime if needed
    EmbeddingFunc = None

# Type hinting support for dynamic imports
if TYPE_CHECKING:
    try:
        from raganything import RAGAnything
        from raganything import RAGAnythingConfig as RAGAnythingConfigType
    except ImportError:
        RAGAnything = Any
        RAGAnythingConfigType = Any
else:
    RAGAnything = None
    RAGAnythingConfigType = None

# Placeholder for runtime classes
raganything_cls = None
RAGAnythingConfig = None


def load_dynamic_imports(project_root: Path):
    """Handle the path injections and dynamic imports safely."""
    global raganything_cls, RAGAnythingConfig

    sys.path.insert(0, str(project_root))
    raganything_path = project_root.parent / "raganything" / "RAG-Anything"
    if raganything_path.exists():
        sys.path.insert(0, str(raganything_path))

    try:
        from raganything import RAGAnything as RA
        from raganything import RAGAnythingConfig as RAC

        raganything_cls = RA
        RAGAnythingConfig = RAC
    except ImportError:
        pass


from src.knowledge.extract_numbered_items import process_content_list
from src.logging import LightRAGLogContext, get_logger
from src.services.embedding import (
    get_embedding_client,
    get_embedding_config,
    reset_embedding_client,
)
from src.services.llm import get_llm_config

logger = get_logger("KnowledgeInit")

# Default base directory for knowledge bases
DEFAULT_BASE_DIR = "./data/knowledge_bases"


class DocumentAdder:
    """Add documents to existing knowledge base with Hash-validation"""

    def __init__(
        self,
        kb_name: str,
        base_dir=DEFAULT_BASE_DIR,
        api_key: str | None = None,
        base_url: str | None = None,
        progress_tracker=None,
        rag_provider: str | None = None,
    ):
        self.kb_name = kb_name
        self.base_dir = Path(base_dir)
        self.kb_dir = self.base_dir / kb_name

        if not self.kb_dir.exists():
            raise ValueError(f"Knowledge base does not exist: {kb_name}")

        self.raw_dir = self.kb_dir / "raw"
        self.images_dir = self.kb_dir / "images"
        self.rag_storage_dir = self.kb_dir / "rag_storage"
        self.content_list_dir = self.kb_dir / "content_list"
        self.metadata_file = self.kb_dir / "metadata.json"

        if not self.rag_storage_dir.exists():
            raise ValueError(f"Knowledge base not initialized: {kb_name}")

        self.api_key = api_key
        self.base_url = base_url
        self.progress_tracker = progress_tracker
        self.rag_provider = rag_provider
        self._ensure_working_directories()

    def _ensure_working_directories(self):
        for directory in [self.raw_dir, self.images_dir, self.content_list_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def _get_file_hash(self, file_path: Path) -> str:
        """
        Calculate SHA-256 hash of a file.
        Uses 64KB chunks for better throughput on SSDs.
        """
        sha256_hash = hashlib.sha256()
        chunk_size = 65536  # 64KB
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_ingested_hashes(self) -> Dict[str, str]:
        """Get map of filename -> hash from metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("file_hashes", {})
            except Exception:
                return {}
        return {}

    async def _run_in_executor(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    def add_documents(self, source_files: List[str], allow_duplicates: bool = False) -> List[Path]:
        """
        Synchronous phase: Validates hashes and prepares files.
        Treats 'raw/' as a Write-Ahead Log: files exist there before being canonized in metadata.
        """
        logger.info(f"Validating documents for '{self.kb_name}'...")

        ingested_hashes = self.get_ingested_hashes()

        files_to_process = []
        for source in source_files:
            source_path = Path(source)
            if not source_path.exists():
                logger.warning(f"  ⚠ Missing: {source}")
                continue

            current_hash = self._get_file_hash(source_path)

            # 1. Check if content is already fully ingested (Canon Check)
            # We look for value matches in the metadata hash map
            if current_hash in ingested_hashes.values() and not allow_duplicates:
                logger.info(f"  → Skipped (content already indexed): {source_path.name}")
                continue

            # 2. Prepare file in raw/ (Write-Ahead Log)
            dest_path = self.raw_dir / source_path.name

            should_copy = True
            if dest_path.exists():
                # If file exists in raw, check if it's the same content
                dest_hash = self._get_file_hash(dest_path)
                if dest_hash == current_hash:
                    should_copy = False
                    logger.info(f"  ⚠ Recovering staged file (interrupted run): {source_path.name}")
                else:
                    if not allow_duplicates:
                        # Name collision with different content
                        logger.info(
                            f"  → Skipped (filename collision with different content): {source_path.name}"
                        )
                        continue
                    else:
                        logger.info(f"  → Overwriting existing raw file: {source_path.name}")

            if should_copy:
                shutil.copy2(source_path, dest_path)
                logger.info(f"  ✓ Staged to raw: {source_path.name}")

            files_to_process.append(dest_path)

        return files_to_process

    async def process_new_documents(self, new_files: List[Path]):
        """
        Async phase: Ingests files into the RAG system.

        Uses FileTypeRouter to classify files and route them appropriately:
        - PDF/DOCX/images -> MinerU parser (full document analysis)
        - Text/Markdown -> Direct read + LightRAG insert (fast)

        Falls back to LightRAG pipeline if RAGAnything is unavailable.
        """
        if not new_files:
            return None

        # Pre-import progress stage if needed to avoid overhead in loop
        ProgressStage: Any = None
        if self.progress_tracker:
            from src.knowledge.progress_tracker import ProgressStage

        # Fall back to LightRAG if RAGAnything is not available
        if raganything_cls is None:
            logger.warning("RAGAnything not available, using LightRAG fallback for text processing")
            return await self._process_with_lightrag_fallback(new_files, ProgressStage)

        # Use unified LLM client from src/services/llm
        from src.services.llm import get_llm_client
        from src.services.rag.components.routing import FileTypeRouter

        llm_client = get_llm_client()
        self.llm_cfg = llm_client.config

        # Get model functions from unified LLM client
        # These handle all provider differences (OpenAI, Anthropic, Azure, local, etc.)
        llm_model_func = llm_client.get_model_func()
        vision_model_func = llm_client.get_vision_model_func()

        # Embedding Setup
        reset_embedding_client()
        embedding_cfg = get_embedding_config()
        embedding_client = get_embedding_client()

        async def unified_embed_func(texts):
            return await embedding_client.embed(texts)

        embedding_func = EmbeddingFunc(
            embedding_dim=embedding_cfg.dim,
            max_token_size=embedding_cfg.max_tokens,
            func=unified_embed_func,
        )

        config = RAGAnythingConfig(
            working_dir=str(self.rag_storage_dir),
            parser="mineru",
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )

        with LightRAGLogContext(scene="knowledge_init"):
            rag = raganything_cls(
                config=config,
                llm_model_func=llm_model_func,
                vision_model_func=vision_model_func,
                embedding_func=embedding_func,
            )
            if hasattr(rag, "_ensure_lightrag_initialized"):
                await rag._ensure_lightrag_initialized()

        # Classify files by type
        file_paths_str = [str(f) for f in new_files]
        classification = FileTypeRouter.classify_files(file_paths_str)

        logger.info(
            f"File classification: {len(classification.needs_mineru)} need MinerU, "
            f"{len(classification.text_files)} text files, "
            f"{len(classification.unsupported)} unsupported"
        )

        processed_files = []
        total_files = len(classification.needs_mineru) + len(classification.text_files)
        idx = 0

        # Process files requiring MinerU (PDF, DOCX, images)
        for doc_file_str in classification.needs_mineru:
            doc_file = Path(doc_file_str)
            idx += 1
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Ingesting (MinerU) {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                # Verify file still exists in raw/ (it should, as we staged it)
                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: Staged file missing {doc_file.name}")
                    continue

                await asyncio.wait_for(
                    rag.process_document_complete(
                        file_path=str(doc_file),
                        output_dir=str(self.content_list_dir),
                        parse_method="auto",
                    ),
                    timeout=600.0,
                )
                processed_files.append(doc_file)
                # Store hash on success - "Canonizing" the file
                self._record_successful_hash(doc_file)
                logger.info(f"  ✓ Processed (MinerU): {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        # Process text files directly (fast path - no MinerU)
        for doc_file_str in classification.text_files:
            doc_file = Path(doc_file_str)
            idx += 1
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Ingesting (text) {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                # Verify file still exists
                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: Staged file missing {doc_file.name}")
                    continue

                # Read text file directly
                content = await FileTypeRouter.read_text_file(str(doc_file))
                if content.strip():
                    # Insert directly into LightRAG, bypassing MinerU
                    await rag.lightrag.ainsert(content)
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"  ✓ Processed (text): {doc_file.name}")
                else:
                    logger.warning(f"  ⚠ Skipped empty file: {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        # Log unsupported files
        for doc_file_str in classification.unsupported:
            logger.warning(f"  ⚠ Skipped unsupported file: {Path(doc_file_str).name}")

        await self.fix_structure()
        return processed_files

    async def _process_with_lightrag_fallback(self, new_files: List[Path], ProgressStage):
        """Fallback processing using LightRAG when RAGAnything is not available.

        This is a simpler pipeline that:
        1. Reads text content from supported files
        2. Inserts into LightRAG for indexing
        """
        from lightrag import LightRAG
        from lightrag.llm.openai import openai_complete_if_cache

        self.llm_cfg = get_llm_config()
        model = self.llm_cfg.model
        api_key = self.api_key or self.llm_cfg.api_key
        base_url = self.base_url or self.llm_cfg.base_url

        logger.info(f"Using LightRAG fallback for {len(new_files)} files")

        # Initialize LightRAG with async LLM function
        async def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            return await openai_complete_if_cache(
                model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )

        # Use embedding config
        reset_embedding_client()
        embedding_cfg = get_embedding_config()
        embedding_client = get_embedding_client()

        async def embedding_func(texts):
            logger.info(f"Embedding {len(texts)} texts...")
            result = await embedding_client.embed(texts)
            return result

        try:
            rag = LightRAG(
                working_dir=str(self.rag_storage_dir),
                llm_model_func=llm_model_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=embedding_cfg.dim,
                    max_token_size=embedding_cfg.max_tokens,
                    func=embedding_func,
                ),
            )
            logger.info("LightRAG instance created successfully")
        except Exception as e:
            logger.error(f"Failed to create LightRAG instance: {e}")
            raise

        processed_files = []
        for idx, doc_file in enumerate(new_files, 1):
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Processing {doc_file.name} (fallback mode)",
                        current=idx,
                        total=len(new_files),
                    )

                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: File missing {doc_file.name}")
                    continue

                # Read text content based on file type
                text_content = await self._extract_text_content(doc_file)

                if text_content and text_content.strip():
                    # Insert into LightRAG
                    await rag.ainsert(text_content)
                    logger.info(f"  ✓ Indexed (fallback): {doc_file.name}")
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                else:
                    logger.warning(f"  ⚠ No text content extracted: {doc_file.name}")
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)

            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        return processed_files

    async def _extract_text_content(self, file_path: Path) -> str:
        """Extract text content from a file based on its extension."""
        suffix = file_path.suffix.lower()

        try:
            if suffix in [".txt", ".md", ".markdown"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()

            elif suffix == ".pdf":
                try:
                    import fitz  # PyMuPDF

                    doc = fitz.open(file_path)
                    text_parts = []
                    for page in doc:
                        text_parts.append(page.get_text())
                    doc.close()
                    return "\n".join(text_parts)
                except ImportError:
                    logger.warning("PyMuPDF not available for PDF extraction")
                    return ""

            elif suffix in [".docx", ".doc"]:
                try:
                    from docx import Document

                    doc = Document(file_path)
                    text_parts = [para.text for para in doc.paragraphs]
                    return "\n".join(text_parts)
                except ImportError:
                    logger.warning("python-docx not available for Word extraction")
                    return ""

            else:
                logger.warning(f"Unsupported file type for text extraction: {suffix}")
                return ""

        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""

    def _record_successful_hash(self, file_path: Path):
        """Update metadata with the hash of a successfully processed file."""
        file_hash = self._get_file_hash(file_path)
        try:
            metadata = {}
            if self.metadata_file.exists():
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

            if "file_hashes" not in metadata:
                metadata["file_hashes"] = {}

            metadata["file_hashes"][file_path.name] = file_hash
            # Atomic write: write to temp file, then rename
            fd, tmp_path = tempfile.mkstemp(dir=self.kb_dir, suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self.metadata_file)
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as e:
            logger.warning(f"Could not update hash metadata: {e}")

    @staticmethod
    def _filter_valid_messages(messages):
        return [
            m
            for m in messages
            if isinstance(m, dict) and m.get("role") is not None and m.get("content") is not None
        ]

    async def fix_structure(self):
        """
        Clean up parser output directories after image migration.

        NOTE: Image migration and path updates are now handled by the RAG pipeline
        (raganything.py / raganything_docling.py) BEFORE RAG insertion. This ensures
        RAG stores the correct canonical image paths (kb/images/) from the start.

        This method now only cleans up empty temporary parser output directories.
        """
        logger.info("Checking for leftover parser output directories...")

        # Support both 'auto' (MinerU) and 'docling' parser output directories
        parser_subdirs = ["auto", "docling"]
        cleaned_count = 0

        for doc_dir in list(self.content_list_dir.glob("*")):
            if not doc_dir.is_dir():
                continue

            for parser_subdir in parser_subdirs:
                subdir = doc_dir / parser_subdir
                if subdir.exists():
                    try:
                        # Check if directory is empty or only contains empty subdirs
                        has_content = any(
                            f.is_file() or (f.is_dir() and any(f.iterdir()))
                            for f in subdir.iterdir()
                        )

                        if not has_content:
                            await self._run_in_executor(shutil.rmtree, subdir)
                            cleaned_count += 1
                    except Exception as e:
                        logger.debug(f"Could not clean up {subdir}: {e}")

            # Remove doc_dir if it's now empty
            try:
                if doc_dir.exists() and not any(doc_dir.iterdir()):
                    doc_dir.rmdir()
            except Exception:
                pass

        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} empty parser directories")

    def extract_numbered_items_for_new_docs(self, processed_files, batch_size=20):
        if not processed_files:
            return

        llm_cfg = getattr(self, "llm_cfg", None)
        if llm_cfg is None:
            llm_cfg = get_llm_config()
        api_key = self.api_key or llm_cfg.api_key
        base_url = self.base_url or llm_cfg.base_url
        output_file = self.kb_dir / "numbered_items.json"

        for doc_file in processed_files:
            content_list_file = self.content_list_dir / f"{doc_file.stem}.json"
            if content_list_file.exists():
                process_content_list(
                    content_list_file=content_list_file,
                    output_file=output_file,
                    api_key=api_key,
                    base_url=base_url,
                    batch_size=batch_size,
                    merge=output_file.exists(),
                )

    def update_metadata(self, added_count: int):
        if not self.metadata_file.exists():
            return
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            metadata["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update RAG provider if specified
            if self.rag_provider:
                metadata["rag_provider"] = self.rag_provider

                # Also save to centralized config file
                try:
                    from src.services.config import get_kb_config_service

                    kb_config_service = get_kb_config_service()
                    kb_config_service.set_rag_provider(self.kb_name, self.rag_provider)
                except Exception as config_err:
                    logger.warning(f"Failed to save to centralized config: {config_err}")

            history = metadata.get("update_history", [])
            history.append(
                {
                    "timestamp": metadata["last_updated"],
                    "action": "incremental_add",
                    "count": added_count,
                }
            )
            metadata["update_history"] = history

            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Metadata update failed: {e}")


async def main():
    parser = argparse.ArgumentParser(description="Incrementally add documents to RAG KB")
    parser.add_argument("kb_name", help="KB Name")
    parser.add_argument("--docs", nargs="+", help="Files")
    parser.add_argument("--docs-dir", help="Directory")
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR)
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY"))
    parser.add_argument("--base-url", default=os.getenv("LLM_HOST"))
    parser.add_argument("--allow-duplicates", action="store_true")

    args = parser.parse_args()

    # Initialize dynamic paths
    project_root = Path(__file__).parent.parent.parent
    load_dynamic_imports(project_root)

    load_dotenv()

    doc_files = []
    if args.docs:
        doc_files.extend(args.docs)
    if args.docs_dir:
        p = Path(args.docs_dir)
        for ext in ["*.pdf", "*.docx", "*.txt", "*.md"]:
            doc_files.extend([str(f) for f in p.glob(ext)])

    if not doc_files:
        logger.error("No documents provided.")
        return

    adder = DocumentAdder(args.kb_name, args.base_dir, args.api_key, args.base_url)

    # 1. Sync Phase (Validate and Stage)
    new_files = adder.add_documents(doc_files, allow_duplicates=args.allow_duplicates)

    # 2. Async Ingestion (Process and Canonize)
    if new_files:
        processed = await adder.process_new_documents(new_files)
        if processed:
            adder.extract_numbered_items_for_new_docs(processed)
            adder.update_metadata(len(processed))
            logger.info(f"Done! Successfully added {len(processed)} documents.")
    else:
        logger.info("No new unique documents to add.")


if __name__ == "__main__":
    asyncio.run(main())
