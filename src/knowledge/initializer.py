#!/usr/bin/env python
"""
Knowledge Base Initialization Script

This script initializes a new knowledge base from given documents:
1. Creates directory structure
2. Processes documents using RAG-Anything
3. Builds knowledge graph database
4. Extracts images and content lists
"""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
# Add raganything module path
raganything_path = project_root.parent / "raganything" / "RAG-Anything"
if raganything_path.exists():
    sys.path.insert(0, str(raganything_path))

from dotenv import load_dotenv
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

from src.core.core import get_embedding_config, get_llm_config

load_dotenv(dotenv_path=".env", override=False)

# Use unified logging system
from src.core.logging import LightRAGLogContext, get_logger

logger = get_logger("KnowledgeInit")

# Import numbered items extraction functionality
from src.knowledge.extract_numbered_items import process_content_list
from src.knowledge.progress_tracker import ProgressStage, ProgressTracker


class KnowledgeBaseInitializer:
    """Knowledge base initializer"""

    def __init__(
        self,
        kb_name: str,
        base_dir="./data/knowledge_bases",
        api_key: str = None,
        base_url: str = None,
        progress_tracker: ProgressTracker = None,
    ):
        self.kb_name = kb_name
        self.base_dir = Path(base_dir)
        self.kb_dir = self.base_dir / kb_name

        # Directory structure
        self.raw_dir = self.kb_dir / "raw"
        self.images_dir = self.kb_dir / "images"
        self.rag_storage_dir = self.kb_dir / "rag_storage"
        self.content_list_dir = self.kb_dir / "content_list"

        # Get LLM configuration if api_key or base_url not provided
        llm_cfg = get_llm_config()
        self.api_key = api_key or llm_cfg.get("api_key")
        self.base_url = base_url or llm_cfg.get("base_url")
        self.embedding_cfg = get_embedding_config()
        self.progress_tracker = progress_tracker or ProgressTracker(kb_name, self.base_dir)

    def _register_to_config(self):
        """Register knowledge base to kb_config.json"""
        config_file = self.base_dir / "kb_config.json"

        # Read existing config
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read config file: {e}, creating new config")
                config = {"knowledge_bases": {}, "default": None}
        else:
            config = {"knowledge_bases": {}, "default": None}

        # Add new knowledge base
        if "knowledge_bases" not in config:
            config["knowledge_bases"] = {}

        if self.kb_name not in config.get("knowledge_bases", {}):
            config["knowledge_bases"][self.kb_name] = {
                "path": self.kb_name,
                "description": f"Knowledge base: {self.kb_name}",
            }

            # If first knowledge base, set as default
            if not config.get("default"):
                config["default"] = self.kb_name

            # Save config
            try:
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, indent=2, ensure_ascii=False, fp=f)
                logger.info("  ✓ Registered to kb_config.json")
            except Exception as e:
                logger.warning(f"Failed to update config file: {e}")
        else:
            logger.info("  ✓ Already registered in kb_config.json")

    def create_directory_structure(self):
        """Create knowledge base directory structure"""
        logger.info(f"Creating directory structure for knowledge base: {self.kb_name}")

        for dir_path in [
            self.raw_dir,
            self.images_dir,
            self.rag_storage_dir,
            self.content_list_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"  ✓ Created: {dir_path}")

        # Create metadata file
        metadata = {
            "name": self.kb_name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": f"Knowledge base: {self.kb_name}",
            "version": "1.0",
        }

        metadata_file = self.kb_dir / "metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, indent=2, ensure_ascii=False, fp=f)

        logger.info(f"  ✓ Created metadata file: {metadata_file}")

        # Automatically register to kb_config.json
        self._register_to_config()

    def copy_documents(self, source_files: list[str]):
        """Copy documents to raw directory"""
        logger.info(f"Copying {len(source_files)} documents to {self.raw_dir}")

        copied_files = []
        for source in source_files:
            source_path = Path(source)
            if not source_path.exists():
                logger.warning(f"  ✗ Source file not found: {source}")
                continue

            dest_path = self.raw_dir / source_path.name
            shutil.copy2(source_path, dest_path)
            copied_files.append(str(dest_path))
            logger.info(f"  ✓ Copied: {source_path.name}")

        return copied_files

    async def process_documents(self):
        """Process documents using RAG-Anything"""
        logger.info("Processing documents with RAG-Anything...")
        self.progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            "Starting to process documents...",
            current=0,
            total=0,
        )

        # Get all documents in raw directory
        doc_files = []
        for ext in ["*.pdf", "*.docx", "*.doc", "*.txt", "*.md"]:
            doc_files.extend(list(self.raw_dir.glob(ext)))

        if not doc_files:
            logger.warning("No documents found to process")
            self.progress_tracker.update(
                ProgressStage.ERROR, "No documents found to process", error="No documents found"
            )
            return

        logger.info(f"Found {len(doc_files)} document(s) to process")
        self.progress_tracker.update(
            ProgressStage.PROCESSING_DOCUMENTS,
            f"Found {len(doc_files)} documents, starting to process...",
            current=0,
            total=len(doc_files),
        )

        # Create RAGAnything configuration
        config = RAGAnythingConfig(
            working_dir=str(self.rag_storage_dir),
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )

        # Get LLM configuration from env_config
        llm_cfg = get_llm_config()
        llm_model = llm_cfg["model"]

        # Define LLM model function
        def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            return openai_complete_if_cache(
                llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=self.api_key,
                base_url=self.base_url,
                **kwargs,
            )

        # Define vision model function for image processing
        def vision_model_func(
            prompt,
            system_prompt=None,
            history_messages=[],
            image_data=None,
            messages=None,
            **kwargs,
        ):
            # If messages format is provided, use it directly
            if messages:
                # Remove 'messages' and other message-related params from kwargs to avoid duplicate parameter
                clean_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k not in ["messages", "prompt", "system_prompt", "history_messages"]
                }
                return openai_complete_if_cache(
                    llm_model,
                    prompt="",  # Empty prompt when using messages
                    system_prompt=None,
                    history_messages=[],
                    messages=messages,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    **clean_kwargs,
                )
            # Traditional single image format
            if image_data:
                # Remove message-related params from kwargs to avoid duplicate parameter
                clean_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k not in ["messages", "prompt", "system_prompt", "history_messages"]
                }
                return openai_complete_if_cache(
                    llm_model,
                    prompt="",  # Empty prompt when using messages
                    system_prompt=None,
                    history_messages=[],
                    messages=[
                        {"role": "system", "content": system_prompt} if system_prompt else None,
                        (
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{image_data}"
                                        },
                                    },
                                ],
                            }
                            if image_data
                            else {"role": "user", "content": prompt}
                        ),
                    ],
                    api_key=self.api_key,
                    base_url=self.base_url,
                    **clean_kwargs,
                )
            # Pure text format
            return llm_model_func(prompt, system_prompt, history_messages, **kwargs)

        # Define embedding function
        embedding_cfg = self.embedding_cfg
        embedding_api_key = embedding_cfg["api_key"] or self.api_key
        embedding_base_url = embedding_cfg["base_url"] or self.base_url
        # Use openai_embed.func to access the unwrapped function
        # This avoids double wrapping issues since openai_embed is already decorated
        # with @wrap_embedding_func_with_attrs(embedding_dim=1536, ...)
        embedding_func = EmbeddingFunc(
            embedding_dim=embedding_cfg["dim"],
            max_token_size=embedding_cfg["max_tokens"],
            func=lambda texts: openai_embed.func(
                texts,
                model=embedding_cfg["model"],
                api_key=embedding_api_key,
                base_url=embedding_base_url,
            ),
        )

        # Initialize RAGAnything with log forwarding
        with LightRAGLogContext(scene="knowledge_init"):
            rag = RAGAnything(
                config=config,
                llm_model_func=llm_model_func,
                vision_model_func=vision_model_func,
                embedding_func=embedding_func,
            )

        # Ensure LightRAG is initialized
        await rag._ensure_lightrag_initialized()

        # Process each document using RAGAnything's process_document_complete
        for idx, doc_file in enumerate(doc_files, 1):
            logger.info(f"\nProcessing: {doc_file.name}")
            self.progress_tracker.update(
                ProgressStage.PROCESSING_FILE,
                f"Processing: {doc_file.name}",
                current=idx,
                total=len(doc_files),
                file_name=doc_file.name,
            )

            try:
                # Use RAGAnything's process_document_complete method
                # This method handles document parsing, content extraction, and insertion
                await rag.process_document_complete(
                    file_path=str(doc_file),
                    output_dir=str(self.content_list_dir),
                    parse_method="auto",
                )
                logger.info(f"  ✓ Successfully processed: {doc_file.name}")

                # Content list should be automatically saved in output_dir
                doc_name = doc_file.stem
                content_list_file = self.content_list_dir / f"{doc_name}.json"
                if content_list_file.exists():
                    logger.info(f"  ✓ Content list saved: {content_list_file.name}")

            except Exception as e:
                error_msg = str(e)
                logger.error(f"  ✗ Error processing {doc_file.name}: {error_msg}")
                import traceback

                logger.error(traceback.format_exc())
                self.progress_tracker.update(
                    ProgressStage.ERROR,
                    f"Failed to process file: {doc_file.name}",
                    current=idx,
                    total=len(doc_files),
                    file_name=doc_file.name,
                    error=error_msg,
                )

        # Copy extracted images
        rag_images_dir = self.rag_storage_dir / "images"
        if rag_images_dir.exists():
            logger.info(f"\nCopying extracted images to {self.images_dir}")
            for img_file in rag_images_dir.glob("*"):
                if img_file.is_file():
                    dest = self.images_dir / img_file.name
                    shutil.copy2(img_file, dest)
            logger.info("  ✓ Copied images")

        logger.info("\n✓ Document processing completed!")

        # Fix structure: flatten nested content_list directories
        await self.fix_structure()

        # Display statistics
        await self.display_statistics(rag)

    async def fix_structure(self):
        """
        Fix the nested structure created by process_document_complete.
        Flattens content_list directories and moves images to the correct location.
        """
        logger.info("\nFixing directory structure...")

        # Find nested content lists
        content_list_moves = []
        for doc_dir in self.content_list_dir.glob("*"):
            if not doc_dir.is_dir():
                continue

            auto_dir = doc_dir / "auto"
            if not auto_dir.exists():
                continue

            # Find the _content_list.json file
            for json_file in auto_dir.glob("*_content_list.json"):
                target_file = self.content_list_dir / f"{doc_dir.name}.json"
                content_list_moves.append((json_file, target_file))

        # Move content list files
        for source, target in content_list_moves:
            try:
                shutil.copy2(source, target)
                logger.info(f"  ✓ Moved: {source.name} -> {target.name}")
            except Exception as e:
                logger.error(f"  ✗ Error moving {source.name}: {e!s}")

        # Find and move nested images
        for doc_dir in self.content_list_dir.glob("*"):
            if not doc_dir.is_dir():
                continue

            auto_dir = doc_dir / "auto"
            if not auto_dir.exists():
                continue

            images_dir = auto_dir / "images"
            if images_dir.exists() and images_dir.is_dir():
                image_count = 0
                # Ensure target directory exists
                self.images_dir.mkdir(parents=True, exist_ok=True)

                for img_file in images_dir.glob("*"):
                    if img_file.is_file() and img_file.exists():
                        target_img = self.images_dir / img_file.name
                        if not target_img.exists():
                            try:
                                # Ensure source file exists
                                if not img_file.exists():
                                    logger.warning(f"  ⚠ Source image not found: {img_file}")
                                    continue
                                shutil.copy2(img_file, target_img)
                                image_count += 1
                            except FileNotFoundError:
                                logger.error(
                                    f"  ✗ Error moving image {img_file.name}: Source file not found: {img_file}"
                                )
                            except Exception as e:
                                logger.error(f"  ✗ Error moving image {img_file.name}: {e!s}")

                if image_count > 0:
                    logger.info(f"  ✓ Moved {image_count} images from {doc_dir.name}/auto/images/")

        # Clean up nested directories
        for doc_dir in self.content_list_dir.glob("*"):
            if doc_dir.is_dir():
                try:
                    shutil.rmtree(doc_dir)
                    logger.info(f"  ✓ Cleaned up: {doc_dir.name}/")
                except Exception as e:
                    logger.error(f"  ✗ Error removing {doc_dir.name}: {e!s}")

        logger.info("✓ Structure fixed!")

    def extract_numbered_items(self, batch_size: int = 20):
        """
        Extract numbered items from knowledge base (Definition, Proposition, Equation, Figure, etc.)

        Args:
            batch_size: Number of items to process per batch
        """
        logger.info("\n" + "=" * 60)
        logger.info("🔍 Starting to extract numbered items...")
        logger.info("=" * 60 + "\n")

        self.progress_tracker.update(
            ProgressStage.EXTRACTING_ITEMS,
            "Starting to extract numbered items...",
            current=0,
            total=0,
        )

        output_file = self.kb_dir / "numbered_items.json"
        content_list_files = sorted(self.content_list_dir.glob("*.json"))

        if not content_list_files:
            logger.warning("No content_list files found, skipping numbered items extraction")
            return

        logger.info(f"Found {len(content_list_files)} content_list files")
        self.progress_tracker.update(
            ProgressStage.EXTRACTING_ITEMS,
            f"Found {len(content_list_files)} files, starting extraction...",
            current=0,
            total=len(content_list_files),
        )

        try:
            # Process all content_list files
            for idx, content_list_file in enumerate(content_list_files, 1):
                logger.info(
                    f"\nProcessing file [{idx}/{len(content_list_files)}]: {content_list_file.name}"
                )
                self.progress_tracker.update(
                    ProgressStage.EXTRACTING_ITEMS,
                    f"Extracting: {content_list_file.name}",
                    current=idx,
                    total=len(content_list_files),
                    file_name=content_list_file.name,
                )

                # First file doesn't merge (creates new file), subsequent files merge into existing results
                merge = idx > 1

                process_content_list(
                    content_list_file=content_list_file,
                    output_file=output_file,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    batch_size=batch_size,
                    merge=merge,
                )

            logger.info(f"\n{'=' * 60}")
            logger.info("✓ Numbered items extraction completed!")
            logger.info(f"Output file: {output_file}")
            logger.info(f"{'=' * 60}\n")

            self.progress_tracker.update(
                ProgressStage.COMPLETED,
                "Knowledge base initialization completed!",
                current=len(content_list_files),
                total=len(content_list_files),
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"\n✗ Numbered items extraction failed: {error_msg}")
            import traceback

            traceback.print_exc()
            self.progress_tracker.update(
                ProgressStage.ERROR, "Numbered items extraction failed", error=error_msg
            )

    async def display_statistics(self, rag: RAGAnything):
        """Display knowledge base statistics"""
        logger.info("\n" + "=" * 50)
        logger.info("Knowledge Base Statistics")
        logger.info("=" * 50)

        # Count files
        raw_files = list(self.raw_dir.glob("*"))
        image_files = list(self.images_dir.glob("*"))
        content_files = list(self.content_list_dir.glob("*.json"))

        logger.info(f"Raw documents: {len(raw_files)}")
        logger.info(f"Extracted images: {len(image_files)}")
        logger.info(f"Content lists: {len(content_files)}")

        # RAG storage info
        if hasattr(rag, "lightrag") and rag.lightrag:
            try:
                # Try to get entity and relation counts
                entities_file = self.rag_storage_dir / "kv_store_full_entities.json"
                relations_file = self.rag_storage_dir / "kv_store_full_relations.json"
                chunks_file = self.rag_storage_dir / "kv_store_text_chunks.json"

                if entities_file.exists():
                    with open(entities_file, encoding="utf-8") as f:
                        entities = json.load(f)
                        logger.info(f"Knowledge entities: {len(entities)}")

                if relations_file.exists():
                    with open(relations_file, encoding="utf-8") as f:
                        relations = json.load(f)
                        logger.info(f"Knowledge relations: {len(relations)}")

                if chunks_file.exists():
                    with open(chunks_file, encoding="utf-8") as f:
                        chunks = json.load(f)
                        logger.info(f"Text chunks: {len(chunks)}")

            except Exception as e:
                logger.warning(f"Could not retrieve statistics: {e!s}")

        logger.info("=" * 50)


