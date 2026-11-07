# -*- coding: utf-8 -*-
"""
LlamaIndex Pipeline
===================

True LlamaIndex integration using official llama-index library.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr

from src.logging import get_logger
from src.services.embedding import get_embedding_client, get_embedding_config

# Default knowledge base directory
DEFAULT_KB_BASE_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "knowledge_bases"
)


class CustomEmbedding(BaseEmbedding):
    """
    Custom embedding adapter for OpenAI-compatible APIs.

    Works with any OpenAI-compatible endpoint including:
    - Google Gemini (text-embedding-004)
    - OpenAI (text-embedding-ada-002, text-embedding-3-*)
    - Azure OpenAI
    - Local models with OpenAI-compatible API
    """

    _client: Any = PrivateAttr()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client = get_embedding_client()

    @classmethod
    def class_name(cls) -> str:
        return "custom_embedding"

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """Get embedding for a query."""
        embeddings = await self._client.embed([query])
        return embeddings[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a text."""
        embeddings = await self._client.embed([text])
        return embeddings[0]

    def _get_query_embedding(self, query: str) -> List[float]:
        """Sync version - called by LlamaIndex sync API."""
        # Use nest_asyncio to allow nested event loops
        import nest_asyncio

        nest_asyncio.apply()
        return asyncio.run(self._aget_query_embedding(query))

    def _get_text_embedding(self, text: str) -> List[float]:
        """Sync version - called by LlamaIndex sync API."""
        # Use nest_asyncio to allow nested event loops
        import nest_asyncio

        nest_asyncio.apply()
        return asyncio.run(self._aget_text_embedding(text))

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts."""
        return await self._client.embed(texts)


class LlamaIndexPipeline:
    """
    True LlamaIndex pipeline using official llama-index library.

    Uses LlamaIndex's native components:
    - VectorStoreIndex for indexing
    - CustomEmbedding for OpenAI-compatible embeddings
    - SentenceSplitter for chunking
    - StorageContext for persistence
    """

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize LlamaIndex pipeline.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        self.logger = get_logger("LlamaIndexPipeline")
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._configure_settings()

    def _configure_settings(self):
        """Configure LlamaIndex global settings."""
        # Get embedding config
        embedding_cfg = get_embedding_config()

        # Configure custom embedding that works with any OpenAI-compatible API
        Settings.embed_model = CustomEmbedding()

        # Configure chunking
        Settings.chunk_size = 512
        Settings.chunk_overlap = 50

        self.logger.info(
            f"LlamaIndex configured: embedding={embedding_cfg.model} "
            f"({embedding_cfg.dim}D, {embedding_cfg.binding}), chunk_size=512"
        )

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """
        Initialize KB using real LlamaIndex components.

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to process
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        self.logger.info(
            f"Initializing KB '{kb_name}' with {len(file_paths)} files using LlamaIndex"
        )

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Parse documents
            documents = []
            for file_path in file_paths:
                file_path = Path(file_path)
                self.logger.info(f"Parsing: {file_path.name}")

                # Extract text based on file type
                if file_path.suffix.lower() == ".pdf":
                    text = self._extract_pdf_text(file_path)
                else:
                    with open(file_path, "r", encoding="utf-8") as f:
                        text = f.read()

                if text.strip():
                    doc = Document(
                        text=text,
                        metadata={
                            "file_name": file_path.name,
                            "file_path": str(file_path),
                        },
                    )
                    documents.append(doc)
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            if not documents:
                self.logger.error("No valid documents found")
                return False

            # Create index with LlamaIndex (run sync code in thread pool to avoid blocking)
            self.logger.info(f"Creating VectorStoreIndex with {len(documents)} documents...")

            # Run sync LlamaIndex code in thread pool to avoid blocking async event loop
            loop = asyncio.get_event_loop()
            index = await loop.run_in_executor(
                None,  # Use default ThreadPoolExecutor
                lambda: VectorStoreIndex.from_documents(documents, show_progress=True),
            )

            # Persist index
            index.storage_context.persist(persist_dir=str(storage_dir))
            self.logger.info(f"Index persisted to {storage_dir}")

            self.logger.info(f"KB '{kb_name}' initialized successfully with LlamaIndex")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize KB: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False

    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            texts = []
            for page in doc:
                texts.append(page.get_text())
            doc.close()
            return "\n\n".join(texts)
        except ImportError:
            self.logger.warning("PyMuPDF not installed. Cannot extract PDF text.")
            return ""
        except Exception as e:
            self.logger.error(f"Failed to extract PDF text: {e}")
            return ""

    async def search(
        self,
        query: str,
        kb_name: str,
        mode: str = "hybrid",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search using LlamaIndex query engine.

        Args:
            query: Search query
            kb_name: Knowledge base name
            mode: Search mode (ignored, LlamaIndex uses similarity)
            **kwargs: Additional arguments (top_k, etc.)

        Returns:
            Search results dictionary
        """
        self.logger.info(f"Searching KB '{kb_name}' with query: {query[:50]}...")

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"

        if not storage_dir.exists():
            self.logger.warning(f"No LlamaIndex storage found at {storage_dir}")
            return {
                "query": query,
                "answer": "No documents indexed. Please upload documents first.",
                "content": "",
                "mode": mode,
                "provider": "llamaindex",
            }

        try:
            # Load index from storage (run in thread pool)
            loop = asyncio.get_event_loop()

            def load_and_retrieve():
                storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
                index = load_index_from_storage(storage_context)
                top_k = kwargs.get("top_k", 5)

                # Use retriever instead of query_engine to avoid LLM requirement
                retriever = index.as_retriever(similarity_top_k=top_k)
                nodes = retriever.retrieve(query)
                return nodes

            # Execute retrieval in thread pool to avoid blocking
            nodes = await loop.run_in_executor(None, load_and_retrieve)

            # Extract text from retrieved nodes
            context_parts = []
            for node in nodes:
                context_parts.append(node.node.text)

            content = "\n\n".join(context_parts) if context_parts else ""

            return {
                "query": query,
                "answer": content,  # Return context for ChatAgent to use
                "content": content,
                "mode": mode,
                "provider": "llamaindex",
            }

        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return {
                "query": query,
                "answer": f"Search failed: {str(e)}",
                "content": "",
                "mode": mode,
                "provider": "llamaindex",
            }

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """
        Incrementally add documents to an existing LlamaIndex KB.

        If the storage directory exists, loads the existing index and inserts
        new documents. Otherwise, creates a new index.

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to add
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        self.logger.info(f"Adding {len(file_paths)} documents to KB '{kb_name}' using LlamaIndex")

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"

        try:
            # Parse new documents
            documents = []
            for file_path in file_paths:
                file_path = Path(file_path)
                self.logger.info(f"Parsing: {file_path.name}")

                # Extract text based on file type
                if file_path.suffix.lower() == ".pdf":
                    text = self._extract_pdf_text(file_path)
                else:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            text = f.read()
                    except UnicodeDecodeError:
                        with open(file_path, "r", encoding="latin-1") as f:
                            text = f.read()

                if text.strip():
                    doc = Document(
                        text=text,
                        metadata={
                            "file_name": file_path.name,
                            "file_path": str(file_path),
                        },
                    )
                    documents.append(doc)
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            if not documents:
                self.logger.warning("No valid documents to add")
                return False

            loop = asyncio.get_event_loop()

            if storage_dir.exists():
                # Load existing index and insert new documents
                self.logger.info(f"Loading existing index from {storage_dir}...")

                def load_and_insert():
                    storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
                    index = load_index_from_storage(storage_context)

                    # Insert new documents
                    for doc in documents:
                        index.insert(doc)

                    # Persist updated index
                    index.storage_context.persist(persist_dir=str(storage_dir))
                    return len(documents)

                num_added = await loop.run_in_executor(None, load_and_insert)
                self.logger.info(f"Added {num_added} documents to existing index")
            else:
                # Create new index (first time)
                self.logger.info(f"Creating new index with {len(documents)} documents...")
                storage_dir.mkdir(parents=True, exist_ok=True)

                def create_index():
                    index = VectorStoreIndex.from_documents(documents, show_progress=True)
                    index.storage_context.persist(persist_dir=str(storage_dir))
                    return len(documents)

                num_added = await loop.run_in_executor(None, create_index)
                self.logger.info(f"Created new index with {num_added} documents")

            self.logger.info(f"Successfully added documents to KB '{kb_name}'")
            return True

        except Exception as e:
            self.logger.error(f"Failed to add documents: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False

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

        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB '{kb_name}'")
            return True

        return False
