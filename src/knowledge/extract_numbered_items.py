#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extract numbered important content from knowledge base content_list
Such as: Definition 1.5., Proposition 1.3., Theorem x.x., Equation x.x., Formula x.x., etc.

Use LLM to identify these contents and store the mapping between numbers and original text in JSON file
"""

import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

from src.services.llm import get_llm_client, get_llm_config

load_dotenv(dotenv_path=".env", override=False)

# Use project unified logging system
import logging as std_logging

# Logger can be either custom Logger or standard logging.Logger
logger: Any  # Use Any to allow both types

try:
    from pathlib import Path

    from src.logging import get_logger
    from src.services.config import load_config_with_main

    project_root = Path(__file__).parent.parent.parent.parent
    config = load_config_with_main(
        "solve_config.yaml", project_root
    )  # Use any config to get main.yaml
    log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get(
        "log_dir"
    )
    logger = get_logger("Knowledge", log_dir=log_dir)
except ImportError:
    # If import fails, use basic logging
    logger = std_logging.getLogger("knowledge_init.extract_items")
    std_logging.basicConfig(
        level=std_logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )


async def _call_llm_async(
    prompt: str,
    system_prompt: str,
    api_key: str,
    base_url: str | None,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    model: str = None,
) -> str:
    """Asynchronously call LLM using unified LLM service"""
    # Get unified LLM client (handles all provider differences and env var setup)
    llm_client = get_llm_client()
    llm_model_func = llm_client.get_model_func()

    # If model not specified, use configured model
    if model is None:
        model = llm_client.config.model

    result = llm_model_func(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if inspect.isawaitable(result):
        return await result
    return str(result)


def _extract_json_block(text: str) -> str:
    """Extract JSON block from text"""
    try:
        s = str(text).strip()
        # Remove code block markers
        if s.startswith("```") and s.endswith("```"):
            lines = s.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()

        # Try to extract JSON object or array
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            return s

        o_start, o_end = s.find("{"), s.rfind("}")
        a_start, a_end = s.find("["), s.rfind("]")

        candidates = []
        if o_start != -1 and o_end != -1 and o_end > o_start:
            candidates.append((o_start, s[o_start : o_end + 1]))
        if a_start != -1 and a_end != -1 and a_end > a_start:
            candidates.append((a_start, s[a_start : a_end + 1]))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        return s
    except Exception:
        return text


async def _check_content_belongs_async(
    start_text: str, candidate_text: str, api_key: str, base_url: str | None
) -> bool:
    """
    Use LLM to determine if candidate content belongs to (is part of) the starting content

    Args:
        start_text: Starting content (beginning part of numbered item)
        candidate_text: Candidate content (subsequent content block)
        api_key: OpenAI API key
        base_url: API base URL

    Returns:
        True means candidate content belongs to starting content, False means it's new independent content
    """
    system_prompt = """You are an expert at analyzing the structure of academic mathematical texts.
Your task is to determine if a candidate text block belongs to (is a continuation of) a starting numbered item, or if it's a new independent item.

Numbered items include: Definitions, Propositions, Theorems, Lemmas, Corollaries, Examples, Remarks, Figures, Equations, etc.

Rules:
- Equations, formulas, and images that follow a numbered item usually belong to that item
- Explanatory text that continues the same topic belongs to the item
- A new numbered item (starting with "Definition X.Y", "Theorem X.Y", etc.) is independent
- Text that starts a completely different topic is independent

Return ONLY "YES" if the candidate belongs to the starting item, or "NO" if it's independent."""

    user_prompt = f"""Starting item:
{start_text[:500]}

Candidate block:
{candidate_text[:300]}

Does the candidate block belong to (continue) the starting item?
Answer with ONLY "YES" or "NO"."""

    try:
        llm_cfg = get_llm_config()
        response = await _call_llm_async(
            user_prompt,
            system_prompt,
            api_key,
            base_url,
            max_tokens=10,
            temperature=0.0,
            model=llm_cfg.model,
        )
        answer = response.strip().upper()
        return answer == "YES"
    except Exception as e:
        logger.warning(f"LLM judgment failed, default to not include: {e}")
        # Default to conservative strategy: don't include
        return False


