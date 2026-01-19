# -*- coding: utf-8 -*-
"""
Image Migration Utilities
=========================

Utilities for migrating images from parser output directories to the canonical
knowledge base images directory, and updating content_list paths accordingly.

This is needed because:
1. Parsers (MinerU/Docling) output images to nested directories like:
   content_list/{doc}/auto/images/ or content_list/{doc}/docling/images/
2. RAG stores these paths in chunks, so if we move files later, retrieval breaks
3. By migrating images BEFORE RAG indexing, we ensure correct paths are stored
"""

import asyncio
from pathlib import Path
import shutil
from typing import Any, Dict, List, Tuple

from src.logging import get_logger

logger = get_logger("ImageMigration")

# Maximum concurrent file operations to avoid overwhelming I/O
MAX_CONCURRENT_COPIES = 10


async def migrate_images_and_update_paths(
    content_list: List[Dict[str, Any]],
    source_base_dir: Path,
    target_images_dir: Path,
    batch_size: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Migrate images from parser output to canonical images directory and update paths.

    This function:
    1. Scans content_list for image paths
    2. Copies images to target_images_dir (with deduplication)
    3. Updates content_list with new paths
    4. Returns updated content_list

    Args:
        content_list: Parsed content list from MinerU/Docling
        source_base_dir: Base directory where parser outputs are located
        target_images_dir: Canonical images directory (e.g., kb/images/)
        batch_size: Number of images to process in each batch

    Returns:
        Tuple of (updated_content_list, num_images_migrated)
    """
    # Ensure target directory exists
    target_images_dir.mkdir(parents=True, exist_ok=True)

    # Collect all image items that need migration
    image_items = []
    for idx, item in enumerate(content_list):
        if not isinstance(item, dict):
            continue

        # Check for image path in various fields
        img_path = item.get("img_path") or item.get("image_path")
        if img_path:
            image_items.append((idx, img_path, "img_path" if "img_path" in item else "image_path"))

    if not image_items:
        logger.debug("No images found in content_list, skipping migration")
        return content_list, 0

    logger.info(f"Found {len(image_items)} images to migrate")

    # Process images in batches to handle large quantities
    migrated_count = 0
    path_updates = {}  # old_path -> new_path mapping

    for batch_start in range(0, len(image_items), batch_size):
        batch = image_items[batch_start : batch_start + batch_size]
        batch_updates = await _process_image_batch(batch, source_base_dir, target_images_dir)
        path_updates.update(batch_updates)
        migrated_count += len([v for v in batch_updates.values() if v])

        if batch_start + batch_size < len(image_items):
            logger.info(f"Migrated {batch_start + len(batch)}/{len(image_items)} images...")

    # Update content_list with new paths
    updated_content_list = _update_content_list_paths(content_list, path_updates)

    logger.info(f"Image migration complete: {migrated_count} images migrated")
    return updated_content_list, migrated_count


async def _process_image_batch(
    batch: List[Tuple[int, str, str]],
    source_base_dir: Path,
    target_images_dir: Path,
) -> Dict[str, str]:
    """
    Process a batch of images concurrently.

    Args:
        batch: List of (index, image_path, field_name) tuples
        source_base_dir: Base directory for resolving relative paths
        target_images_dir: Target directory for images

    Returns:
        Dict mapping old paths to new paths
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_COPIES)

    async def copy_single_image(idx: int, img_path: str, field_name: str) -> Tuple[str, str]:
        async with semaphore:
            return await _migrate_single_image(img_path, source_base_dir, target_images_dir)

    tasks = [copy_single_image(idx, img_path, field_name) for idx, img_path, field_name in batch]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    path_updates = {}
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Error migrating image: {result}")
            continue
        old_path, new_path = result
        if new_path:
            path_updates[old_path] = new_path

    return path_updates


