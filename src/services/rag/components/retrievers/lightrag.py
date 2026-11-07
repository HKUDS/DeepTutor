# -*- coding: utf-8 -*-
"""
LightRAG Retriever
==================

Pure LightRAG retriever (text-only, no multimodal).
"""

from pathlib import Path
import sys
from typing import Any, ClassVar, Dict, Optional

from ..base import BaseComponent


class LightRAGRetriever(BaseComponent):
    """
    Pure LightRAG retriever using LightRAG.query() directly.

    Uses LightRAG's native retrieval modes (naive, local, global, hybrid).
    Text-only, no multimodal processing.
    """

    name = "lightrag_retriever"
    _instances: ClassVar[Dict[str, Any]] = {}

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize LightRAG retriever.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        super().__init__()
        self.kb_base_dir = kb_base_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent.parent.parent
            / "data"
            / "knowledge_bases"
        )

    def _get_lightrag_instance(self, kb_name: str):
        """Get or create a pure LightRAG instance (text-only)."""
        working_dir = str(Path(self.kb_base_dir) / kb_name / "rag_storage")

        if working_dir in self._instances:
            return self._instances[working_dir]

        # Add LightRAG path
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
        raganything_path = project_root.parent / "raganything" / "RAG-Anything"
        if raganything_path.exists() and str(raganything_path) not in sys.path:
            sys.path.insert(0, str(raganything_path))

        try:
            from lightrag import LightRAG

            from src.services.embedding import get_embedding_client
            from src.services.llm import get_llm_client

            # Use unified LLM client from src/services/llm
            llm_client = get_llm_client()
            embed_client = get_embedding_client()

            # Get model function from unified LLM client
            # This handles all provider differences and env var setup for LightRAG
            llm_model_func = llm_client.get_model_func()

            # Create pure LightRAG instance (no multimodal)
            rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=llm_model_func,
                embedding_func=embed_client.get_embedding_func(),  # Use proper EmbeddingFunc object
            )

            self._instances[working_dir] = rag
            return rag

        except ImportError as e:
            self.logger.error(f"Failed to import LightRAG: {e}")
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
        Search using pure LightRAG retrieval (text-only).

        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (hybrid, local, global, naive)
            only_need_context: Whether to only return context without answer
            **kwargs: Additional arguments

        Returns:
            Search results dictionary
        """
        self.logger.info(f"LightRAG search ({mode}) in {kb_name}: {query[:50]}...")

        from src.logging.adapters import LightRAGLogContext

        with LightRAGLogContext(scene="LightRAG-Search"):
            rag = self._get_lightrag_instance(kb_name)

            # Initialize storages if not already initialized
            await rag.initialize_storages()
            from lightrag.kg.shared_storage import initialize_pipeline_status

            await initialize_pipeline_status()

            # Import QueryParam for proper query parameter passing
            from lightrag import QueryParam

            # Use LightRAG's native query method with QueryParam object
            query_param = QueryParam(mode=mode, only_need_context=only_need_context)
            answer = await rag.aquery(query, param=query_param)
            answer_str = answer if isinstance(answer, str) else str(answer)

            return {
                "query": query,
                "answer": answer_str,
                "content": answer_str,
                "mode": mode,
                "provider": "lightrag",
            }