async def _get_complete_content_async(
    content_items: list[dict[str, Any]],
    start_index: int,
    api_key: str,
    base_url: str | None,
    max_following: int = 5,
) -> tuple[str, list[str]]:
    """
    Get complete content, including subsequent formulas, text, etc., and all related image paths
    Use LLM to determine if subsequent content belongs to current numbered item

    Args:
        content_items: Complete content_list
        start_index: Starting index
        api_key: OpenAI API key
        base_url: API base URL
        max_following: Maximum number of subsequent entries to check

    Returns:
        (Complete text content, image path list)
    """
    complete_text = content_items[start_index].get("text", "")
    img_paths = []

    # Collect image paths from starting item
    start_img_path = content_items[start_index].get("img_path", "")
    if start_img_path:
        img_paths.append(start_img_path)

    logger.debug(
        f"Starting to use LLM to determine content boundaries, starting text (first 50 chars): {complete_text[:50]}..."
    )

    # Check subsequent entries
    for i in range(1, max_following + 1):
        next_index = start_index + i
        if next_index >= len(content_items):
            break

        next_item = content_items[next_index]
        next_type = next_item.get("type", "")

        # If encountering title-level text, definitely stop
        if next_type == "text" and next_item.get("text_level", 0) > 0:
            break

        # If it's a formula, usually belongs to current content, add directly
        if next_type == "equation":
            equation_text = next_item.get("text", "")
            if equation_text:
                complete_text += " " + equation_text
            # Collect formula image paths
            eq_img_path = next_item.get("img_path", "")
            if eq_img_path:
                img_paths.append(eq_img_path)
        # If it's an image, collect image paths
        elif next_type == "image":
            img_path = next_item.get("img_path", "")
            if img_path:
                img_paths.append(img_path)
            # Can also add image captions to text
            captions = next_item.get("image_caption", [])
            if captions:
                caption_text = " ".join(captions) if isinstance(captions, list) else str(captions)
                complete_text += " " + caption_text
        # If it's regular text, use LLM to judge
        elif next_type == "text" and next_item.get("text_level", 0) == 0:
            next_text = next_item.get("text", "").strip()
            if not next_text:
                continue

            # Use LLM to determine if this text belongs to current numbered item
            belongs = await _check_content_belongs_async(
                complete_text, next_text, api_key, base_url
            )

            if belongs:
                complete_text += " " + next_text
                logger.debug(
                    f"LLM judgment: Subsequent text belongs to current content, added (first 30 chars: {next_text[:30]}...)"
                )
            else:
                # Doesn't belong to current content, stop collecting
                logger.debug(
                    f"LLM judgment: Subsequent text doesn't belong to current content, stop collecting (first 30 chars: {next_text[:30]}...)"
                )
                break

    return complete_text.strip(), img_paths


def _get_complete_content(
    content_items: list[dict[str, Any]],
    start_index: int,
    api_key: str,
    base_url: str | None,
    max_following: int = 5,
) -> tuple[str, list[str]]:
    """
    Synchronous wrapper for async function to get complete content
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If event loop is already running, check if it's uvloop
            loop_type = type(loop).__name__
            if "uvloop" in loop_type.lower():
                # uvloop doesn't support nest_asyncio, use threading approach
                import concurrent.futures

                def run_in_new_loop():
                    # Create a new asyncio event loop in a new thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            _get_complete_content_async(
                                content_items, start_index, api_key, base_url, max_following
                            )
                        )
                    finally:
                        new_loop.close()

                # Run in a thread with a new event loop
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_new_loop)
                    return future.result()
            else:
                # Try nest_asyncio for standard event loops
                try:
                    import nest_asyncio

                    nest_asyncio.apply()
                    return loop.run_until_complete(
                        _get_complete_content_async(
                            content_items, start_index, api_key, base_url, max_following
                        )
                    )
                except (ValueError, TypeError) as e:
                    # nest_asyncio failed, fall back to threading approach
                    logger.debug(f"nest_asyncio failed ({e}), using threading fallback")
                    import concurrent.futures

                    def run_in_new_loop():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            return new_loop.run_until_complete(
                                _get_complete_content_async(
                                    content_items, start_index, api_key, base_url, max_following
                                )
                            )
                        finally:
                            new_loop.close()

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(run_in_new_loop)
                        return future.result()
        else:
            return loop.run_until_complete(
                _get_complete_content_async(
                    content_items, start_index, api_key, base_url, max_following
                )
            )
    except RuntimeError:
        # No event loop, create new one
        return asyncio.run(
            _get_complete_content_async(
                content_items, start_index, api_key, base_url, max_following
            )
        )


async def _process_single_batch(
    batch_idx: int,
    batch: list[dict[str, Any]],
    batch_start: int,
    content_items: list[dict[str, Any]],
    text_item_to_full_index: dict[int, int],
    api_key: str,
    base_url: str | None,
    total_batches: int,
) -> dict[str, dict[str, Any]]:
    """Asynchronously process a single batch"""
    numbered_items: dict[str, dict[str, Any]] = {}

    # Build batch processing text
    batch_texts = []
    for idx, item in enumerate(batch):
        batch_texts.append(f"[{batch_start + idx}] {item.get('text', '')}")

    combined_text = "\n\n".join(batch_texts)

    system_prompt = """You are an expert at identifying numbered mathematical and scientific content in academic texts.
