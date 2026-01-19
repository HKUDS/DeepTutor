# -*- coding: utf-8 -*-
"""
RAGAnything Pipeline
====================

End-to-end pipeline wrapping RAG-Anything for academic document processing.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from src.logging import get_logger
from src.logging.adapters import LightRAGLogContext

# Load LLM config early to ensure OPENAI_API_KEY env var is set before LightRAG imports
# This is critical because LightRAG reads os.environ["OPENAI_API_KEY"] directly
from src.services.llm.config import get_llm_config as _early_config_load  # noqa: F401


class RAGAnythingPipeline:
    """
    RAG-Anything end-to-end Pipeline.

    Uses RAG-Anything's complete processing:
    - MinerU PDF parsing (multimodal: images, tables, equations)
    - LightRAG knowledge graph construction
    - Hybrid retrieval (hybrid/local/global/naive modes)

    This is a "monolithic" pipeline - best for academic documents.
    """

    name = "raganything"

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        enable_image_processing: bool = True,
        enable_table_processing: bool = True,
        enable_equation_processing: bool = True,
    ):
        """
        Initialize RAGAnything pipeline.

        Args:
            kb_base_dir: Base directory for knowledge bases
            enable_image_processing: Enable image extraction and processing
            enable_table_processing: Enable table extraction and processing
            enable_equation_processing: Enable equation extraction and processing
        """
        self.logger = get_logger("RAGAnythingPipeline")
        self.kb_base_dir = kb_base_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "knowledge_bases"
        )
        self.enable_image = enable_image_processing
        self.enable_table = enable_table_processing
        self.enable_equation = enable_equation_processing
        self._instances: Dict[str, Any] = {}

    def _setup_raganything_path(self):
        """Add RAG-Anything to sys.path if available."""
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        raganything_path = project_root.parent / "raganything" / "RAG-Anything"
        if raganything_path.exists() and str(raganything_path) not in sys.path:
            sys.path.insert(0, str(raganything_path))

    def _get_rag_instance(self, kb_name: str):
        """Get or create RAGAnything instance."""
        kb_dir = Path(self.kb_base_dir) / kb_name
        working_dir = str(kb_dir / "rag_storage")

        if working_dir in self._instances:
            return self._instances[working_dir]

        self._setup_raganything_path()

        from raganything import RAGAnything, RAGAnythingConfig

        from src.services.embedding import get_embedding_client
        from src.services.llm import get_llm_client

        # Use unified LLM client from src/services/llm
        llm_client = get_llm_client()
        embed_client = get_embedding_client()

        # Get model functions from unified LLM client
        # These handle all provider differences (OpenAI, Anthropic, Azure, local, etc.)
        llm_model_func = llm_client.get_model_func()
        vision_model_func = llm_client.get_vision_model_func()

        config = RAGAnythingConfig(
            working_dir=working_dir,
            enable_image_processing=self.enable_image,
            enable_table_processing=self.enable_table,
            enable_equation_processing=self.enable_equation,
        )

        rag = RAGAnything(
            config=config,
            llm_model_func=llm_model_func,
            vision_model_func=vision_model_func,
            embedding_func=embed_client.get_embedding_func(),
        )

        self._instances[working_dir] = rag
        return rag

    async def initialize(
        self,
        kb_name: str,
        file_paths: List[str],
        extract_numbered_items: bool = True,
        **kwargs,
    ) -> bool:
        """
        Initialize KB using RAG-Anything with MinerU parser.

        Processing flow:
        1. Parse documents using MinerU (generates content_list with nested image paths)
        2. Migrate images to canonical location (kb/images/) and update paths in content_list
        3. Insert updated content_list into RAG (now with correct image paths)
        4. Clean up temporary parser output directories

        This ensures RAG stores the final image paths, avoiding path mismatches during retrieval.

        Uses FileTypeRouter to classify files and route them appropriately:
        - PDF files -> MinerU parser (full document analysis)
        - Text files -> Direct read + LightRAG insert (fast)

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to process
            extract_numbered_items: Whether to extract numbered items after processing
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        import json

        from ..components.routing import FileTypeRouter
        from ..utils.image_migration import (
            cleanup_parser_output_dirs,
            migrate_images_and_update_paths,
        )

        self.logger.info(f"Initializing KB '{kb_name}' with {len(file_paths)} files")

        kb_dir = Path(self.kb_base_dir) / kb_name
        content_list_dir = kb_dir / "content_list"
        images_dir = kb_dir / "images"
        content_list_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        # Classify files by type
        classification = FileTypeRouter.classify_files(file_paths)

        self.logger.info(
            f"File classification: {len(classification.needs_mineru)} need MinerU, "
            f"{len(classification.text_files)} text files, "
            f"{len(classification.unsupported)} unsupported"
        )

        with LightRAGLogContext(scene="knowledge_init"):
            rag = self._get_rag_instance(kb_name)
            await rag._ensure_lightrag_initialized()

            total_files = len(classification.needs_mineru) + len(classification.text_files)
            idx = 0
            total_images_migrated = 0

            # Process files requiring MinerU (PDF, DOCX, images)
            for file_path in classification.needs_mineru:
                idx += 1
                file_name = Path(file_path).name
                self.logger.info(f"Processing [{idx}/{total_files}] (MinerU): {file_name}")

                # Step 1: Parse document (without RAG insertion)
                self.logger.info("  Step 1/3: Parsing document...")
                content_list, doc_id = await rag.parse_document(
                    file_path=file_path,
                    output_dir=str(content_list_dir),
                    parse_method="auto",
                )

                # Step 2: Migrate images and update paths
                self.logger.info("  Step 2/3: Migrating images to canonical location...")
                updated_content_list, num_migrated = await migrate_images_and_update_paths(
                    content_list=content_list,
                    source_base_dir=content_list_dir,
                    target_images_dir=images_dir,
                    batch_size=50,
                )
                total_images_migrated += num_migrated

                # Save updated content_list for future reference
                content_list_file = content_list_dir / f"{Path(file_path).stem}.json"
                with open(content_list_file, "w", encoding="utf-8") as f:
                    json.dump(updated_content_list, f, ensure_ascii=False, indent=2)

                # Step 3: Insert into RAG with corrected paths
                self.logger.info("  Step 3/3: Inserting into RAG knowledge graph...")
                await rag.insert_content_list(
                    content_list=updated_content_list,
                    file_path=file_path,
                    doc_id=doc_id,
                )

                self.logger.info(f"  ✓ Completed: {file_name}")

            # Process text files directly (fast path)
            for file_path in classification.text_files:
                idx += 1
                self.logger.info(
                    f"Processing [{idx}/{total_files}] (direct text): {Path(file_path).name}"
                )
                content = await FileTypeRouter.read_text_file(file_path)
                if content.strip():
                    # Insert directly into LightRAG, bypassing MinerU
                    await rag.lightrag.ainsert(content)

            # Log unsupported files
            for file_path in classification.unsupported:
                self.logger.warning(f"Skipped unsupported file: {Path(file_path).name}")

            # Clean up temporary parser output directories
            if total_images_migrated > 0:
                self.logger.info("Cleaning up temporary parser output directories...")
                await cleanup_parser_output_dirs(content_list_dir)

        if extract_numbered_items:
            await self._extract_numbered_items(kb_name)

        self.logger.info(
            f"KB '{kb_name}' initialized successfully ({total_images_migrated} images migrated)"
        )
        return True

    async def _extract_numbered_items(self, kb_name: str):
        """Extract numbered items using existing extraction logic."""
        try:
            import json

            from src.knowledge.extract_numbered_items import (
                extract_numbered_items_with_llm_async,
            )
            from src.services.llm import get_llm_client

            kb_dir = Path(self.kb_base_dir) / kb_name
            content_list_dir = kb_dir / "content_list"

            if not content_list_dir.exists():
                self.logger.warning("No content_list directory found, skipping extraction")
                return

            # Load all content list files
            all_content_items = []
            for json_file in content_list_dir.glob("*.json"):
                with open(json_file, "r", encoding="utf-8") as f:
                    content_items = json.load(f)
                    all_content_items.extend(content_items)

            if not all_content_items:
                self.logger.warning("No content items found for extraction")
                return

            self.logger.info(
                f"Extracting numbered items from {len(all_content_items)} content items"
            )

            llm_client = get_llm_client()
            items = await extract_numbered_items_with_llm_async(
                all_content_items,
                api_key=llm_client.config.api_key,
                base_url=llm_client.config.base_url,
            )

            # Save numbered items
            if items:
                output_file = kb_dir / "numbered_items.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False, indent=2)
                self.logger.info(f"Extracted {len(items)} numbered items")

        except ImportError as e:
            self.logger.warning(f"Could not import extraction module: {e}")
        except Exception as e:
            self.logger.error(f"Failed to extract numbered items: {e}")

    async def search(
        self,
        query: str,
        kb_name: str,
        mode: str = "hybrid",
        only_need_context: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search using RAG-Anything's aquery().

        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (hybrid, local, global, naive)
            only_need_context: Whether to only return context without answer
            **kwargs: Additional arguments

        Returns:
            Search results dictionary
        """
        with LightRAGLogContext(scene="rag_search"):
            rag = self._get_rag_instance(kb_name)
            await rag._ensure_lightrag_initialized()

            answer = await rag.aquery(query, mode=mode, only_need_context=only_need_context)
            answer_str = answer if isinstance(answer, str) else str(answer)

            return {
                "query": query,
                "answer": answer_str,
                "content": answer_str,
                "mode": mode,
                "provider": "raganything",
            }

    async def delete(self, kb_name: str) -> bool:
        """
        Delete knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            True if successful
        """
        import shutil

        kb_dir = Path(self.kb_base_dir) / kb_name
        working_dir = str(kb_dir / "rag_storage")

        # Remove from cache
        if working_dir in self._instances:
            del self._instances[working_dir]

        # Delete directory
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB '{kb_name}'")
            return True

        return False