async def _migrate_single_image(
    img_path: str,
    source_base_dir: Path,
    target_images_dir: Path,
) -> Tuple[str, str]:
    """
    Migrate a single image file.

    Args:
        img_path: Original image path (may be absolute or relative)
        source_base_dir: Base directory for resolving relative paths
        target_images_dir: Target directory for images

    Returns:
        Tuple of (original_path, new_path) or (original_path, None) if failed
    """
    try:
        # Resolve the source path
        source_path = Path(img_path)
        if not source_path.is_absolute():
            source_path = source_base_dir / img_path

        if not source_path.exists():
            logger.warning(f"Source image not found: {img_path}")
            return (img_path, None)

        # Generate target filename (preserve original name)
        target_filename = source_path.name
        target_path = target_images_dir / target_filename

        # Handle filename conflicts by adding suffix
        if target_path.exists():
            # Check if it's the same file (by size)
            if target_path.stat().st_size == source_path.stat().st_size:
                # Same file already exists, just update path
                return (img_path, str(target_path))

            # Different file with same name, add suffix
            stem = source_path.stem
            suffix = source_path.suffix
            counter = 1
            while target_path.exists():
                target_filename = f"{stem}_{counter}{suffix}"
                target_path = target_images_dir / target_filename
                counter += 1

        # Copy file using thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, shutil.copy2, str(source_path), str(target_path))

        logger.debug(f"Migrated: {source_path.name} -> {target_path}")
        return (img_path, str(target_path))

    except Exception as e:
        logger.error(f"Failed to migrate image {img_path}: {e}")
        return (img_path, None)


def _update_content_list_paths(
    content_list: List[Dict[str, Any]],
    path_updates: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Update image paths in content_list with new paths.

    Args:
        content_list: Original content list
        path_updates: Mapping of old paths to new paths

    Returns:
        Updated content list (new list, original is not modified)
    """
    updated_list = []

    for item in content_list:
        if not isinstance(item, dict):
            updated_list.append(item)
            continue

        # Create a copy of the item
        updated_item = dict(item)

        # Update img_path if present
        if "img_path" in updated_item:
            old_path = updated_item["img_path"]
            if old_path in path_updates and path_updates[old_path]:
                updated_item["img_path"] = path_updates[old_path]

        # Update image_path if present (alternative field name)
        if "image_path" in updated_item:
            old_path = updated_item["image_path"]
            if old_path in path_updates and path_updates[old_path]:
                updated_item["image_path"] = path_updates[old_path]

        updated_list.append(updated_item)

    return updated_list


async def cleanup_parser_output_dirs(
    content_list_dir: Path,
    parser_subdirs: List[str] = None,
) -> int:
    """
    Clean up parser output directories after successful migration.

    Only removes the nested parser output directories (auto/, docling/),
    NOT the content_list JSON files at the root level.

    Args:
        content_list_dir: The content_list directory
        parser_subdirs: List of parser subdirectory names to clean

    Returns:
        Number of directories cleaned up
    """
    if parser_subdirs is None:
        parser_subdirs = ["auto", "docling"]

    cleaned_count = 0

    for doc_dir in content_list_dir.glob("*"):
        if not doc_dir.is_dir():
            continue

        for parser_subdir in parser_subdirs:
            subdir = doc_dir / parser_subdir
            if subdir.exists():
                try:
                    # Run in thread pool to avoid blocking
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, shutil.rmtree, str(subdir))
                    cleaned_count += 1
                    logger.debug(f"Cleaned up: {subdir}")
                except Exception as e:
                    logger.warning(f"Failed to clean up {subdir}: {e}")

        # Remove the doc_dir if it's now empty
        try:
            if doc_dir.exists() and not any(doc_dir.iterdir()):
                doc_dir.rmdir()
                logger.debug(f"Removed empty directory: {doc_dir}")
        except Exception as e:
            logger.debug(f"Could not remove directory {doc_dir}: {e}")

    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} parser output directories")

    return cleaned_count
