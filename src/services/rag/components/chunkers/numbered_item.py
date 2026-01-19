# -*- coding: utf-8 -*-
"""
Numbered Item Extractor
=======================

Extracts numbered items (definitions, theorems, equations) from documents.
"""

from typing import List

from ...types import Chunk, Document
from ..base import BaseComponent


class NumberedItemExtractor(BaseComponent):
    """
    Extract numbered items (definitions, theorems, equations) from documents.

    Uses LLM to identify and extract structured academic content like
    definitions, theorems, lemmas, propositions, equations, etc.
    """

    name = "numbered_item_extractor"

    def __init__(self, batch_size: int = 20, max_concurrent: int = 5):
        """
        Initialize numbered item extractor.

        Args:
            batch_size: Number of content items to process per batch
            max_concurrent: Maximum concurrent LLM calls
        """
        super().__init__()
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

    async def process(self, doc: Document, **kwargs) -> List[Chunk]:
        """
        Extract numbered items from a document.

        Args:
            doc: Document to extract from (must have content_items)
            **kwargs: Additional arguments

        Returns:
            List of Chunks representing numbered items
        """
        if not doc.content_items:
            self.logger.warning("No content_items in document, skipping extraction")
            return []

        self.logger.info(f"Extracting numbered items from {len(doc.content_items)} content items")

        try:
            from src.knowledge.extract_numbered_items import (
                extract_numbered_items_with_llm_async,
            )
            from src.services.llm import get_llm_client

            llm_client = get_llm_client()

            # Use existing extraction logic
            items = await extract_numbered_items_with_llm_async(
                doc.content_items,
                api_key=llm_client.config.api_key,
                base_url=llm_client.config.base_url,
                batch_size=self.batch_size,
                max_concurrent=self.max_concurrent,
            )

            # Convert to Chunks
            chunks = []
            for identifier, item_data in items.items():
                chunks.append(
                    Chunk(
                        content=item_data["text"],
                        chunk_type=item_data["type"],  # Definition, Theorem, Equation...
                        metadata={
                            "identifier": identifier,
                            "page": item_data.get("page", 0),
                            "img_paths": item_data.get("img_paths", []),
                            "source": doc.file_path,
                        },
                    )
                )

            self.logger.info(f"Extracted {len(chunks)} numbered items")
            return chunks

        except ImportError as e:
            self.logger.warning(f"Could not import extraction module: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Failed to extract numbered items: {e}")
            return []