You need to extract items like:
- Definitions (e.g., "Definition 1.5.", "Definition 1.1")
- Propositions (e.g., "Proposition 1.3.")
- Theorems (e.g., "Theorem 2.1.")
- Lemmas (e.g., "Lemma 3.2.")
- Corollaries (e.g., "Corollary 1.4.")
- Examples (e.g., "Example 2.3.")
- Remarks (e.g., "Remark 1.6.")
- Figures (e.g., "Figure 1.1", "Fig. 2.3")
- Equations (formulas with \\tag{x.y.z})
- Tables (e.g., "Table 1.1")

Note: Do NOT extract section titles or headings.

IMPORTANT:
- For equations with tags like \\tag{1.2.1}, extract identifier as "(1.2.1)" (only the number in parentheses)
- For figures, extract the figure number from the caption
- Return ONLY a valid JSON array
- Ensure all backslashes in LaTeX formulas are properly escaped (use \\\\ instead of \\)."""

    user_prompt = f"""Analyze the following text segments and extract all numbered items (definitions, propositions, theorems, lemmas, corollaries, examples, remarks, figures, equations, tables, etc.).

Each segment starts with [N] where N is the segment index number.

For each numbered item found, extract:
1. The index number N from the brackets [N] at the start of that segment
2. The identifier (e.g., "Definition 1.5", "Figure 1.1", "(1.2.1)")
3. The item type (e.g., "Definition", "Proposition", "Theorem", "Figure", "Equation", "Table")
4. The complete text of that item

Special cases:
- For equations with \\tag{{x.y.z}}, extract identifier as "(x.y.z)" - ONLY the number in parentheses, no "Equation" prefix
- For figures, extract the figure number from captions like "Figure 1.1: ..."
- For tables, extract table numbers like "Table 2.1"

Return a JSON array of objects with this structure:
[
  {{
    "index": 152,
    "identifier": "Figure 1.1",
    "type": "Figure",
    "full_text": "Figure 1.1: Evolution of phylogenetic intelligence..."
  }},
  {{
    "index": 185,
    "identifier": "(1.2.1)",
    "type": "Equation",
    "full_text": "$$S = 1,2,3,4,5,6,\\\\ldots ,n,n + 1,\\\\ldots \\\\tag{{1.2.1}}$$"
  }},
  ...
]

CRITICAL REQUIREMENTS:
- The "index" field MUST be the number N from [N] in brackets, NOT a relative position
- For equations, identifier must be ONLY "(x.y.z)" format, not "Equation (x.y.z)"
- Ensure all backslashes in LaTeX are properly escaped for JSON (double them: \\\\ instead of \\).

Text segments:
{combined_text}

