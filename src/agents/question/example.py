#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Example script that demonstrates how to use the Agent coordinator.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

os.environ["RAGANYTHING_VERBOSE"] = "0"
os.environ["LIGHTRAG_VERBOSE"] = "0"

logging.basicConfig(level=logging.WARNING, force=True)
for logger_name in ["lightrag", "raganything", "nano-vectordb", "openai", "httpx", "httpcore"]:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.WARNING)
    logger.propagate = False

project_root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

load_dotenv(dotenv_path=project_root / ".env", override=False)

from src.agents.question import AgentCoordinator


async def run_single_example(coordinator: AgentCoordinator):
    """Generate a single question."""
    requirement = {
        "knowledge_point": "Lagrange multipliers",
        "difficulty": "medium",
        "question_type": "written",
        "additional_requirements": "Focus on a computational exercise that demonstrates how to apply Lagrange multipliers.",
    }

    result = await coordinator.generate_question(requirement)

    print("\n" + "=" * 80)
    print("📊 Single-question result")
    print("=" * 80)

    if result.get("success"):
        question = result["question"]
        validation = result["validation"]

        print(f"\n✓ Success in {result['rounds']} round(s)")
        print(f"\nType: {question.get('question_type')}")
        print(f"\nQuestion:\n{question.get('question')}")

        if question.get("options"):
            print("\nOptions:")
            for key, value in question["options"].items():
                print(f"  {key}. {value}")

        print(f"\nCorrect answer: {question.get('correct_answer')}")
        print(f"\nExplanation:\n{question.get('explanation')}")

        print(f"\nValidation decision: {validation.get('decision')}")
        print(f"Validation reasoning: {validation.get('reasoning')}")
    else:
        error_type = result.get("error")
        if error_type == "task_rejected":
            print("\n🚫 Task rejected")
            print(f"Reason: {result.get('reason')}")
            print(
                "\n💡 Tip: try a different knowledge point or ensure the knowledge base contains supporting material."
            )
        else:
            print(f"\n✗ Failed: {error_type}")
            if result.get("last_question"):
                print("\nLast attempted question:")
                print(json.dumps(result["last_question"], ensure_ascii=False, indent=2))
            if result.get("last_validation"):
                print("\nLast validation result:")
                print(json.dumps(result["last_validation"], ensure_ascii=False, indent=2))


async def run_batch_example(coordinator: AgentCoordinator):
    """Generate multiple questions from a natural-language prompt."""
    prompt = (
        "Medium questions on Multivariable Functions, Limits and Continuity, and Differentiation"
    )

    batch_result = await coordinator.generate_questions_from_prompt(
        requirement_text=prompt, num_questions=3
    )

    print("\n" + "=" * 80)
    print("📦 Batch generation result")
    print("=" * 80)
    print(json.dumps(batch_result, ensure_ascii=False, indent=2))


async def main():
    """Entry point for the example script."""
    coordinator = AgentCoordinator(max_rounds=10, kb_name="math2211", output_dir="./output")

    # await run_single_example(coordinator)
    await run_batch_example(coordinator)


if __name__ == "__main__":
    asyncio.run(main())
