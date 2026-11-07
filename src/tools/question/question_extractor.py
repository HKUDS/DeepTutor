#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extract question information from MinerU-parsed exam papers

This script reads MinerU-parsed markdown files and content_list.json,
uses LLM to analyze and extract all questions, including question content and related images.

Uses the unified LLM Factory for all LLM calls, supporting:
- Cloud providers (OpenAI, Anthropic, DeepSeek, etc.)
- Local providers (Ollama, LM Studio, vLLM, etc.)
- Automatic retry with exponential backoff
"""

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

# Project root is 3 levels up from src/tools/question/
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.services.config import get_agent_params
from src.services.llm import complete as llm_complete
from src.services.llm.capabilities import supports_response_format
from src.services.llm.config import get_llm_config
from src.utils.json_parser import parse_json_response


def load_parsed_paper(paper_dir: Path) -> tuple[str | None, list[dict] | None, Path]:
    """
    Load MinerU-parsed exam paper files

    Args:
        paper_dir: MinerU output directory (e.g., reference_papers/paper_name_20241129/)

    Returns:
        (markdown_content, content_list, images_dir)
    """
    auto_dir = paper_dir / "auto"
    if not auto_dir.exists():
        auto_dir = paper_dir

    md_files = list(auto_dir.glob("*.md"))
    if not md_files:
        print(f"✗ Error: No markdown file found in {auto_dir}")
        return None, None, auto_dir / "images"

    md_file = md_files[0]
    print(f"📄 Found markdown file: {md_file.name}")

    with open(md_file, encoding="utf-8") as f:
        markdown_content = f.read()

    json_files = list(auto_dir.glob("*_content_list.json"))
    content_list = None
    if json_files:
        json_file = json_files[0]
        print(f"📋 Found content_list file: {json_file.name}")
        with open(json_file, encoding="utf-8") as f:
            content_list = json.load(f)
    else:
        print("⚠️ Warning: content_list.json file not found, will use markdown content only")

    images_dir = auto_dir / "images"
    if images_dir.exists():
        image_count = len(list(images_dir.glob("*")))
        print(f"🖼️ Found image directory: {image_count} images")
    else:
        print("⚠️ Warning: images directory not found")

    return markdown_content, content_list, images_dir


def extract_questions_with_llm(
    markdown_content: str,
    content_list: list[dict] | None,
    images_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    api_version: str | None = None,
    binding: str | None = None,
) -> list[dict[str, Any]]:
    """
    Use LLM to analyze markdown content and extract questions

    Args:
        markdown_content: Document content in Markdown format
        content_list: MinerU-generated content_list (optional)
        images_dir: Image directory path
        api_key: OpenAI API key
        base_url: API endpoint URL
        model: Model name
        api_version: API version for Azure OpenAI (optional)
        binding: Provider binding type (optional)

        Returns:
        Question list, each question contains:
        {
            "question_number": Question number,
            "question_text": Question text content (multiple choice includes options),
            "images": [List of relative paths to related images]
        }
    """
    import os

    binding = binding or os.getenv("LLM_BINDING", "openai")

    image_list = []
    if images_dir.exists():
        for img_file in sorted(images_dir.glob("*")):
            if img_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                image_list.append(img_file.name)

    system_prompt = """You are a professional exam paper analysis assistant. Your task is to extract all question information from the provided exam paper content.

Please carefully analyze the exam paper content and extract the following information for each question:
1. Question number (e.g., "1.", "Question 1", etc.)
2. Complete question text content (if multiple choice, include all options)
3. Related image file names (if the question references images)

For multiple choice questions, please merge the stem and all options into one complete question text, for example:
"1. Which of the following descriptions about neural networks is correct? ()\nA. Option A content\nB. Option B content\nC. Option C content\nD. Option D content"

Please return results in JSON format as follows:
```json
{
    "questions": [
        {
            "question_number": "1",
            "question_text": "Complete question content (including options)...",
            "images": ["image_001.jpg", "image_002.jpg"]
        },
        {
            "question_number": "2",
            "question_text": "Complete content of another question...",
            "images": []
        }
    ]
}
```

Important Notes:
1. Ensure all questions are extracted, do not miss any
2. Keep the original question text, do not modify or summarize
3. For multiple choice questions, must merge stem and options in question_text
4. If a question has no associated images, set images field to empty array []
5. Image file names should be actual existing file names
6. Ensure the returned format is valid JSON
"""

    user_prompt = f"""Exam paper content (Markdown format):

{markdown_content[:15000]}

Available image files:
{json.dumps(image_list, ensure_ascii=False, indent=2)}