Return ONLY the JSON array, no other text. Ensure it is valid JSON."""

    # Asynchronously call LLM
    try:
        llm_cfg = get_llm_config()
        response = await _call_llm_async(
            user_prompt,
            system_prompt,
            api_key,
            base_url,
            max_tokens=4000,
            temperature=0.1,
            model=llm_cfg.model,
        )

        # Parse response
        json_str = _extract_json_block(response)
        # Try direct parsing
        try:
            extracted = json.loads(json_str)
        except json.JSONDecodeError as e_first:
            # If parsing fails, try to fix common issues
            logger.warning(f"Batch {batch_idx}: Initial JSON parsing failed, attempting to fix...")

            # Try 1: Use strict=False
            try:
                from json.decoder import JSONDecoder

                decoder = JSONDecoder(strict=False)
                extracted = decoder.decode(json_str)
                logger.info(f"Batch {batch_idx}: Parsed successfully using non-strict mode")
            except Exception:
                # Try 2: Use ast.literal_eval
                try:
                    import ast

                    extracted = ast.literal_eval(json_str)
                    logger.info(f"Batch {batch_idx}: Parsed successfully using literal_eval")
                except Exception:
                    # All methods failed, skip this batch
                    logger.warning(f"Batch {batch_idx}: All parsing methods failed, skipping batch")
                    logger.error(f"Original error: {e_first!s}")
                    logger.error(f"Response content (first 500 chars): {response[:500]}")
                    return numbered_items

        if not isinstance(extracted, list):
            logger.warning(f"Batch {batch_idx}: LLM returned non-array")
            return numbered_items

        # Process extracted results
        for item in extracted:
            index = item.get("index")
            if index is None or index < batch_start or index >= batch_start + len(batch):
                continue

            # Convert to index relative to batch
            relative_index = index - batch_start
            original_item = batch[relative_index]
            identifier = item.get("identifier", "").strip()

            if not identifier:
                continue

            # Get complete content and related images
            # Prefer LLM-extracted full_text (contains complete content)
            llm_extracted_text = item.get("full_text", "").strip()
            img_paths = []

            # For image or equation types, use LLM-extracted content directly (no need to complete)
            original_type = original_item.get("_original_type", original_item.get("type", ""))
            if original_type in ["image", "equation"]:
                complete_text = llm_extracted_text
                # Collect image path for current item
                img_path = original_item.get("img_path", "")
                if img_path:
                    img_paths.append(img_path)
            else:
                # For plain text, get index in full content_items and complete
                full_index = text_item_to_full_index.get(index)
                if full_index is not None:
                    # Get complete content (including subsequent equations, etc.) and all related images
                    # Use LLM to intelligently determine content boundaries
                    complete_text, img_paths = await _get_complete_content_async(
                        content_items, full_index, api_key, base_url
                    )
                else:
                    complete_text = original_item.get("text", "")
                    # Collect image path for current item
                    img_path = original_item.get("img_path", "")
                    if img_path:
                        img_paths.append(img_path)

                # If completed content is shorter than LLM-extracted, use LLM-extracted
                if len(llm_extracted_text) > len(complete_text):
                    complete_text = llm_extracted_text

            numbered_items[identifier] = {
                "text": complete_text,
                "type": item.get("type", "Unknown"),
                "page": original_item.get("page_idx", 0) + 1,
                "img_paths": img_paths if img_paths else [],
            }

        extracted_count = len([e for e in extracted if e.get("identifier", "").strip()])
        logger.info(
            f"  Batch {batch_idx}/{total_batches}: Extracted {extracted_count} numbered items"
        )

    except Exception as e:
        logger.error(f"Batch {batch_idx}: Processing failed: {e}")

    return numbered_items


async def extract_numbered_items_with_llm_async(
    content_items: list[dict[str, Any]],
    api_key: str,
    base_url: str | None,
    batch_size: int = 20,
    max_concurrent: int = 5,
) -> dict[str, dict[str, Any]]:
    """
    Use LLM to asynchronously batch extract numbered important content

    Args:
        content_items: List of content items from content_list
        api_key: OpenAI API key
        base_url: API base URL
        batch_size: Number of items to process per batch
        max_concurrent: Maximum concurrency

    Returns:
        Dict[identifier, {text: original text, type: type, page: page number}]
    """
    numbered_items: dict[str, dict[str, Any]] = {}

    # Create index mapping: from text_items index to full content_items index
    text_item_to_full_index: dict[int, int] = {}
    text_items: list[dict[str, Any]] = []

    for idx, item in enumerate(content_items):
        item_type = item.get("type", "")

        # Process plain text
        if item_type == "text" and item.get("text_level", 0) == 0:
            text_item_to_full_index[len(text_items)] = idx
            text_items.append(item)

        # Process images (extract Figure number from caption)
        elif item_type == "image":
            captions = item.get("image_caption", [])
            if captions:
                # Create a virtual text item
                caption_text = " ".join(captions) if isinstance(captions, list) else str(captions)
                virtual_item = {
                    "type": "image",
                    "text": caption_text,
                    "page_idx": item.get("page_idx", 0),
                    "bbox": item.get("bbox", []),
                    "img_path": item.get("img_path", ""),
                    "_original_type": "image",
                }
                text_item_to_full_index[len(text_items)] = idx
                text_items.append(virtual_item)

        # Process numbered equations (extract from tag)
        elif item_type == "equation":
            equation_text = item.get("text", "")
            # Check if there's a number tag, like \tag{1.2.1} or other forms
            if "\\tag{" in equation_text or "tag{" in equation_text:
                virtual_item = {
                    "type": "equation",
                    "text": equation_text,
                    "page_idx": item.get("page_idx", 0),
                    "bbox": item.get("bbox", []),
                    "img_path": item.get("img_path", ""),
                    "_original_type": "equation",
                }
                text_item_to_full_index[len(text_items)] = idx
                text_items.append(virtual_item)

    # Statistics
    text_count = sum(
        1 for item in content_items if item.get("type") == "text" and item.get("text_level", 0) == 0
    )
    image_count = sum(
        1 for item in content_items if item.get("type") == "image" and item.get("image_caption")
    )
    equation_count = sum(
        1
        for item in content_items
        if item.get("type") == "equation"
        and ("\\tag{" in item.get("text", "") or "tag{" in item.get("text", ""))
    )

    logger.info(f"Total {len(text_items)} items to process")
    logger.info(f"  - Plain text: {text_count}")
    logger.info(f"  - Images with captions: {image_count}")
    logger.info(f"  - Numbered equations: {equation_count}")

    # Prepare all batches
    batches = []
    for batch_start in range(0, len(text_items), batch_size):
        batch_end = min(batch_start + batch_size, len(text_items))
        batch = text_items[batch_start:batch_end]
        batches.append((batch_start, batch))

    total_batches = len(batches)
    logger.info(f"Using {max_concurrent} concurrent tasks to process {total_batches} batches")

    # Use semaphore to control concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(batch_idx, batch_start, batch):
        async with semaphore:
            return await _process_single_batch(
                batch_idx + 1,
                batch,
                batch_start,
                content_items,
                text_item_to_full_index,
                api_key,
                base_url,
                total_batches,
            )

    # Create all tasks
    tasks = [
        process_with_semaphore(idx, batch_start, batch)
        for idx, (batch_start, batch) in enumerate(batches)
    ]

    # Execute all batches concurrently
    results = await asyncio.gather(*tasks)

    # Merge all results
    for result in results:
        numbered_items.update(result)

    # Count results
    type_stats: dict[str, int] = {}
    for item_data in numbered_items.values():
        item_type = item_data.get("type", "Unknown")
        type_stats[item_type] = type_stats.get(item_type, 0) + 1

    logger.info(f"\nExtraction complete, total {len(numbered_items)} numbered items")
    logger.info("Statistics by type:")
    for item_type, count in sorted(type_stats.items()):
        logger.info(f"  - {item_type}: {count}")

    return numbered_items


def extract_numbered_items_with_llm(
    content_items: list[dict[str, Any]],
    api_key: str,
    base_url: str | None,
    batch_size: int = 20,
    max_concurrent: int = 5,
) -> dict[str, dict[str, Any]]:
    """
    Synchronous wrapper for async extraction function
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If event loop is already running, check if it's uvloop
            loop_type = type(loop).__name__
            if "uvloop" in loop_type.lower():
                # uvloop doesn't support nest_asyncio, use threading approach
                import concurrent.futures

                def run_in_new_loop():
                    # Create a new asyncio event loop in a new thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            extract_numbered_items_with_llm_async(
                                content_items, api_key, base_url, batch_size, max_concurrent
                            )
                        )
                    finally:
                        new_loop.close()

                # Run in a thread with a new event loop
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_new_loop)
                    return future.result()
            else:
                # Try nest_asyncio for standard event loops
                try:
                    import nest_asyncio

                    nest_asyncio.apply()
                    return loop.run_until_complete(
                        extract_numbered_items_with_llm_async(
                            content_items, api_key, base_url, batch_size, max_concurrent
                        )
                    )
                except (ValueError, TypeError) as e:
                    # nest_asyncio failed, fall back to threading approach
                    logger.debug(f"nest_asyncio failed ({e}), using threading fallback")
                    import concurrent.futures

                    def run_in_new_loop():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            return new_loop.run_until_complete(
                                extract_numbered_items_with_llm_async(
                                    content_items, api_key, base_url, batch_size, max_concurrent
                                )
                            )
                        finally:
                            new_loop.close()

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(run_in_new_loop)
                        return future.result()
        else:
            return loop.run_until_complete(
                extract_numbered_items_with_llm_async(
                    content_items, api_key, base_url, batch_size, max_concurrent
                )
            )
    except RuntimeError:
        # No event loop, create new one
        return asyncio.run(
            extract_numbered_items_with_llm_async(
                content_items, api_key, base_url, batch_size, max_concurrent
            )
        )