async def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Initialize a new knowledge base from documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Initialize new knowledge base from documents (with auto extraction)
  python init_knowledge_base.py my_kb --docs document1.pdf document2.pdf

  # Initialize from a directory
  python init_knowledge_base.py my_kb --docs-dir ./my_documents/

  # Initialize without numbered items extraction
  python init_knowledge_base.py my_kb --docs document.pdf --skip-extract

  # Adjust batch size for extraction (for large knowledge bases)
  python init_knowledge_base.py my_kb --docs document.pdf --batch-size 30
        """,
    )

    parser.add_argument("name", help="Knowledge base name")
    parser.add_argument("--docs", nargs="+", help="Document files to process")
    parser.add_argument("--docs-dir", help="Directory containing documents to process")
    parser.add_argument(
        "--base-dir",
        default="./knowledge_bases",
        help="Base directory for knowledge bases (default: ./knowledge_bases)",
    )
    parser.add_argument(
        "--api-key", default=os.getenv("LLM_BINDING_API_KEY"), help="OpenAI API key"
    )
    parser.add_argument("--base-url", default=os.getenv("LLM_BINDING_HOST"), help="API base URL")
    parser.add_argument(
        "--skip-processing",
        action="store_true",
        help="Skip document processing (only create structure)",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip numbered items extraction after initialization",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Batch size for numbered items extraction (default: 20)",
    )

    args = parser.parse_args()

    # Check API key
    if not args.skip_processing and not args.api_key:
        logger.error("Error: OpenAI API key required")
        logger.error("Set LLM_BINDING_API_KEY environment variable or use --api-key option")
        return

    # Collect document files
    doc_files = []
    if args.docs:
        doc_files.extend(args.docs)

    if args.docs_dir:
        docs_dir = Path(args.docs_dir)
        if docs_dir.exists() and docs_dir.is_dir():
            for ext in ["*.pdf", "*.docx", "*.doc", "*.txt", "*.md"]:
                doc_files.extend([str(f) for f in docs_dir.glob(ext)])
        else:
            logger.error(f"Error: Documents directory not found: {args.docs_dir}")
            return

    if not args.skip_processing and not doc_files:
        logger.error("Error: No documents specified")
        logger.error("Use --docs or --docs-dir to specify documents")
        return

    # Initialize knowledge base
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Initializing Knowledge Base: {args.name}")
    logger.info(f"{'=' * 60}\n")

    initializer = KnowledgeBaseInitializer(
        kb_name=args.name, base_dir=args.base_dir, api_key=args.api_key, base_url=args.base_url
    )

    # Create directory structure
    initializer.create_directory_structure()

    # Copy documents
    if doc_files:
        copied_files = initializer.copy_documents(doc_files)
        logger.info(f"\nCopied {len(copied_files)} file(s) to raw directory")

    # Process documents
    if not args.skip_processing:
        await initializer.process_documents()
    else:
        logger.info("\nSkipping document processing (--skip-processing specified)")

    # Extract numbered items (automatically after processing)
    if not args.skip_processing and not args.skip_extract:
        initializer.extract_numbered_items(batch_size=args.batch_size)
    elif args.skip_extract:
        logger.info("\nSkipping numbered items extraction (--skip-extract specified)")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"✓ Knowledge base '{args.name}' initialized successfully!")
    logger.info(f"Location: {initializer.kb_dir}")
    logger.info(f"{'=' * 60}\n")


if __name__ == "__main__":
    # Logging configuration already completed during module import, no need to configure again here
    asyncio.run(main())