Please analyze the above exam paper content, extract all question information, and return in JSON format.
"""

    print("\n🤖 Using LLM to analyze questions...")
    print(f"📊 Model: {model}")
    print(f"📝 Document length: {len(markdown_content)} characters")
    print(f"🖼️ Available images: {len(image_list)}")

    # Get agent parameters from unified config
    agent_params = get_agent_params("question")

    # Build kwargs for LLM Factory
    llm_kwargs = {
        "temperature": agent_params["temperature"],
        "max_tokens": agent_params["max_tokens"],
    }

    # Only add response_format if the provider supports it
    if supports_response_format(binding, model):
        llm_kwargs["response_format"] = {"type": "json_object"}

    try:
        # Call LLM via unified Factory (async, so we need to run in event loop)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an existing event loop, run in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    llm_complete(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                        api_version=api_version,
                        binding=binding,
                        **llm_kwargs,
                    ),
                )
                result_text = future.result()
        else:
            # No running loop, use run_until_complete
            result_text = loop.run_until_complete(
                llm_complete(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    api_version=api_version,
                    binding=binding,
                    **llm_kwargs,
                )
            )
    except RuntimeError as e:
        if "already running" in str(e):
            # Fallback: use asyncio.run in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    llm_complete(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                        api_version=api_version,
                        binding=binding,
                        **llm_kwargs,
                    ),
                )
                result_text = future.result()
        else:
            raise

    # Parse JSON response
    try:
        if not result_text:
            raise ValueError("LLM returned empty or None response")
        result = parse_json_response(result_text, logger_instance=None, fallback={})
        if result is None:
            raise ValueError("JSON parsing returned None")
    except Exception as e:
        print(f"✗ JSON parsing error: {e!s}")
        print(f"LLM response content: {result_text[:500]}...")
        raise ValueError(
            f"Failed to parse LLM JSON response: {e}. "
            f"Raw response (first 500 chars): {result_text[:500]!r}"
        ) from e

    questions = result.get("questions", [])
    print(f"✓ Successfully extracted {len(questions)} questions")

    return questions


def save_questions_json(questions: list[dict[str, Any]], output_dir: Path, paper_name: str) -> Path:
    """
    Save question information as JSON file

    Args:
        questions: Question list
        output_dir: Output directory
        paper_name: Paper name

    Returns:
        Saved file path
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_data = {
        "paper_name": paper_name,
        "extraction_time": datetime.now().isoformat(),
        "total_questions": len(questions),
        "questions": questions,
    }

    output_file = output_dir / f"{paper_name}_{timestamp}_questions.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"💾 Question information saved to: {output_file.name}")

    print("\n📋 Question statistics:")
    print(f"  Total questions: {len(questions)}")

    questions_with_images = sum(1 for q in questions if q.get("images"))
    print(f"  Questions with images: {questions_with_images}")

    return output_file


def extract_questions_from_paper(paper_dir: str, output_dir: str | None = None) -> bool:
    """
    Extract questions from parsed exam paper

    Args:
        paper_dir: MinerU-parsed directory path
        output_dir: Output directory (default: paper_dir)

    Returns:
        Whether extraction was successful
    """
    paper_dir = Path(paper_dir).resolve()
    if not paper_dir.exists():
        print(f"✗ Error: Directory does not exist: {paper_dir}")
        return False

    print(f"📁 Paper directory: {paper_dir}")

    markdown_content, content_list, images_dir = load_parsed_paper(paper_dir)

    if not markdown_content:
        print("✗ Error: Unable to load paper content")
        return False

    try:
        llm_config = get_llm_config()
    except ValueError as e:
        print(f"✗ {e!s}")
        print(
            "Tip: Please create .env file in project root and configure LLM-related environment variables"
        )
        return False

    questions = extract_questions_with_llm(
        markdown_content=markdown_content,
        content_list=content_list,
        images_dir=images_dir,
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        model=llm_config.model,
        api_version=getattr(llm_config, "api_version", None),
        binding=getattr(llm_config, "binding", None),
    )

    if not questions:
        print("⚠️ Warning: No questions extracted")
        return False

    if output_dir is None:
        output_dir = paper_dir
    else:
        output_dir = Path(output_dir)

    paper_name = paper_dir.name
    output_file = save_questions_json(questions, output_dir, paper_name)

    print("\n✓ Question extraction completed!")
    print(f"📄 View results: {output_file}")

    return True


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Extract question information from MinerU-parsed exam papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract questions from parsed exam paper directory
  python question_extractor.py reference_papers/exam_20241129_143052

  # Specify output directory
  python question_extractor.py reference_papers/exam_20241129_143052 -o ./output
        """,
    )

    parser.add_argument("paper_dir", type=str, help="MinerU-parsed exam paper directory path")

    parser.add_argument(
        "-o", "--output", type=str, default=None, help="Output directory (default: paper directory)"
    )

    args = parser.parse_args()

    success = extract_questions_from_paper(args.paper_dir, args.output)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