def process_content_list(
    content_list_file: Path,
    output_file: Path,
    api_key: str,
    base_url: str | None,
    batch_size: int = 20,
    merge: bool = True,
):
    """
    Process content_list file and extract numbered items

    Args:
        content_list_file: Path to content_list JSON file
        output_file: Path to output JSON file
        api_key: OpenAI API key
        base_url: API base URL
        batch_size: Batch processing size
        merge: Whether to merge with existing results (default True)
    """
    logger.info(f"Reading file: {content_list_file}")

    # Read content_list
    with open(content_list_file, encoding="utf-8") as f:
        content_items = json.load(f)

    logger.info(f"File contains {len(content_items)} items")

    # Extract numbered items
    logger.info("Starting numbered items extraction...")
    new_items = extract_numbered_items_with_llm(
        content_items,
        api_key,
        base_url,
        batch_size,
        max_concurrent=5,  # Default concurrency
    )

    logger.info(f"Extracted {len(new_items)} numbered items this time")

    # If merge is needed and file exists
    if merge and output_file.exists():
        logger.info(f"Existing file detected: {output_file}")
        try:
            with open(output_file, encoding="utf-8") as f:
                existing_items = json.load(f)
            logger.info(f"Loaded {len(existing_items)} existing numbered items")

            # Merge (new items will override old items with same identifier)
            merged_count = 0
            for identifier, data in new_items.items():
                if identifier in existing_items:
                    merged_count += 1
                existing_items[identifier] = data

            numbered_items = existing_items
            logger.info(
                f"Merge complete: Updated {merged_count} existing items, added {len(new_items) - merged_count} new items"
            )
            logger.info(f"Total {len(numbered_items)} numbered items after merge")
        except Exception as e:
            logger.warning(f"Could not read existing file, will create new file: {e}")
            numbered_items = new_items
    else:
        numbered_items = new_items

    # Save results
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(numbered_items, f, indent=2, ensure_ascii=False)

    logger.info(f"Results saved to: {output_file}")

    # Print statistics
    type_counts: dict[str, int] = {}
    for identifier in numbered_items.keys():
        # Identify equations: starting with parenthesis, e.g., (1.2.1)
        if identifier.startswith("(") and ")" in identifier:
            item_type = "Equation"
        else:
            # Extract type from identifier (e.g., "Definition 1.1" -> "Definition")
            parts = identifier.split()
            if parts:
                item_type = parts[0]
            else:
                item_type = "Unknown"
        type_counts[item_type] = type_counts.get(item_type, 0) + 1

    logger.info("\n=== Extraction Statistics ===")
    for item_type, count in sorted(type_counts.items()):
        logger.info(f"  {item_type}: {count}")

    return numbered_items


