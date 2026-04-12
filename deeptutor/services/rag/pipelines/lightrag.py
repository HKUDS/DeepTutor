"""
LightRAG Pipeline Implementation
================================

Integrates LightRAG (Dual-level Retrieval-Augmented Generation) into DeepTutor's RAG service.
LightRAG provides better global context understanding by combining graph-based and vector-based retrieval.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import numpy as np

from deeptutor.services.rag.pipeline import BaseRAGPipeline
from deeptutor.services.rag.types import RAGRequest, RAGResponse, SearchResult

logger = logging.getLogger(__name__)

class LightRAGPipeline(BaseRAGPipeline):
    """
    LightRAG pipeline for advanced knowledge retrieval.
    Expects 'lightrag-hku' to be installed.
    """

    def __init__(self, **kwargs):
        """
        Initialize the LightRAG pipeline.
        Args:
            kb_base_dir: Base directory for knowledge bases
            kb_name: Name of the knowledge base
        """
        super().__init__(**kwargs)
        self.kb_name = kwargs.get("kb_name")
        self.kb_base_dir = kwargs.get("kb_base_dir")
        # Ensure the directory exists
        self.working_dir = str(Path(self.kb_base_dir) / self.kb_name)
        os.makedirs(self.working_dir, exist_ok=True)
        self._rag_instance = None

    async def _setup_rag(self) -> None:
        """Sets up the LightRAG instance with DeepTutor service bridges."""
        if self._rag_instance:
            return

        try:
            from lightrag import LightRAG, QueryParam
            from lightrag.utils import EmbeddingFunc
            from deeptutor.services.llm import complete
            from deeptutor.services.embedding import get_embedding_client

            # 1. Bridge LLM
            async def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
                return await complete(
                    prompt, 
                    system_prompt=system_prompt,
                    # Bridge history if needed
                    **kwargs
                )

            # 2. Bridge Embeddings
            embed_client = get_embedding_client()
            config = embed_client.config
            
            async def embedding_func(texts: list[str]) -> np.ndarray:
                vectors = await embed_client.embed(texts)
                return np.array(vectors)

            # 3. Create Instance
            self._rag_instance = LightRAG(
                working_dir=self.working_dir,
                llm_model_func=llm_model_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=config.dimension or 1536,
                    max_token_size=config.max_tokens or 8192,
                    func=embedding_func
                )
            )
            logger.info(f"LightRAG pipeline ready at {self.working_dir}")
        except ImportError:
            logger.error("lightrag-hku or dependencies missing.")
            raise

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """Initialize and ingest initial files."""
        await self._setup_rag()
        
        # Ingest files
        for path in file_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    await self._rag_instance.ainsert(content)
        
        return True

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        """Perform search using LightRAG."""
        await self._setup_rag()
        
        from lightrag import QueryParam
        
        mode = kwargs.get("mode", "hybrid")
        answer = await self._rag_instance.aquery(query, param=QueryParam(mode=mode))
        
        return {
            "query": query,
            "answer": answer,
            "content": answer, # Compatibility with DeepTutor result format
            "sources": [], # LightRAG sources extraction could be added here
            "provider": "lightrag"
        }

    async def delete(self, kb_name: str) -> bool:
        """Delete the LightRAG working directory."""
        if os.path.exists(self.working_dir):
            import shutil
            shutil.rmtree(self.working_dir)
            return True
        return False

    def get_name(self) -> str:
        return "lightrag"
