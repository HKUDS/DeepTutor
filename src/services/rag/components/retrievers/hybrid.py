# -*- coding: utf-8 -*-
"""
Hybrid Retriever
================

Hybrid retriever combining multiple retrieval strategies.
"""

from pathlib import Path
import sys
from typing import Any, Dict, Optional

from ..base import BaseComponent


class HybridRetriever(BaseComponent):
    """
    Hybrid retriever combining graph and vector retrieval.

    Uses LightRAG's hybrid mode for retrieval.
    """

    name = "hybrid_retriever"
    _instances: Dict[str, Any] = {}

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize hybrid retriever.

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

    async def process(
        self,
        query: str,
        kb_name: str,
        mode: str = "hybrid",
        only_need_context: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search using hybrid retrieval.

        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (hybrid, local, global, naive)
            only_need_context: Whether to only return context without answer
            **kwargs: Additional arguments

        Returns:
            Search results dictionary
        """
        self.logger.info(f"Hybrid search ({mode}) in {kb_name}: {query[:50]}...")

        from src.logging.adapters import LightRAGLogContext

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
                "provider": "hybrid",
            }