def main():
    parser = argparse.ArgumentParser(
        description="Extract numbered important content from knowledge base content_list"
    )
    parser.add_argument(
        "--kb", required=True, help="Knowledge base name (under knowledge_bases directory)"
    )
    parser.add_argument(
        "--content-file",
        help="content_list file name (optional, if not specified, automatically process all JSON files)",
        default=None,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode: only process first file (for quick testing)",
    )
    parser.add_argument(
        "--output-name",
        help="Output file name (default: numbered_items.json)",
        default="numbered_items.json",
    )
    parser.add_argument(
        "--base-dir",
        help="Data storage base directory (default: ./knowledge_bases)",
        default="./knowledge_bases",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Number of items to process per batch (default: 20)",
        default=20,
    )
    parser.add_argument(
        "--max-concurrent", type=int, help="Maximum concurrent tasks (default: 5)", default=5
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Do not merge existing results, directly overwrite (default will merge)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LLM_API_KEY"),
        help="OpenAI API key (default reads from LLM_API_KEY)",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LLM_HOST"),
        help="OpenAI API Base URL (default reads from LLM_HOST)",
    )

    args = parser.parse_args()

    # Get API configuration
    api_key = args.api_key
    base_url = args.base_url

    # Validate API key
    if not api_key:
        raise SystemExit(
            "Missing API Key: Please set environment variable LLM_API_KEY or pass via --api-key"
        )

    # Build paths
    base_dir = Path(args.base_dir)
    kb_dir = base_dir / args.kb
    content_list_dir = kb_dir / "content_list"

    # Check if content_list directory exists
    if not content_list_dir.exists():
        logger.error(f"content_list directory does not exist: {content_list_dir}")
        sys.exit(1)

    # Get list of files to process
    if args.content_file:
        # If file is specified, only process that file
        content_list_files = [content_list_dir / args.content_file]
        if not content_list_files[0].exists():
            logger.error(f"content_list file does not exist: {content_list_files[0]}")
            sys.exit(1)
    else:
        # Otherwise automatically scan all JSON files
        content_list_files = sorted(content_list_dir.glob("*.json"))
        if not content_list_files:
            logger.error(f"No JSON files found in {content_list_dir}")
            sys.exit(1)

        # Debug mode: only process first file
        if args.debug:
            logger.info(f"⚠️ Debug mode: Only processing first file {content_list_files[0].name}")
            content_list_files = content_list_files[:1]

    # Output file fixed as numbered_items.json (shared across entire knowledge base)
    output_file = kb_dir / args.output_name

    # Display configuration information
    logger.info("=" * 60)
    logger.info("📋 Configuration Information")
    logger.info("=" * 60)
    logger.info(f"Knowledge base: {args.kb}")
    logger.info(f"Content files: {len(content_list_files)} files")
    for f in content_list_files:
        logger.info(f"  - {f.name}")
    logger.info(f"Output file: {output_file}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Max concurrent: {args.max_concurrent}")
    logger.info(f"Auto merge: {'Yes' if not args.no_merge else 'No'}")
    logger.info(f"Debug mode: {'Yes' if args.debug else 'No'}")
    logger.info(
        f"API key: {'Set (' + api_key[:8] + '...' + api_key[-4:] + ')' if api_key else 'Not set'}"
    )
    logger.info(f"API base URL: {base_url if base_url else 'Default (https://api.openai.com/v1)'}")
    logger.info("=" * 60)
    logger.info("")

    try:
        # Process all files
        for idx, content_list_file in enumerate(content_list_files, 1):
            logger.info(f"\n{'=' * 60}")
            logger.info(
                f"Processing file [{idx}/{len(content_list_files)}]: {content_list_file.name}"
            )
            logger.info(f"{'=' * 60}\n")

            process_content_list(
                content_list_file,
                output_file,
                api_key,
                base_url,
                args.batch_size,
                merge=not args.no_merge,  # Auto-merge after first file
            )

            # From second file onwards, force merge mode
            if idx == 1 and len(content_list_files) > 1:
                args.no_merge = False
                logger.info(f"\nSubsequent files will be automatically merged to {output_file}\n")

        logger.info("\n" + "=" * 60)
        logger.info("✓ All files processed!")
        logger.info("=" * 60)

        # Display final statistics
        if output_file.exists():
            with open(output_file, encoding="utf-8") as f:
                final_items = json.load(f)

            logger.info(f"\nFinal result: {output_file}")
            logger.info(f"Total extracted {len(final_items)} numbered items")

            # Statistics by type
            type_counts = {}
            for identifier in final_items.keys():
                # Identify equations: starting with parenthesis, e.g., (1.2.1)
                if identifier.startswith("(") and ")" in identifier:
                    item_type = "Equation"
                else:
                    # Extract type from identifier (e.g., "Definition 1.1" -> "Definition")
                    parts = identifier.split()
                    if parts:
                        item_type = parts[0]
                    else:
                        item_type = "Unknown"
                type_counts[item_type] = type_counts.get(item_type, 0) + 1

            logger.info("\n=== Final Statistics ===")
            for item_type, count in sorted(type_counts.items()):
                logger.info(f"  {item_type}: {count}")

    except Exception as e:
        logger.error(f"\n✗ Processing failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
