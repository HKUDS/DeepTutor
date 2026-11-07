#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Incremental Document Addition Usage Example

Demonstrates how to add new documents to an existing knowledge base
"""

import asyncio
import os
from pathlib import Path
import sys

# Add project root directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.knowledge.add_documents import DocumentAdder


async def example_add_single_document():
    """Example 1: Add single document"""
    print("\n" + "=" * 60)
    print("Example 1: Add single document to knowledge base")
    print("=" * 60)

    adder = DocumentAdder(
        kb_name="ai_textbook",
        base_dir="./data/knowledge_bases",
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_HOST"),
    )

    # Add documents
    new_files = adder.add_documents(
        source_files=["./new_chapter.pdf"],
        skip_duplicates=True,  # Skip files with same name
    )

    if new_files:
        # Process new documents
        processed = await adder.process_new_documents(new_files)

        # Extract numbered items
        adder.extract_numbered_items_for_new_docs(processed)

        # Update metadata
        adder.update_metadata(len(new_files))

        print("\n✓ Completed!")


async def example_add_multiple_documents():
    """Example 2: Add multiple documents"""
    print("\n" + "=" * 60)
    print("Example 2: Batch add documents to knowledge base")
    print("=" * 60)

    adder = DocumentAdder(
        kb_name="math2211",
        base_dir="./data/knowledge_bases",
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_HOST"),
    )

    # Add multiple documents
    new_files = adder.add_documents(
        source_files=[
            "./materials/chapter1.pdf",
            "./materials/chapter2.pdf",
            "./materials/exercises.pdf",
        ],
        skip_duplicates=True,
    )

    if new_files:
        # Process new documents
        processed = await adder.process_new_documents(new_files)

        # Extract numbered items (use larger batch size)
        adder.extract_numbered_items_for_new_docs(
            processed,
            batch_size=30,  # Increase batch size for efficiency
        )

        # Update metadata
        adder.update_metadata(len(new_files))

        print("\n✓ Completed!")


async def example_add_from_directory():
    """Example 3: Add all documents from directory"""
    print("\n" + "=" * 60)
    print("Example 3: Add all documents from directory")
    print("=" * 60)

    adder = DocumentAdder(
        kb_name="ai_textbook",
        base_dir="./data/knowledge_bases",
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_HOST"),
    )

    # Collect all documents in directory
    docs_dir = Path("./new_materials")
    doc_files = []

    for ext in ["*.pdf", "*.docx", "*.doc"]:
        doc_files.extend([str(f) for f in docs_dir.glob(ext)])

    print(f"Found {len(doc_files)} documents")

    # Add documents
    new_files = adder.add_documents(source_files=doc_files, skip_duplicates=True)

    if new_files:
        # Process new documents
        processed = await adder.process_new_documents(new_files)

        # Extract numbered items
        adder.extract_numbered_items_for_new_docs(processed)

        # Update metadata
        adder.update_metadata(len(new_files))

        print("\n✓ Completed!")


async def example_add_only_no_processing():
    """Example 4: Only add files, no processing (process manually later)"""
    print("\n" + "=" * 60)
    print("Example 4: Only add files, no processing")
    print("=" * 60)

    adder = DocumentAdder(
        kb_name="ai_textbook",
        base_dir="./data/knowledge_bases",
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_HOST"),
    )

    # Only add files to raw directory
    new_files = adder.add_documents(source_files=["./chapter.pdf"], skip_duplicates=True)

    print(f"Added {len(new_files)} files to raw directory")
    print("These files can be processed manually later")

    # Don't call process_new_documents()
    # Can process manually later or use other tools


async def example_check_existing_files():
    """Example 5: Check existing files"""
    print("\n" + "=" * 60)
    print("Example 5: Check existing files in knowledge base")
    print("=" * 60)

    adder = DocumentAdder(kb_name="ai_textbook", base_dir="./data/knowledge_bases")

    existing_files = adder.get_existing_files()

    print(f"\nKnowledge base 'ai_textbook' already has {len(existing_files)} files:")
    for filename in sorted(existing_files):
        print(f"  • {filename}")


def example_with_error_handling():
    """Example 6: Complete error handling"""
    print("\n" + "=" * 60)
    print("Example 6: Incremental addition with error handling")
    print("=" * 60)

    try:
        adder = DocumentAdder(
            kb_name="ai_textbook",
            base_dir="./data/knowledge_bases",
            api_key=os.getenv("LLM_API_KEY"),
            base_url=os.getenv("LLM_HOST"),
        )

        # Check if file exists
        source_file = Path("./new_chapter.pdf")
        if not source_file.exists():
            print(f"✗ Error: Source file does not exist: {source_file}")
            return

        # Add documents
        new_files = adder.add_documents(source_files=[str(source_file)], skip_duplicates=True)

        if not new_files:
            print("ℹ️ No new files to add (may already exist)")
            return

        # Async processing
        async def process():
            processed = await adder.process_new_documents(new_files)
            adder.extract_numbered_items_for_new_docs(processed)
            adder.update_metadata(len(new_files))

        asyncio.run(process())

        print("\n✓ Successfully added documents!")

    except ValueError as e:
        print(f"✗ Configuration error: {e}")
    except FileNotFoundError as e:
        print(f"✗ File error: {e}")
    except Exception as e:
        print(f"✗ Unknown error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("\nIncremental Document Addition Usage Examples")
    print("=" * 60)

    # Select example to run
    example = 5  # Change this number to run different examples

    if example == 1:
        asyncio.run(example_add_single_document())
    elif example == 2:
        asyncio.run(example_add_multiple_documents())
    elif example == 3:
        asyncio.run(example_add_from_directory())
    elif example == 4:
        asyncio.run(example_add_only_no_processing())
    elif example == 5:
        asyncio.run(example_check_existing_files())
    elif example == 6:
        example_with_error_handling()
    else:
        print("Please select example number 1-6")
