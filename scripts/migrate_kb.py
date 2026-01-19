#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Knowledge Base Migration Script
===============================

Migrate existing knowledge bases into DeepTutor's knowledge base system.

Features:
- Auto-detect RAG provider type (LlamaIndex or LightRAG/RAGAnything)
- Validate required index files
- Copy/migrate KB to target directory
- Register in kb_config.json
- Optionally extract numbered items (if content_list exists)
- Run test query to verify migration

Usage:
    python scripts/migrate_kb.py /path/to/kb --name my_kb --test --extract-items
    python scripts/migrate_kb.py /path/to/kb --validate-only
"""

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# Constants: Required files for each RAG provider
# =============================================================================

LLAMAINDEX_REQUIRED_FILES = [
    "docstore.json",
    "index_store.json",
    "default__vector_store.json",
]

LIGHTRAG_REQUIRED_FILES = [
    "kv_store_text_chunks.json",
    "kv_store_full_entities.json",
    "kv_store_full_relations.json",
]

# Optional but recommended for better performance
LIGHTRAG_OPTIONAL_FILES = [
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
    "graph_chunk_entity_relation.graphml",
]

# Default target directory
DEFAULT_KB_BASE_DIR = PROJECT_ROOT / "data" / "knowledge_bases"


# =============================================================================
# Validation Functions
# =============================================================================


def detect_provider(kb_path: Path) -> str | None:
    """
    Detect the RAG provider type based on directory structure and valid files.

    Args:
        kb_path: Path to the knowledge base directory

    Returns:
        Provider name: "llamaindex", "lightrag", or None if not detected
    """
    llamaindex_dir = kb_path / "llamaindex_storage"
    lightrag_dir = kb_path / "rag_storage"

    has_llamaindex = llamaindex_dir.exists() and llamaindex_dir.is_dir()
    has_lightrag = lightrag_dir.exists() and lightrag_dir.is_dir()

    # Check which one has valid index files
    llamaindex_valid = False
    lightrag_valid = False

    if has_llamaindex:
        # Check if LlamaIndex has required files
        llamaindex_valid = all((llamaindex_dir / f).exists() for f in LLAMAINDEX_REQUIRED_FILES)

    if has_lightrag:
        # Check if LightRAG has required files
        lightrag_valid = all((lightrag_dir / f).exists() for f in LIGHTRAG_REQUIRED_FILES)

    # Return based on which has valid files
    if llamaindex_valid and lightrag_valid:
        # Both valid, prefer LightRAG (more feature-rich)
        return "lightrag"
    elif lightrag_valid:
        return "lightrag"
    elif llamaindex_valid:
        return "llamaindex"
    elif has_llamaindex:
        # Directory exists but incomplete
        return "llamaindex"
    elif has_lightrag:
        # Directory exists but incomplete
        return "lightrag"
    else:
        return None


def validate_llamaindex_files(storage_dir: Path) -> tuple[bool, list[str], list[str]]:
    """
    Validate LlamaIndex storage has required files.

    Args:
        storage_dir: Path to llamaindex_storage directory

    Returns:
        Tuple of (is_valid, missing_files, found_files)
    """
    missing = []
    found = []

    for filename in LLAMAINDEX_REQUIRED_FILES:
        filepath = storage_dir / filename
        if filepath.exists():
            found.append(filename)
        else:
            missing.append(filename)

    return len(missing) == 0, missing, found


def validate_lightrag_files(storage_dir: Path) -> tuple[bool, list[str], list[str]]:
    """
    Validate LightRAG storage has required files.

    Args:
        storage_dir: Path to rag_storage directory

    Returns:
        Tuple of (is_valid, missing_files, found_files)
    """
    missing = []
    found = []

    for filename in LIGHTRAG_REQUIRED_FILES:
        filepath = storage_dir / filename
        if filepath.exists():
            found.append(filename)
        else:
            missing.append(filename)

    # Also check optional files
    optional_found = []
    for filename in LIGHTRAG_OPTIONAL_FILES:
        if (storage_dir / filename).exists():
            optional_found.append(filename)

    return len(missing) == 0, missing, found + optional_found


def validate_kb(kb_path: Path) -> dict:
    """
    Validate a knowledge base directory.

    Args:
        kb_path: Path to the knowledge base directory

    Returns:
        Validation result dictionary
    """
    result = {
        "path": str(kb_path),
        "exists": kb_path.exists(),
        "is_valid": False,
        "provider": None,
        "missing_files": [],
        "found_files": [],
        "has_content_list": False,
        "has_raw_docs": False,
        "has_images": False,
        "has_metadata": False,
        "has_numbered_items": False,
    }

    if not kb_path.exists():
        return result

    # Detect provider
    provider = detect_provider(kb_path)
    result["provider"] = provider

    if provider is None:
        result["error"] = (
            "No valid RAG storage found (neither llamaindex_storage/ nor rag_storage/)"
        )
        return result

    # Validate based on provider
    if provider == "llamaindex":
        storage_dir = kb_path / "llamaindex_storage"
        is_valid, missing, found = validate_llamaindex_files(storage_dir)
    else:  # lightrag
        storage_dir = kb_path / "rag_storage"
        is_valid, missing, found = validate_lightrag_files(storage_dir)

    result["is_valid"] = is_valid
    result["missing_files"] = missing
    result["found_files"] = found

    # Check optional directories
    content_list_dir = kb_path / "content_list"
    result["has_content_list"] = content_list_dir.exists() and any(content_list_dir.glob("*.json"))

    raw_dir = kb_path / "raw"
    result["has_raw_docs"] = raw_dir.exists() and any(raw_dir.iterdir())

    images_dir = kb_path / "images"
    result["has_images"] = images_dir.exists() and any(images_dir.iterdir())

    result["has_metadata"] = (kb_path / "metadata.json").exists()
    result["has_numbered_items"] = (kb_path / "numbered_items.json").exists()

    return result


# =============================================================================
# Migration Functions
# =============================================================================


def copy_kb_directory(source_path: Path, target_path: Path, verbose: bool = True) -> bool:
    """
    Copy knowledge base directory to target location.

    Args:
        source_path: Source KB directory
        target_path: Target KB directory
        verbose: Print progress messages

    Returns:
        True if successful
    """
    if target_path.exists():
        if verbose:
            print(f"  ⚠️  Target directory already exists: {target_path}")
        return False

    if verbose:
        print(f"  Copying {source_path} -> {target_path}")

    shutil.copytree(source_path, target_path)

    if verbose:
        print("  ✓ Copied successfully")

    return True


def register_kb(
    kb_name: str, kb_base_dir: Path, description: str = "", provider: str | None = None
) -> bool:
    """
    Register knowledge base in kb_config.json.

    Args:
        kb_name: Knowledge base name
        kb_base_dir: Base directory containing kb_config.json
        description: Optional description
        provider: RAG provider name

    Returns:
        True if successful
    """
    config_file = kb_base_dir / "kb_config.json"

    # Load existing config
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {"knowledge_bases": {}}

    if "knowledge_bases" not in config:
        config["knowledge_bases"] = {}

    # Check if already registered
    if kb_name in config["knowledge_bases"]:
        print(f"  ⚠️  KB '{kb_name}' is already registered in kb_config.json")
        return True

    # Add to config
    config["knowledge_bases"][kb_name] = {
        "path": kb_name,
        "description": description or f"Knowledge base: {kb_name}",
    }

    # Save config
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"  ✓ Registered '{kb_name}' in kb_config.json")

    # Also create/update metadata.json if needed
    kb_dir = kb_base_dir / kb_name
    metadata_file = kb_dir / "metadata.json"

    if not metadata_file.exists():
        metadata = {
            "name": kb_name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": description or f"Knowledge base: {kb_name}",
            "version": "1.0",
            "rag_provider": provider,
            "migrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print("  ✓ Created metadata.json")
    else:
        # Update existing metadata with migration info
        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)

        if provider and not metadata.get("rag_provider"):
            metadata["rag_provider"] = provider
        metadata["migrated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print("  ✓ Updated metadata.json")

    return True


async def extract_numbered_items(kb_name: str, kb_base_dir: Path) -> bool:
    """
    Extract numbered items from content_list files.

    Args:
        kb_name: Knowledge base name
        kb_base_dir: Base directory for knowledge bases

    Returns:
        True if successful
    """
    try:
        from src.knowledge.extract_numbered_items import (
            extract_numbered_items_with_llm_async,
        )
        from src.services.llm import get_llm_client
    except ImportError as e:
        print(f"  ⚠️  Could not import extraction module: {e}")
        return False

    kb_dir = kb_base_dir / kb_name
    content_list_dir = kb_dir / "content_list"

    if not content_list_dir.exists():
        print("  ⚠️  No content_list directory found")
        return False

    # Load all content list files
    all_content_items = []
    json_files = list(content_list_dir.glob("*.json"))

    if not json_files:
        print("  ⚠️  No JSON files found in content_list/")
        return False

    print(f"  Loading {len(json_files)} content list files...")

    for json_file in json_files:
        try:
            with open(json_file, encoding="utf-8") as f:
                content_items = json.load(f)
                if isinstance(content_items, list):
                    all_content_items.extend(content_items)
        except Exception as e:
            print(f"  ⚠️  Error loading {json_file.name}: {e}")

    if not all_content_items:
        print("  ⚠️  No content items found")
        return False

    print(f"  Extracting numbered items from {len(all_content_items)} content items...")

    try:
        llm_client = get_llm_client()
        items = await extract_numbered_items_with_llm_async(
            all_content_items,
            api_key=llm_client.config.api_key,
            base_url=llm_client.config.base_url,
        )

        if items:
            output_file = kb_dir / "numbered_items.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Extracted {len(items)} numbered items")
            return True
        else:
            print("  ⚠️  No numbered items extracted")
            return False

    except Exception as e:
        print(f"  ✗ Extraction failed: {e}")
        return False


async def test_kb_search(kb_name: str, query: str = "What is this knowledge base about?") -> bool:
    """
    Test knowledge base with a simple search query.

    Args:
        kb_name: Knowledge base name
        query: Test query

    Returns:
        True if search succeeded
    """
    try:
        from src.tools.rag_tool import rag_search
    except ImportError as e:
        print(f"  ⚠️  Could not import rag_tool: {e}")
        return False

    print(f"  Running test query: '{query[:50]}...'")

    try:
        result = await rag_search(
            query=query,
            kb_name=kb_name,
            mode="naive",  # Use simplest mode for testing
        )

        if result and result.get("answer"):
            answer_preview = result["answer"][:200]
            print("  ✓ Search successful!")
            print(f"    Provider: {result.get('provider', 'unknown')}")
            print(f"    Answer preview: {answer_preview}...")
            return True
        else:
            print("  ⚠️  Search returned empty result")
            return False

    except Exception as e:
        print(f"  ✗ Search failed: {e}")
        return False


async def migrate_kb(
    source_path: str,
    target_base_dir: str | None = None,
    kb_name: str | None = None,
    run_test: bool = False,
    extract_items: bool = False,
    validate_only: bool = False,
    force: bool = False,
) -> bool:
    """
    Migrate a knowledge base to DeepTutor.

    Args:
        source_path: Path to source knowledge base
        target_base_dir: Target base directory (default: data/knowledge_bases)
        kb_name: Name for the migrated KB (default: source directory name)
        run_test: Run a test query after migration
        extract_items: Extract numbered items if content_list exists
        validate_only: Only validate, don't migrate
        force: Overwrite existing KB if exists

    Returns:
        True if successful
    """
    source = Path(source_path).resolve()
    target_base = Path(target_base_dir) if target_base_dir else DEFAULT_KB_BASE_DIR
    target_base = target_base.resolve()

    # Determine KB name
    if kb_name is None:
        kb_name = source.name

    print("=" * 60)
    print("Knowledge Base Migration")
    print("=" * 60)
    print(f"Source: {source}")
    print(f"Target: {target_base / kb_name}")
    print()

    # Step 1: Validate source KB
    print("Step 1: Validating source knowledge base...")
    validation = validate_kb(source)

    if not validation["exists"]:
        print(f"  ✗ Source directory does not exist: {source}")
        return False

    if not validation["is_valid"]:
        print("  ✗ Validation failed!")
        if validation.get("error"):
            print(f"    Error: {validation['error']}")
        if validation["missing_files"]:
            print(f"    Missing files: {', '.join(validation['missing_files'])}")
        return False

    print("  ✓ Validation passed")
    print(f"    Provider: {validation['provider']}")
    print(f"    Found files: {', '.join(validation['found_files'][:5])}...")
    print(f"    Has content_list: {'Yes' if validation['has_content_list'] else 'No'}")
    print(f"    Has raw docs: {'Yes' if validation['has_raw_docs'] else 'No'}")
    print(f"    Has images: {'Yes' if validation['has_images'] else 'No'}")
    print()

    if validate_only:
        print("Validation-only mode. Exiting.")
        return True

    # Step 2: Copy to target
    print("Step 2: Copying knowledge base...")
    target_path = target_base / kb_name

    if target_path.exists():
        if force:
            print("  Removing existing directory (--force)...")
            shutil.rmtree(target_path)
        elif source.resolve() == target_path.resolve():
            print("  Source and target are the same. Skipping copy.")
        else:
            print(f"  ✗ Target directory already exists: {target_path}")
            print("    Use --force to overwrite or --name to specify a different name")
            return False

    if source.resolve() != target_path.resolve():
        success = copy_kb_directory(source, target_path)
        if not success:
            return False
    print()

    # Step 3: Register in kb_config.json
    print("Step 3: Registering knowledge base...")
    register_kb(
        kb_name=kb_name,
        kb_base_dir=target_base,
        description=f"Migrated from: {source}",
        provider=validation["provider"],
    )
    print()

    # Step 4: Extract numbered items (optional)
    if extract_items and validation["has_content_list"]:
        print("Step 4: Extracting numbered items...")
        await extract_numbered_items(kb_name, target_base)
        print()
    elif extract_items:
        print("Step 4: Skipping numbered items extraction (no content_list)")
        print()

    # Step 5: Test search (optional)
    if run_test:
        print("Step 5: Testing knowledge base...")
        await test_kb_search(kb_name)
        print()

    print("=" * 60)
    print("✓ Migration complete!")
    print(f"  Knowledge base '{kb_name}' is now available in DeepTutor.")
    print("=" * 60)

    return True


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Migrate knowledge bases into DeepTutor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate a knowledge base
  python scripts/migrate_kb.py /path/to/my_kb

  # Migrate with custom name
  python scripts/migrate_kb.py /path/to/kb --name my_textbook

  # Migrate and run test query
  python scripts/migrate_kb.py /path/to/kb --test

  # Migrate and extract numbered items
  python scripts/migrate_kb.py /path/to/kb --extract-items

  # Validate only (don't migrate)
  python scripts/migrate_kb.py /path/to/kb --validate-only

  # Force overwrite existing KB
  python scripts/migrate_kb.py /path/to/kb --force
""",
    )

    parser.add_argument("source", help="Path to source knowledge base directory")

    parser.add_argument(
        "--name", help="Name for the migrated knowledge base (default: source directory name)"
    )

    parser.add_argument(
        "--target-dir", help=f"Target base directory (default: {DEFAULT_KB_BASE_DIR})"
    )

    parser.add_argument("--test", action="store_true", help="Run a test query after migration")

    parser.add_argument(
        "--extract-items",
        action="store_true",
        help="Extract numbered items from content_list (requires LLM API)",
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the knowledge base, don't migrate",
    )

    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing knowledge base if exists"
    )

    args = parser.parse_args()

    # Run migration
    success = asyncio.run(
        migrate_kb(
            source_path=args.source,
            target_base_dir=args.target_dir,
            kb_name=args.name,
            run_test=args.test,
            extract_items=args.extract_items,
            validate_only=args.validate_only,
            force=args.force,
        )
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
