#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Incrementally add documents to existing knowledge base.
Improved version with Hash-based duplicate checking, robust error handling,
and architectural improvements for data integrity and vision support.

Supports multiple RAG providers with lazy loading:
- llamaindex: Pure vector retrieval (load_index + insert + persist)
- lightrag: Knowledge graph (LightRAG.ainsert, text-only)
- raganything: Multimodal with MinerU parser
- raganything_docling: Multimodal with Docling parser
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
from typing import Any, Dict, List

from dotenv import load_dotenv

from src.knowledge.extract_numbered_items import process_content_list
from src.logging import LightRAGLogContext, get_logger
from src.services.llm import get_llm_config

# Load LLM config early to ensure OPENAI_API_KEY env var is set before LightRAG imports
# This is critical because LightRAG reads os.environ["OPENAI_API_KEY"] directly
from src.services.llm.config import get_llm_config as _early_config_load  # noqa: F401

logger = get_logger("KnowledgeInit")

# Default base directory for knowledge bases
DEFAULT_BASE_DIR = "./data/knowledge_bases"


class DocumentAdder:
    """Add documents to existing knowledge base with Hash-validation.

    Supports multiple RAG providers with lazy loading to avoid unnecessary imports:
    - llamaindex: Only imports llama_index modules
    - lightrag: Only imports lightrag modules (no raganything)
    - raganything: Imports raganything with MinerU parser
    - raganything_docling: Imports raganything with Docling parser
    """

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

        # For llamaindex, check llamaindex_storage instead of rag_storage
        provider = self._get_provider_from_metadata()
        if provider == "llamaindex":
            llamaindex_storage = self.kb_dir / "llamaindex_storage"
            if not llamaindex_storage.exists():
                raise ValueError(f"Knowledge base not initialized (llamaindex): {kb_name}")
        else:
            if not self.rag_storage_dir.exists():
                raise ValueError(f"Knowledge base not initialized: {kb_name}")

        self.api_key = api_key
        self.base_url = base_url
        self.progress_tracker = progress_tracker

        # IMPORTANT: rag_provider parameter is IGNORED for incremental add
        # We always use the provider from KB metadata to ensure consistency
        # This prevents mixing different index formats in the same KB
        self._resolved_provider = provider
        if rag_provider and rag_provider != provider:
            logger.warning(
                f"Requested provider '{rag_provider}' ignored. "
                f"Using KB's existing provider '{provider}' for consistency."
            )
        logger.info(f"Incremental add will use provider: {provider} (from KB metadata)")
        self._ensure_working_directories()

    def _get_provider_from_metadata(self) -> str:
        """
        Get the RAG provider for the KB.

        Priority:
        1. kb_config.json (authoritative source)
        2. metadata.json (backward compatibility)
        3. Detect from storage structure (fallback)

        This ensures we use the same provider that was used during initialization
        for data consistency and correct storage format.

        Returns:
            Provider name (llamaindex, lightrag, raganything, raganything_docling)
        """
        # First, try kb_config.json (authoritative source)
        kb_config_file = Path(self.base_dir) / "kb_config.json"
        if kb_config_file.exists():
            try:
                with open(kb_config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    kb_config = config.get("knowledge_bases", {}).get(self.kb_name, {})
                    provider = kb_config.get("rag_provider")
                    if provider:
                        return provider
            except Exception as e:
                logger.warning(f"Failed to read provider from kb_config.json: {e}")
        
        # Fallback: try metadata.json (backward compatibility)
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    provider = metadata.get("rag_provider")
                    if provider:
                        return provider
            except Exception as e:
                logger.warning(f"Failed to read provider from metadata.json: {e}")

        # Fallback: detect from storage structure
        llamaindex_storage = self.kb_dir / "llamaindex_storage"
        if llamaindex_storage.exists():
            return "llamaindex"

        # Default to raganything for backward compatibility
        return "raganything"

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

        Uses lazy loading to only import dependencies for the actual provider:
        - llamaindex: Only imports llama_index
        - lightrag: Only imports lightrag (no raganything)
        - raganything: Imports raganything with MinerU
        - raganything_docling: Imports raganything with Docling
        """
        if not new_files:
            return None

        provider = self._resolved_provider
        logger.info(f"Processing {len(new_files)} files with provider: {provider}")

        # Dispatch to provider-specific implementation
        if provider == "llamaindex":
            return await self._process_llamaindex(new_files)
        elif provider == "lightrag":
            return await self._process_lightrag(new_files)
        elif provider == "raganything":
            return await self._process_raganything(new_files, parser="mineru")
        elif provider == "raganything_docling":
            return await self._process_raganything(new_files, parser="docling")
        else:
            raise ValueError(f"Unknown RAG provider: {provider}")

    async def _process_llamaindex(self, new_files: List[Path]) -> List[Path]:
        """
        Incremental add for LlamaIndex pipeline.
        Lazy imports llama_index only when needed.
        """
        logger.info("Using LlamaIndex incremental add...")

        # Lazy import llama_index
        try:
            from src.services.rag.pipelines.llamaindex import LlamaIndexPipeline
        except ImportError as e:
            raise ImportError(
                f"LlamaIndex dependencies not installed. "
                f"Install with: pip install llama-index llama-index-core. Error: {e}"
            ) from e

        # Pre-import progress stage if needed
        ProgressStage: Any = None
        if self.progress_tracker:
            from src.knowledge.progress_tracker import ProgressStage

        pipeline = LlamaIndexPipeline(kb_base_dir=str(self.base_dir))
        file_paths = [str(f) for f in new_files]

        # Use the new add_documents method for incremental add
        processed_files = []
        total_files = len(file_paths)

        for idx, file_path in enumerate(file_paths, 1):
            doc_file = Path(file_path)
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Indexing (LlamaIndex) {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                # Use add_documents for incremental add
                success = await pipeline.add_documents(self.kb_name, [file_path])
                if success:
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"  ✓ Processed (LlamaIndex): {doc_file.name}")
                else:
                    logger.error(f"  ✗ Failed to index: {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        return processed_files

    async def _process_lightrag(self, new_files: List[Path]) -> List[Path]:
        """
        Incremental add for LightRAG pipeline (text-only).
        Lazy imports lightrag only when needed - does NOT require raganything.
        """
        logger.info("Using LightRAG incremental add (text-only)...")

        # Lazy import lightrag
        try:
            from lightrag import LightRAG
            from lightrag.utils import EmbeddingFunc
        except ImportError as e:
            raise ImportError(
                f"LightRAG dependencies not installed. "
                f"Install with: pip install lightrag. Error: {e}"
            ) from e

        from src.services.embedding import (
            get_embedding_client,
            get_embedding_config,
            reset_embedding_client,
        )
        from src.services.llm import get_llm_client
        from src.services.rag.components.routing import FileTypeRouter

        # Pre-import progress stage if needed
        ProgressStage: Any = None
        if self.progress_tracker:
            from src.knowledge.progress_tracker import ProgressStage

        # Setup LLM and embedding
        llm_client = get_llm_client()
        self.llm_cfg = llm_client.config
        llm_model_func = llm_client.get_model_func()

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

        # Create LightRAG instance (text-only, no raganything)
        with LightRAGLogContext(scene="knowledge_incremental"):
            rag = LightRAG(
                working_dir=str(self.rag_storage_dir),
                llm_model_func=llm_model_func,
                embedding_func=embedding_func,
            )
            await rag.initialize_storages()

            from lightrag.kg.shared_storage import initialize_pipeline_status

            await initialize_pipeline_status()

        # Classify files
        file_paths_str = [str(f) for f in new_files]
        classification = FileTypeRouter.classify_files(file_paths_str)

        logger.info(
            f"File classification: {len(classification.needs_mineru)} need parsing, "
            f"{len(classification.text_files)} text files, "
            f"{len(classification.unsupported)} unsupported"
        )

        processed_files = []
        total_files = len(classification.needs_mineru) + len(classification.text_files)
        idx = 0

        # For LightRAG (text-only), use basic PDF text extraction for PDFs
        for doc_file_str in classification.needs_mineru:
            doc_file = Path(doc_file_str)
            idx += 1
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Extracting text from {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: File missing {doc_file.name}")
                    continue

                # Basic text extraction
                content = await self._extract_text_basic(doc_file)
                if content.strip():
                    await rag.ainsert(content)
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"  ✓ Processed (LightRAG): {doc_file.name}")
                else:
                    logger.warning(f"  ⚠ No text extracted: {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        # Process text files directly
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

                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: File missing {doc_file.name}")
                    continue

                content = await FileTypeRouter.read_text_file(str(doc_file))
                if content.strip():
                    await rag.ainsert(content)
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"  ✓ Processed (text): {doc_file.name}")
                else:
                    logger.warning(f"  ⚠ Skipped empty file: {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        for doc_file_str in classification.unsupported:
            logger.warning(f"  ⚠ Skipped unsupported file: {Path(doc_file_str).name}")

        return processed_files

    async def _process_raganything(
        self, new_files: List[Path], parser: str = "mineru"
    ) -> List[Path]:
        """
        Incremental add for RAGAnything pipeline (multimodal).
        Lazy imports raganything only when needed.

        Args:
            parser: "mineru" for RAGAnything, "docling" for RAGAnything Docling
        """
        parser_name = "MinerU" if parser == "mineru" else "Docling"
        logger.info(f"Using RAGAnything incremental add with {parser_name} parser...")

        # Lazy import raganything
        try:
            # Add RAG-Anything to path if needed
            project_root = Path(__file__).resolve().parent.parent.parent
            raganything_path = project_root.parent / "raganything" / "RAG-Anything"
            if raganything_path.exists() and str(raganything_path) not in sys.path:
                sys.path.insert(0, str(raganything_path))

            from lightrag.utils import EmbeddingFunc
            from raganything import RAGAnything, RAGAnythingConfig
        except ImportError as e:
            raise ImportError(
                f"RAGAnything dependencies not installed. "
                f"Please install raganything package. Error: {e}"
            ) from e

        from src.services.embedding import (
            get_embedding_client,
            get_embedding_config,
            reset_embedding_client,
        )
        from src.services.llm import get_llm_client
        from src.services.rag.components.routing import FileTypeRouter
        from src.services.rag.utils.image_migration import (
            cleanup_parser_output_dirs,
            migrate_images_and_update_paths,
        )

        # Pre-import progress stage if needed
        ProgressStage: Any = None
        if self.progress_tracker:
            from src.knowledge.progress_tracker import ProgressStage

        # Setup LLM and embedding
        llm_client = get_llm_client()
        self.llm_cfg = llm_client.config
        llm_model_func = llm_client.get_model_func()
        vision_model_func = llm_client.get_vision_model_func()

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

        # Configure RAGAnything with the appropriate parser
        config = RAGAnythingConfig(
            working_dir=str(self.rag_storage_dir),
            parser=parser,
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )

        with LightRAGLogContext(scene="knowledge_incremental"):
            rag = RAGAnything(
                config=config,
                llm_model_func=llm_model_func,
                vision_model_func=vision_model_func,
                embedding_func=embedding_func,
            )
            if hasattr(rag, "_ensure_lightrag_initialized"):
                await rag._ensure_lightrag_initialized()

        # Classify files
        file_paths_str = [str(f) for f in new_files]
        classification = FileTypeRouter.classify_files(file_paths_str)

        logger.info(
            f"File classification: {len(classification.needs_mineru)} need {parser_name}, "
            f"{len(classification.text_files)} text files, "
            f"{len(classification.unsupported)} unsupported"
        )

        processed_files = []
        total_files = len(classification.needs_mineru) + len(classification.text_files)
        idx = 0
        total_images_migrated = 0

        # Process files requiring parser (PDF, DOCX, images)
        for doc_file_str in classification.needs_mineru:
            doc_file = Path(doc_file_str)
            idx += 1
            try:
                if self.progress_tracker and ProgressStage:
                    self.progress_tracker.update(
                        ProgressStage.PROCESSING_FILE,
                        f"Ingesting ({parser_name}) {doc_file.name}",
                        current=idx,
                        total=total_files,
                    )

                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: File missing {doc_file.name}")
                    continue

                # Step 1: Parse document
                logger.info(f"  Step 1/3: Parsing {doc_file.name}...")
                content_list, doc_id = await rag.parse_document(
                    file_path=str(doc_file),
                    output_dir=str(self.content_list_dir),
                    parse_method="auto",
                )

                # Step 2: Migrate images
                logger.info("  Step 2/3: Migrating images...")
                updated_content_list, num_migrated = await migrate_images_and_update_paths(
                    content_list=content_list,
                    source_base_dir=self.content_list_dir,
                    target_images_dir=self.images_dir,
                    batch_size=50,
                )
                total_images_migrated += num_migrated

                # Save content_list
                content_list_file = self.content_list_dir / f"{doc_file.stem}.json"
                with open(content_list_file, "w", encoding="utf-8") as f:
                    json.dump(updated_content_list, f, ensure_ascii=False, indent=2)

                # Step 3: Insert into RAG
                logger.info("  Step 3/3: Inserting into knowledge graph...")
                await rag.insert_content_list(
                    content_list=updated_content_list,
                    file_path=str(doc_file),
                    doc_id=doc_id,
                )

                processed_files.append(doc_file)
                self._record_successful_hash(doc_file)
                logger.info(f"  ✓ Processed ({parser_name}): {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        # Process text files directly
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

                if not doc_file.exists():
                    logger.error(f"  ✗ Failed: File missing {doc_file.name}")
                    continue

                content = await FileTypeRouter.read_text_file(str(doc_file))
                if content.strip():
                    await rag.lightrag.ainsert(content)
                    processed_files.append(doc_file)
                    self._record_successful_hash(doc_file)
                    logger.info(f"  ✓ Processed (text): {doc_file.name}")
                else:
                    logger.warning(f"  ⚠ Skipped empty file: {doc_file.name}")
            except Exception as e:
                logger.exception(f"  ✗ Failed {doc_file.name}: {e}")

        for doc_file_str in classification.unsupported:
            logger.warning(f"  ⚠ Skipped unsupported file: {Path(doc_file_str).name}")

        # Cleanup parser output directories
        if total_images_migrated > 0:
            logger.info("Cleaning up temporary parser output directories...")
            await cleanup_parser_output_dirs(self.content_list_dir)

        await self.fix_structure()
        return processed_files

    async def _extract_text_basic(self, file_path: Path) -> str:
        """Basic text extraction for LightRAG (text-only pipeline)."""
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(file_path)
                texts = []
                for page in doc:
                    texts.append(page.get_text())
                doc.close()
                return "\n\n".join(texts)
            except ImportError:
                logger.warning("PyMuPDF not installed. Cannot extract PDF text.")
                return ""
            except Exception as e:
                logger.error(f"Failed to extract PDF text: {e}")
                return ""
        else:
            # Try to read as text
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        return f.read()
                except Exception as e:
                    logger.error(f"Failed to read file as text: {e}")
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
        """Update metadata after incremental add.

        Note: We do NOT update rag_provider here - incremental adds must use
        the same provider as the original initialization for consistency.
        """
        if not self.metadata_file.exists():
            return
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            metadata["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Record the provider used (should match what's already in metadata)
            if "rag_provider" not in metadata and self._resolved_provider:
                metadata["rag_provider"] = self._resolved_provider

            history = metadata.get("update_history", [])
            history.append(
                {
                    "timestamp": metadata["last_updated"],
                    "action": "incremental_add",
                    "count": added_count,
                    "provider": self._resolved_provider,
                }
            )
            metadata["update_history"] = history

            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Metadata update failed: {e}")


async def main():
    parser = argparse.ArgumentParser(
        description="Incrementally add documents to RAG KB",
        epilog="""
Example usage:
  # Add documents to existing KB (uses provider from KB metadata)
  python -m src.knowledge.add_documents my_kb --docs doc1.pdf doc2.txt

  # Add all documents from a directory
  python -m src.knowledge.add_documents my_kb --docs-dir ./documents/
        """,
    )
    parser.add_argument("kb_name", help="KB Name")
    parser.add_argument("--docs", nargs="+", help="Files")
    parser.add_argument("--docs-dir", help="Directory")
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR)
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY"))
    parser.add_argument("--base-url", default=os.getenv("LLM_HOST"))
    parser.add_argument("--allow-duplicates", action="store_true")

    args = parser.parse_args()

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
