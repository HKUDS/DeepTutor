# -*- coding: utf-8 -*-
"""
Graph Indexer
=============

Knowledge graph indexer using LightRAG.
"""

from pathlib import Path
import sys
from typing import Dict, List, Optional

from ...types import Document
from ..base import BaseComponent


class GraphIndexer(BaseComponent):
    """
    Knowledge graph indexer using LightRAG.

    Builds a knowledge graph from documents for graph-based retrieval.
    """

    name = "graph_indexer"
    _instances: Dict[str, any] = {}  # Cache RAG instances

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize graph indexer.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        super().__init__()
        self.kb_base_dir = kb_base_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent.parent.parent
            / "data"
            / "knowledge_bases"
        )

    def _get_rag_instance(self, kb_name: str):
        """Get or create a RAGAnything instance."""
        working_dir = str(Path(self.kb_base_dir) / kb_name / "rag_storage")

        if working_dir in self._instances:
            return self._instances[working_dir]

        # Add RAG-Anything path
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
        raganything_path = project_root.parent / "raganything" / "RAG-Anything"
        if raganything_path.exists() and str(raganything_path) not in sys.path:
            sys.path.insert(0, str(raganything_path))

        try:
            from raganything import RAGAnything, RAGAnythingConfig

            from src.services.embedding import get_embedding_client
            from src.services.llm import get_llm_client

            # Use unified LLM client from src/services/llm
            llm_client = get_llm_client()
            embed_client = get_embedding_client()

            # Get model function from unified LLM client
            # This handles all provider differences and env var setup for LightRAG
            llm_model_func = llm_client.get_model_func()

            config = RAGAnythingConfig(
                working_dir=working_dir,
                enable_image_processing=True,
                enable_table_processing=True,
                enable_equation_processing=True,
            )

            rag = RAGAnything(
                config=config,
                llm_model_func=llm_model_func,
                embedding_func=embed_client.get_embedding_func(),
            )

            self._instances[working_dir] = rag
            return rag

        except ImportError as e:
            self.logger.error(f"Failed to import RAG-Anything: {e}")
            raise

    async def process(self, kb_name: str, documents: List[Document], **kwargs) -> bool:
        """
        Build knowledge graph from documents.

        Args:
            kb_name: Knowledge base name
            documents: List of documents to index
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        self.logger.info(f"Building knowledge graph for {kb_name}...")

        from src.logging.adapters import LightRAGLogContext

        # Use log forwarding context
        with LightRAGLogContext(scene="indexer"):
            rag = self._get_rag_instance(kb_name)
            await rag._ensure_lightrag_initialized()

            for doc in documents:
                if doc.content:
                    # Write content to temporary file
                    import os
                    import tempfile

                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w", encoding="utf-8", suffix=".txt", delete=False
                        ) as tmp_file:
                            tmp_file.write(doc.content)
                            tmp_path = tmp_file.name

                        # Use RAGAnything API
                        working_dir = str(Path(self.kb_base_dir) / kb_name / "rag_storage")
                        output_dir = os.path.join(working_dir, "output")
                        os.makedirs(output_dir, exist_ok=True)
                        await rag.process_document_complete(tmp_path, output_dir)
                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            os.unlink(tmp_path)

        self.logger.info("Knowledge graph built successfully")
        return True
