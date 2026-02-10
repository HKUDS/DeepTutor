#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent coordinator responsible for managing collaboration between the question-generation agent
and the validation workflow.
"""

import asyncio
from collections.abc import Callable
import copy
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any

from .agents import Message, QuestionGenerationAgent
from .validation_workflow import QuestionValidationWorkflow

# Add project root for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.logging import Logger, get_logger
from src.services.config import load_config_with_main, parse_language
from src.services.prompt import get_prompt_manager
from src.tools.rag_tool import rag_search


def ensure_list(value: Any, default: list | None = None) -> list:
    """
    Ensure a value is a list, converting if necessary.

    Args:
        value: Value to check/convert
        default: Default value to return if conversion fails (default: [])

    Returns:
        List: A list representation of the value
    """
    if default is None:
        default = []

    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        # If it's a dict, try to extract values
        return list(value.values()) if value else default
    if isinstance(value, (str, int, float)):
        # If it's a single value, wrap in list
        return [value]
    if value is None:
        return default
    # Try to convert to list
    try:
        return list(value)
    except (TypeError, ValueError):
        return default


def ensure_dict(value: Any, default: dict | None = None) -> dict:
    """
    Ensure a value is a dict, converting if necessary.

    Args:
        value: Value to check/convert
        default: Default value to return if conversion fails (default: {})

    Returns:
        Dict: A dict representation of the value
    """
    if default is None:
        default = {}

    if isinstance(value, dict):
        return value
    if value is None:
        return default
    # Cannot safely convert non-dict to dict
    return default


class AgentCoordinator:
    """
    Coordinate interactions between QuestionGenerationAgent and QuestionValidationWorkflow.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_rounds: int = 10,
        kb_name: str | None = None,
        output_dir: str | None = None,
    ):
        """
        Initialize the coordinator.
        """
        self.max_rounds = max_rounds
        self.kb_name = kb_name
        self.output_dir = output_dir

        # Load configuration (with main.yaml merge) first
        project_root = Path(__file__).parent.parent.parent.parent
        self.config = load_config_with_main("question_config.yaml", project_root)

        # Initialize logger (from config)
        log_dir = self.config.get("paths", {}).get("user_log_dir") or self.config.get(
            "logging", {}
        ).get("log_dir")
        self.logger: Logger = get_logger("QuestionGen", log_dir=log_dir)

        # Get language setting from config (unified in config/main.yaml system.language)
        lang_config = self.config.get("system", {}).get("language", "zh")
        self.language = parse_language(lang_config)
        self.logger.info(f"Language setting: {self.language}")

        # Load coordinator prompts based on language
        self._prompts = get_prompt_manager().load_prompts(
            module_name="question",
            agent_name="coordinator",
            language=self.language,
        )

        # Override max_rounds from config if available
        question_cfg = self.config.get("question", {})
        if isinstance(question_cfg, dict) and "max_rounds" in question_cfg:
            self.max_rounds = question_cfg["max_rounds"]

        # Get parallel generation config from question section
        self.rag_query_count = question_cfg.get("rag_query_count", 3)
        self.max_parallel_questions = question_cfg.get("max_parallel_questions", 3)

        # Store API credentials for creating multiple agents
        self._api_key = api_key
        self._base_url = base_url

        # Get config for generation agent
        gen_agent_config = self.config.get("agents", {}).get("question_generation", {})
        max_gen_iterations = gen_agent_config.get("max_iterations", 5)

        # Instantiate question-generation agent
        self.question_agent = QuestionGenerationAgent(
            api_key=api_key,
            base_url=base_url,
            max_iterations=max_gen_iterations,
            kb_name=kb_name,
            token_stats_callback=self.update_token_stats,
            language=self.language,
        )

        # Instantiate validation workflow (fixed pipeline)
        self.validation_workflow = QuestionValidationWorkflow(
            api_key=api_key,
            base_url=base_url,
            kb_name=kb_name,
            token_stats_callback=self.update_token_stats,
            language=self.language,
        )

        # Message queue
        self.message_queue = asyncio.Queue()
        self._logging_suppressed = False

        # Token tracking
        self.token_stats = {
            "model": "gpt-4o-mini",
            "calls": 0,
            "tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
        }

        # Agent status tracking
        self.agent_status = {
            "QuestionGenerationAgent": "pending",
            "ValidationWorkflow": "pending",
            "RetrievalTool": "pending",
        }

        # WebSocket callback for streaming updates
        self._ws_callback: Callable | None = None

    def set_ws_callback(self, callback: Callable):
        """Set WebSocket callback for streaming updates to frontend."""
        self._ws_callback = callback

    async def _send_ws_update(self, update_type: str, data: dict[str, Any]):
        """Send update via WebSocket callback if available."""
        if self._ws_callback:
            try:
                await self._ws_callback({"type": update_type, **data})
            except Exception as e:
                self.logger.debug(f"Failed to send WS update: {e}")

    def _update_agent_status(self, agent: str, status: str):
        """Update agent status and notify frontend."""
        self.agent_status[agent] = status
        asyncio.create_task(
            self._send_ws_update(
                "agent_status", {"agent": agent, "status": status, "all_agents": self.agent_status}
            )
        )

    def update_token_stats(self, input_tokens: int = 0, output_tokens: int = 0, model: str = None):
        """
        Update token statistics. Can be called by external components.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            model: Model name (optional, will update if provided)
        """
        self.token_stats["calls"] += 1
        self.token_stats["input_tokens"] += input_tokens
        self.token_stats["output_tokens"] += output_tokens
        self.token_stats["tokens"] = (
            self.token_stats["input_tokens"] + self.token_stats["output_tokens"]
        )
        if model:
            self.token_stats["model"] = model

        # Estimate cost (simplified pricing)
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        self.token_stats["cost"] = (
            self.token_stats["input_tokens"] * 0.00000015
            + self.token_stats["output_tokens"] * 0.0000006
        )

        asyncio.create_task(self._send_ws_update("token_stats", {"stats": self.token_stats}))

    def _update_token_stats(self, input_tokens: int = 0, output_tokens: int = 0, model: str = None):
        """Internal alias for backwards compatibility."""
        self.update_token_stats(input_tokens, output_tokens, model)

    async def send_message(self, message: Message):
        """Send a message to the destination agent."""
        await self.message_queue.put(message)

    async def deliver_messages(self):
        """Deliver queued messages."""
        while not self.message_queue.empty():
            message = await self.message_queue.get()

            if message.to_agent == "QuestionGenerationAgent":
                self.question_agent.receive_message(message)

    def _suppress_logging(self):
        if self._logging_suppressed:
            return
        logging.basicConfig(level=logging.ERROR, force=True)
        for logger_name in [
            "lightrag",
            "raganything",
            "nano-vectordb",
            "openai",
            "httpx",
            "httpcore",
        ]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)
            logging.getLogger(logger_name).propagate = False
        self._logging_suppressed = True

    def _extract_json_from_markdown(self, content: str) -> str:
        """Extract JSON from markdown code blocks.

        LLMs often wrap JSON in ```json ... ``` blocks. This method strips
        the markdown formatting and any surrounding text.
        """
        if not content:
            return content

        # Remove leading explanatory text (look for the first ```json or ```)
        import re

        # Try to find JSON code block
        json_block_pattern = r"```(?:json)?\s*\n?(.*?)```"
        matches = re.findall(json_block_pattern, content, re.DOTALL)

        if matches:
            # Return the content inside the first code block
            return matches[0].strip()

        # If no code blocks found, return as-is (might already be valid JSON)
        return content.strip()

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
        stage: str = "",
    ):
        """Utility wrapper around the generation agent's LLM client."""
        client = self.question_agent.client
        model = self.question_agent.model

        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "timeout": 180.0,  # Add timeout to prevent hanging
        }
        if response_format:
            kwargs["response_format"] = response_format

        # Log the request details for debugging
        self.logger.debug(
            f"[{stage or 'coordinator'}] Calling LLM: model={model}, "
            f"system_prompt_len={len(system_prompt)}, user_prompt_len={len(user_prompt)}, "
            f"response_format={response_format}"
        )

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            self.logger.error(
                f"[{stage or 'coordinator'}] LLM API call failed: {type(e).__name__}: {e}"
            )
            self.logger.error(f"Request kwargs: {kwargs}")
            raise RuntimeError(f"LLM call failed in stage '{stage}': {e}") from e

        # Extract response content with validation
        if not response or not response.choices:
            error_msg = f"[{stage or 'coordinator'}] LLM returned empty response or no choices"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        response_content = response.choices[0].message.content

        # Validate content is not None or empty
        if response_content is None:
            error_msg = (
                f"[{stage or 'coordinator'}] LLM returned None content. Response: {response}"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        if not response_content.strip():
            error_msg = (
                f"[{stage or 'coordinator'}] LLM returned empty string. Response object: {response}"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Log successful response
        self.logger.debug(
            f"[{stage or 'coordinator'}] LLM response received: "
            f"length={len(response_content)}, preview={response_content[:200]}..."
        )

        # Track token usage
        input_tokens = 0
        output_tokens = 0
        cost = 0.0
        if hasattr(response, "usage") and response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            cost = input_tokens * 0.00000015 + output_tokens * 0.0000006
            self._update_token_stats(
                input_tokens=input_tokens, output_tokens=output_tokens, model=model
            )

        # Log LLM call with detailed information
        self.logger.log_llm_call(
            model=model,
            stage=stage or "coordinator_call",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response_content,
            agent_name="Coordinator",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            level="DEBUG",
        )

        return response_content

    async def _generate_search_queries(
        self, base_requirement: dict[str, Any], num_queries: int
    ) -> list[str]:
        """Backwards compatibility helper when a structured requirement already exists."""
        text = json.dumps(base_requirement, ensure_ascii=False, indent=2)
        return await self._generate_search_queries_from_text(text, num_queries)

    async def _generate_search_queries_from_text(
        self, requirement_text: str, num_queries: int
    ) -> list[str]:
        """Use LLM to produce semantic search queries directly from natural-language text."""
        # Load prompts from YAML file based on language setting
        prompt_config = self._prompts.get("generate_search_queries", "")
        if prompt_config and isinstance(prompt_config, str):
            # Parse the YAML-style prompt config
            import yaml
            try:
                parsed = yaml.safe_load(prompt_config)
                system_prompt = parsed.get("system", "")
                user_template = parsed.get("user_template", "")
            except Exception:
                system_prompt = ""
                user_template = ""
        else:
            system_prompt = ""
            user_template = ""
        
        # Fallback if prompts not loaded
        if not system_prompt:
            system_prompt = (
                "【Role】You are a knowledge base retrieval assistant, preparing for question generation.\n"
                "\n"
                "【Current Task】Generate knowledge point retrieval queries to find theoretical explanations, definitions, and theorems in the knowledge base.\n"
                "⚠️ Key: You are not generating questions now! You are looking for theoretical knowledge needed for question generation!\n"
                "\n"
                "【Output Rules】\n"
                "1. Only output pure knowledge point names (theorem names, concept names, method names)\n"
                "2. Each query should be 2-5 words\n"
                "3. Do not include functions, numerical values, or calculation tasks\n"
                "4. Do not use questions or task descriptions\n"
            )
        
        if user_template:
            user_prompt = user_template.format(
                requirement_text=requirement_text,
                num_queries=num_queries,
            )
        else:
            user_prompt = (
                f"The user's question generation requirement is:\n{requirement_text}\n\n"
                f"Please extract {num_queries} pure knowledge point names from it for knowledge base retrieval.\n\n"
                "Correct examples:\n"
                "✓ Taylor theorem\n"
                "✓ Lagrange multipliers  \n"
                "✓ critical points\n\n"
                "Incorrect examples (do not generate):\n"
                "✗ Apply Taylor's Theorem to approximate f(x,y)=... (This is a question)\n"
                "✗ Find and classify critical points (This is a task)\n"
                "✗ Use Lagrange multipliers to find maximum (This is an instruction)\n\n"
                f'Return in JSON format: {{"queries": ["knowledge point 1", "knowledge point 2", ...]}}, containing exactly {num_queries} knowledge point names.'
            )

        try:
            content = await self._call_llm(system_prompt=system_prompt, user_prompt=user_prompt)
            data = json.loads(content)

            # Ensure queries is a list
            queries_raw = data.get("queries", [])
            if not isinstance(queries_raw, list):
                self.logger.warning(
                    f"Queries is not a list (type: {type(queries_raw)}), converting..."
                )
                if isinstance(queries_raw, dict):
                    # If it's a dict, try to extract values or convert to list
                    queries_raw = list(queries_raw.values()) if queries_raw else []
                elif isinstance(queries_raw, str):
                    queries_raw = [queries_raw]
                else:
                    queries_raw = []

            queries = [q.strip() for q in queries_raw if q and q.strip()]
        except Exception as e:
            self.logger.warning(f"Failed to generate search queries: {e}")
            queries = []
        if not queries:
            queries = [requirement_text[:50]]
        return queries[:num_queries]

    async def _single_rag_search(self, query: str) -> dict[str, Any]:
        """Execute a single RAG search and return the raw answer."""
        question_cfg = self.config.get("question", {})
        rag_mode = question_cfg.get("rag_mode", "hybrid")

        result = await rag_search(
            query=query,
            kb_name=self.kb_name,
            mode=rag_mode,
            only_need_context=True,
        )
        return {
            "query": query,
            "answer": result.get("answer", ""),
            "mode": result.get("mode", rag_mode),
        }

    async def _gather_retrieval_context(self, queries: list[str]) -> list[dict[str, Any]]:
        """Run retrieval for each query in parallel and collect the raw contexts."""
        self._update_agent_status("RetrievalTool", "running")
        self.logger.info(f"Retrieving knowledge for {len(queries)} queries...")

        # Execute all queries in parallel
        tasks = [self._single_rag_search(query) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        retrievals = []
        for i, result in enumerate(results):
            query = queries[i]
            if isinstance(result, Exception):
                self.logger.warning(f"Retrieval failed for query '{query}': {result}")
                continue

            self.logger.debug(f"  → Query: {query[:50]}... (retrieved)")
            retrievals.append(
                {
                    "query": query,
                    "answer": result.get("answer", ""),
                }
            )

        self._update_agent_status("RetrievalTool", "done")
        return retrievals

    def _summarize_retrievals(self, retrievals: list[dict[str, Any]]) -> str:
        """Turn retrieval objects into a digest for the LLM."""
        lines = []
        for item in retrievals:
            lines.append(f"=== Query: {item['query']} ===")
            answer = item.get("answer", "")
            if answer:
                # Truncate very long answers
                if len(answer) > 2000:
                    answer = answer[:2000] + "...[truncated]"
                lines.append(answer)
            lines.append("")
        return "\n".join(lines) if lines else "No retrieval context available."

    def _save_question_result(
        self,
        question: dict[str, Any],
        requirement: dict[str, Any],
        validation: dict[str, Any],
        round_num: int,
        extended: bool = False,
    ) -> str | None:
        """
        Save a single question result to disk.

        Args:
            question: The generated question dict
            requirement: The requirement dict (contains knowledge_point, difficulty, etc.)
            validation: The validation result dict
            round_num: Number of rounds taken
            extended: Whether this is an extended question

        Returns:
            The output directory path if saved successfully, None otherwise
        """
        if not self.output_dir:
            return None

        try:
            # Create timestamped subdirectory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Path(self.output_dir) / f"question_{timestamp}"
            output_path.mkdir(parents=True, exist_ok=True)

            # Build result structure
            result = {
                "success": True,
                "question": question,
                "validation": validation,
                "rounds": round_num,
            }
            if extended:
                result["extended"] = True

            # Save result.json
            with open(output_path / "result.json", "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            # Build question.md
            validation_status = "Extended" if extended else "Approved"
            md_content = f"""# Generated Question

**Knowledge point**: {requirement.get("knowledge_point", question.get("knowledge_point", "N/A"))}
**Difficulty**: {requirement.get("difficulty", "N/A")}
**Type**: {requirement.get("question_type", question.get("question_type", "N/A"))}

---

## Question
{question.get("question", "")}

"""
            if question.get("options"):
                md_content += "## Options\n"
                for key, value in question.get("options", {}).items():
                    md_content += f"- **{key}**: {value}\n"
                md_content += "\n"

            md_content += f"""
## Answer
{question.get("correct_answer", "")}

## Explanation
{question.get("explanation", "")}

---
**Validation**: {validation_status} after {round_num} round(s)
"""
            with open(output_path / "question.md", "w", encoding="utf-8") as f:
                f.write(md_content)

            self.logger.info(f"Question saved to: {output_path}")
            return str(output_path)

        except Exception as e:
            self.logger.warning(f"Failed to save question artifacts: {e}")
            return None

    async def _check_retrieval_relevance(
        self, requirement_text: str, knowledge_summary: str
    ) -> bool:
        """Use LLM to determine whether retrieval results match the user's request."""
        # Load prompts from YAML file based on language setting
        prompt_config = self._prompts.get("check_retrieval_relevance", "")
        if prompt_config and isinstance(prompt_config, str):
            import yaml
            try:
                parsed = yaml.safe_load(prompt_config)
                system_prompt = parsed.get("system", "")
                user_template = parsed.get("user_template", "")
            except Exception:
                system_prompt = ""
                user_template = ""
        else:
            system_prompt = ""
            user_template = ""
        
        # Fallback if prompts not loaded
        if not system_prompt:
            system_prompt = (
                "You evaluate whether retrieved knowledge is relevant to a user's request. "
                'Respond in JSON with key "relevant" (true/false) and optional "reason".'
            )
        
        if user_template:
            user_prompt = user_template.format(
                requirement_text=requirement_text,
                knowledge_summary=knowledge_summary,
            )
        else:
            user_prompt = (
                f"User request:\n{requirement_text}\n\n"
                f"Retrieved knowledge summary:\n{knowledge_summary}\n\n"
                "Is the retrieved knowledge substantively relevant to the request?"
            )
        
        try:
            content = await self._call_llm(system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = json.loads(content)
            return bool(parsed.get("relevant"))
        except Exception as e:
            self.logger.warning(f"Failed to check retrieval relevance: {e}")
            return False

    async def _generate_child_requirements(
        self, base_requirement: dict[str, Any], knowledge_summary: str, num_questions: int
    ) -> list[dict[str, Any]]:
        """Ask LLM to break the base requirement into multiple sub-requirements."""
        # Load prompts from YAML file based on language setting
        prompt_config = self._prompts.get("generate_child_requirements", "")
        if prompt_config and isinstance(prompt_config, str):
            import yaml
            try:
                parsed = yaml.safe_load(prompt_config)
                system_prompt = parsed.get("system", "")
                user_template = parsed.get("user_template", "")
            except Exception:
                system_prompt = ""
                user_template = ""
        else:
            system_prompt = ""
            user_template = ""
        
        # Fallback if prompts not loaded
        if not system_prompt:
            system_prompt = (
                "You are a curriculum designer. Given a base requirement and knowledge summary, "
                "create distinct sub-requirements that all test the SAME knowledge point. "
                "Each sub-requirement must describe a unique scenario and reasoning flow. "
                'Output JSON with key "requirements" (array of length requested) where each item has: '
                '"title", "question_type", "difficulty", "additional_requirements".'
            )
        
        if user_template:
            user_prompt = user_template.format(
                base_requirement=json.dumps(base_requirement, ensure_ascii=False, indent=2),
                knowledge_summary=knowledge_summary,
                num_questions=num_questions,
            )
        else:
            user_prompt = (
                f"Base requirement:\n{json.dumps(base_requirement, ensure_ascii=False, indent=2)}\n\n"
                f"Knowledge summary:\n{knowledge_summary}\n\n"
                f"Generate exactly {num_questions} sub-requirements in JSON."
            )
        
        try:
            content = await self._call_llm(system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = json.loads(content)

            # Ensure requirements is a list
            requirements_raw = parsed.get("requirements", [])
            if not isinstance(requirements_raw, list):
                self.logger.warning(
                    f"Requirements is not a list (type: {type(requirements_raw)}), converting..."
                )
                if isinstance(requirements_raw, dict):
                    # If it's a dict, try to extract values or convert to list
                    requirements_raw = list(requirements_raw.values()) if requirements_raw else []
                else:
                    requirements_raw = []

            requirements = requirements_raw
        except Exception as e:
            self.logger.warning(f"Failed to generate sub-requirements: {e}")
            requirements = []
        return requirements[:num_questions]

    async def _interpret_requirement_text(self, requirement_text: str) -> dict[str, Any]:
        """Convert a natural-language request into structured requirement fields."""
        # Load prompts from YAML file based on language setting
        prompt_config = self._prompts.get("interpret_requirement_text", "")
        if prompt_config and isinstance(prompt_config, str):
            import yaml
            try:
                parsed_config = yaml.safe_load(prompt_config)
                system_prompt = parsed_config.get("system", "")
                user_template = parsed_config.get("user_template", "")
            except Exception:
                system_prompt = ""
                user_template = ""
        else:
            system_prompt = ""
            user_template = ""
        
        # Fallback if prompts not loaded
        if not system_prompt:
            system_prompt = (
                "You are an instruction parser for an exam-question generator. "
                "Given a natural-language request, extract the core knowledge point, "
                "difficulty (easy/medium/hard), preferred question type (choice/written), "
                "and additional requirements. Return JSON with keys: "
                '"knowledge_point", "difficulty", "question_type", "additional_requirements".'
            )
        
        if user_template:
            user_prompt = user_template.format(requirement_text=requirement_text)
        else:
            user_prompt = f"Requirement:\n{requirement_text}\n\nReturn JSON only."
        
        try:
            content = await self._call_llm(system_prompt=system_prompt, user_prompt=user_prompt)
            parsed = json.loads(content)
        except Exception as e:
            self.logger.warning(f"Failed to interpret requirement text: {e}")
            parsed = {}

        knowledge_point = parsed.get("knowledge_point") or requirement_text[:60]
        difficulty = (parsed.get("difficulty") or "medium").lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        question_type = (parsed.get("question_type") or "written").lower()
        if question_type not in {"choice", "written"}:
            question_type = "written"

        additional_requirements = parsed.get("additional_requirements") or requirement_text

        return {
            "knowledge_point": knowledge_point,
            "difficulty": difficulty,
            "question_type": question_type,
            "additional_requirements": additional_requirements,
        }

    async def generate_question(self, requirement: dict[str, Any]) -> dict[str, Any]:
        """
        Full workflow for generating and validating a question.
        """
        # Reset agent status for this question
        self.agent_status = {
            "QuestionGenerationAgent": "pending",
            "ValidationWorkflow": "pending",
            "RetrievalTool": "pending",
        }

        self.logger.section("Question Generation Workflow")
        self.logger.info("Workflow started")
        self.logger.info(f"Knowledge point: {requirement.get('knowledge_point')}")
        self.logger.info(f"Difficulty: {requirement.get('difficulty')}")
        self.logger.info(f"Question type: {requirement.get('question_type')}")

        # Send progress update
        await self._send_ws_update(
            "progress", {"stage": "generating", "progress": {"status": "initializing"}}
        )

        # If this is a batch sub-requirement, show specific info
        batch_index = requirement.get("batch_index")
        additional_req = requirement.get("additional_requirements", "")
        if batch_index and additional_req:
            lines = additional_req.split("\n")
            for line in lines:
                if line.startswith("[Auto-derived sub requirement"):
                    title_part = line.split(":", 1)[1].strip().rstrip("]") if ":" in line else ""
                    self.logger.info(f"Sub-requirement: {title_part}")
                    break

        # Ensure noisy loggers are silenced
        self._suppress_logging()

        # Provide requirement to the generation agent
        self.question_agent.set_requirement(requirement)

        for round_num in range(1, self.max_rounds + 1):
            self.logger.separator()
            self.logger.stage(f"Round {round_num}/{self.max_rounds}")

            # Send progress update
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generating",
                    "progress": {"round": round_num, "max_rounds": self.max_rounds},
                },
            )

            self.logger.info("Stage 1: QuestionGenerationAgent starting...")
            self.logger.debug(f"  Knowledge point: {requirement.get('knowledge_point', 'N/A')}")
            self.logger.debug(f"  Difficulty: {requirement.get('difficulty', 'N/A')}")
            self._update_agent_status("QuestionGenerationAgent", "running")

            # Register message callback
            self.question_agent.send_message = self.send_message

            # Reset submission flag for the new round
            self.question_agent.submitted = False

            # Build task description and context
            if round_num == 1:
                task = f"Generate a question that satisfies the requirement: {requirement.get('knowledge_point')}"
                agent_context = {
                    "requirement": requirement,
                    "round_num": round_num,
                    "is_new_round": False,
                }
            else:
                task = "Revise the question based on validation feedback"
                agent_context = {
                    "requirement": requirement,
                    "round_num": round_num,
                    "is_new_round": True,  # Notify the agent that a fresh round is starting
                }

            # Execute the question-generation agent
            question_result = await self.question_agent.run(
                task=task, context=agent_context, send_message_callback=self.send_message
            )

            if not question_result.get("success"):
                self._update_agent_status("QuestionGenerationAgent", "error")
                return {
                    "success": False,
                    "error": "question_agent_execution_failed",
                    "details": question_result,
                }

            # Check for rejections FIRST (before checking if submitted)
            result_data = question_result.get("result")
            if isinstance(result_data, dict) and result_data.get("task_rejected"):
                self.logger.separator()
                self.logger.warning("Question generation rejected")
                self._update_agent_status("QuestionGenerationAgent", "error")
                return {
                    "success": False,
                    "error": "task_rejected",
                    "reason": result_data.get(
                        "reason", "Required knowledge is missing from the knowledge base."
                    ),
                    "message": "QuestionGenerationAgent rejected this task because the knowledge base lacks the required content.",
                }

            # Ensure the agent submitted a question
            if self.question_agent.submitted:
                self.logger.success("QuestionGenerationAgent submitted a question")
                self._update_agent_status("QuestionGenerationAgent", "done")
            else:
                self.logger.warning(
                    "QuestionGenerationAgent did not submit a question; moving to next round"
                )
                continue

            # Retrieve the submitted question from the queue (before delivering messages)
            question = None
            messages_to_deliver = []
            while not self.message_queue.empty():
                msg = await self.message_queue.get()
                if msg.message_type == "validate_request":
                    question = msg.content.get("question")
                else:
                    messages_to_deliver.append(msg)

            # Return non-question messages to the queue
            for msg in messages_to_deliver:
                await self.message_queue.put(msg)

            # Deliver other pending messages
            await self.deliver_messages()

            if not question:
                self.logger.warning("QuestionGenerationAgent did not submit a question")
                continue

            self.logger.success("Question submitted for validation")

            self.logger.info("Stage 2: Validation workflow starting...")
            self.logger.debug(f"  Validating question: {question.get('question', '')[:60]}...")
            self._update_agent_status("ValidationWorkflow", "running")

            # Send progress update
            await self._send_ws_update(
                "progress", {"stage": "validating", "progress": {"round": round_num}}
            )

            # Attach knowledge point for validation retrieval
            question["knowledge_point"] = requirement.get("knowledge_point", "")

            # Execute validation workflow (retrieve → validate → return)
            # Pass reference question for innovation check
            reference_question = requirement.get("reference_question")
            validation_result = await self.validation_workflow.validate(
                question, reference_question
            )

            # Evaluate validation decision
            decision = validation_result.get("decision")

            if decision == "approve":
                self.logger.separator()
                self.logger.success("Question approved by validation")
                self._update_agent_status("ValidationWorkflow", "done")

                # Validate validation_result structure before building result
                issues = validation_result.get("issues", [])
                suggestions = validation_result.get("suggestions", [])

                # Log types for debugging
                self.logger.debug(
                    f"Validation result - issues type: {type(issues)}, suggestions type: {type(suggestions)}"
                )

                # Ensure issues and suggestions are lists
                if not isinstance(issues, list):
                    self.logger.warning(
                        f"Issues is not a list (type: {type(issues)}), converting..."
                    )
                    if isinstance(issues, dict):
                        issues = [issues]
                    else:
                        issues = []

                if not isinstance(suggestions, list):
                    self.logger.warning(
                        f"Suggestions is not a list (type: {type(suggestions)}), converting..."
                    )
                    if isinstance(suggestions, dict):
                        suggestions = [suggestions]
                    else:
                        suggestions = []

                result = {
                    "success": True,
                    "question": question,
                    "validation": {
                        "decision": decision,
                        "issues": issues,
                        "suggestions": suggestions,
                        "reasoning": validation_result.get("reasoning", ""),
                    },
                    "rounds": round_num,
                }

                # Log final result structure
                self.logger.debug(
                    f"Result structure - validation.issues type: {type(result['validation']['issues'])}, validation.suggestions type: {type(result['validation']['suggestions'])}"
                )

                # Persist results if output_dir is provided
                if self.output_dir:
                    try:
                        # timestamped subdirectory
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        output_path = Path(self.output_dir) / f"question_{timestamp}"
                        output_path.mkdir(parents=True, exist_ok=True)

                        # result JSON
                        with open(output_path / "result.json", "w", encoding="utf-8") as f:
                            json.dump(result, f, indent=2, ensure_ascii=False)

                        # question markdown
                        md_content = f"""# Generated Question

**Knowledge point**: {requirement.get("knowledge_point")}
**Difficulty**: {requirement.get("difficulty")}
**Type**: {requirement.get("question_type")}

---

## Question
{question.get("question")}

"""
                        if question.get("options"):
                            md_content += "## Options\n"
                            for key, value in question.get("options", {}).items():
                                md_content += f"- **{key}**: {value}\n"
                            md_content += "\n"

                        md_content += f"""
## Answer
{question.get("correct_answer")}

## Explanation
{question.get("explanation")}

---
**Validation**: Approved after {round_num} round(s)
"""
                        with open(output_path / "question.md", "w", encoding="utf-8") as f:
                            f.write(md_content)

                        self.logger.info(f"Results saved to: {output_path}")
                        result["output_dir"] = str(output_path)

                    except Exception as e:
                        self.logger.warning(f"Failed to save artifacts: {e}")

                return result

            # Handle modification/regeneration decisions
            if decision in ["request_modification", "request_regeneration"]:
                self.logger.info(f"Validation decision: {decision}")
                self.logger.debug(f"Issues: {validation_result.get('issues')}")
                self.logger.debug(f"Suggestions: {validation_result.get('suggestions')}")
                self._update_agent_status("ValidationWorkflow", "pending")

                # Send feedback back to the question agent
                message = Message(
                    from_agent="QuestionValidationWorkflow",
                    to_agent="QuestionGenerationAgent",
                    message_type=decision,
                    content={
                        "issues": validation_result.get("issues", []),
                        "suggestions": validation_result.get("suggestions", []),
                        "reasoning": validation_result.get("reasoning", ""),
                    },
                )
                self.question_agent.receive_message(message)

                # Continue to next round
                continue

            self.logger.warning(f"Unknown validation decision: {decision}")
            continue

        self.logger.separator()
        self.logger.warning(f"Maximum rounds reached ({self.max_rounds})")

        # Return as extended question instead of failure
        last_question = self.question_agent.current_question
        if last_question:
            # Get extension analysis from validation workflow
            # Build shared context from retrieved knowledge
            shared_context = ""
            if hasattr(self.question_agent, "retrieved_knowledge"):
                for k in self.question_agent.retrieved_knowledge:
                    shared_context += f"{k.get('answer', '')}\n\n"

            extension_analysis = await self.validation_workflow.analyze_extension(
                last_question, shared_context
            )

            self.logger.info("Question marked as extended (beyond KB scope)")
            return {
                "success": True,
                "question": last_question,
                "validation": {
                    "decision": "extended",
                    "reasoning": extension_analysis.get("reasoning", ""),
                    "kb_connection": extension_analysis.get("kb_connection", ""),
                    "extended_aspect": extension_analysis.get("extended_aspect", ""),
                },
                "rounds": self.max_rounds,
                "extended": True,
            }
        else:
            return {
                "success": False,
                "error": f"Maximum rounds reached ({self.max_rounds}) without generating a question",
                "last_question": None,
            }

    async def generate_multiple_questions(
        self,
        base_requirement: dict[str, Any],
        num_questions: int,
        precomputed_queries: list[str] | None = None,
        precomputed_retrievals: list[dict[str, Any]] | None = None,
        precomputed_summary: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate multiple questions based on a single high-level requirement.
        """
        if num_questions <= 0:
            raise ValueError("num_questions must be greater than zero")

        self._suppress_logging()

        # Step 1: plan retrieval queries and gather context
        queries = precomputed_queries or await self._generate_search_queries(
            base_requirement, max(3, num_questions)
        )
        retrievals = precomputed_retrievals or await self._gather_retrieval_context(queries)
        knowledge_summary = precomputed_summary or self._summarize_retrievals(retrievals)

        if (
            not retrievals
            or not knowledge_summary
            or knowledge_summary.strip() == "No retrieval context available."
        ):
            return {
                "success": False,
                "error": "knowledge_not_found",
                "message": "Knowledge base does not contain relevant information for the request.",
            }

        # Step 2: ask LLM to produce sub-requirements
        child_requirements = await self._generate_child_requirements(
            base_requirement, knowledge_summary, num_questions
        )

        if not child_requirements:
            # Fallback: simple numbered variants
            child_requirements = [
                {
                    "title": f"Variant #{idx}",
                    "question_type": base_requirement.get("question_type"),
                    "difficulty": base_requirement.get("difficulty"),
                    "additional_requirements": f"Create a distinct scenario #{idx} using the same knowledge point.",
                }
                for idx in range(1, num_questions + 1)
            ]

        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        self.logger.section(f"Batch Generation: {num_questions} question(s)")

        for idx in range(1, num_questions + 1):
            self.logger.separator("-")
            self.logger.stage(f"Generating variant #{idx}/{num_questions}")

            # Send progress update
            await self._send_ws_update(
                "progress",
                {"stage": "generating", "progress": {"current": idx, "total": num_questions}},
            )

            # Clear Agent history, ensure each question is independent
            self.question_agent.reset()

            requirement_variant = copy.deepcopy(base_requirement)
            child_req = child_requirements[idx - 1] if idx - 1 < len(child_requirements) else {}

            if child_req.get("question_type"):
                requirement_variant["question_type"] = child_req["question_type"]
            if child_req.get("difficulty"):
                requirement_variant["difficulty"] = child_req["difficulty"]

            existing_extra = requirement_variant.get("additional_requirements", "").strip()
            child_extra = child_req.get("additional_requirements", "").strip()
            title = child_req.get("title", f"Variant #{idx}")

            directive = (
                f"[Auto-derived sub requirement #{idx}: {title}]\n"
                "Maintain the exact same core knowledge point(s) as the base requirement.\n"
                "Use the retrieved knowledge summary to shape the scenario.\n"
                "Ensure the scenario and reasoning steps are distinct from other variants.\n"
                f"{child_extra}"
            )

            combined_requirements = "\n\n".join(
                part for part in [existing_extra, directive] if part
            )
            requirement_variant["additional_requirements"] = combined_requirements
            requirement_variant["batch_index"] = idx

            result = await self.generate_question(requirement_variant)

            if result.get("success"):
                results.append(result)
            else:
                failures.append(
                    {"index": idx, "error": result.get("error"), "reason": result.get("reason")}
                )
                # If any child requirement fails (e.g., due to knowledge issues), stop the batch early
                self.logger.error(f"Batch aborted due to failure while generating variant #{idx}")
                break

        summary = {
            "success": len(results) == num_questions and len(failures) == 0,
            "requested": num_questions,
            "completed": len(results),
            "failed": len(failures),
            "search_queries": queries,
            "knowledge_summary": knowledge_summary,
            "child_requirements": child_requirements,
            "results": results,
            "failures": failures,
        }

        # Persist batch results if output_dir is provided
        if self.output_dir:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = Path(self.output_dir)
                out_path.mkdir(parents=True, exist_ok=True)
                batch_file = out_path / f"batch_{timestamp}.json"
                with open(batch_file, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                summary["output_file"] = str(batch_file)
                self.logger.info(f"Batch results saved to: {batch_file}")
            except Exception as e:
                self.logger.warning(f"Failed to save batch results: {e}")

        self.logger.section("Batch Generation Summary")
        self.logger.info(f"Requested : {num_questions}")
        self.logger.info(f"Completed : {len(results)}")
        self.logger.info(f"Failed    : {len(failures)}")

        return summary

    async def generate_questions_from_prompt(
        self, requirement_text: str, num_questions: int
    ) -> dict[str, Any]:
        """
        Entry point for users supplying only natural-language requirements.
        """
        self._suppress_logging()

        queries = await self._generate_search_queries_from_text(
            requirement_text, max(3, num_questions)
        )
        retrievals = await self._gather_retrieval_context(queries)
        knowledge_summary = self._summarize_retrievals(retrievals)

        # Check if any content was retrieved
        has_content = any(retrieval.get("answer", "").strip() for retrieval in retrievals)

        if not has_content:
            return {
                "success": False,
                "error": "knowledge_not_found",
                "message": "Knowledge base does not contain relevant information for the request.",
                "search_queries": queries,
                "knowledge_summary": knowledge_summary,
            }

        relevant = await self._check_retrieval_relevance(requirement_text, knowledge_summary)
        if not relevant:
            return {
                "success": False,
                "error": "knowledge_not_found",
                "message": "Knowledge base appears unrelated to the requested topic.",
                "search_queries": queries,
                "knowledge_summary": knowledge_summary,
            }

        base_requirement = await self._interpret_requirement_text(requirement_text)
        return await self.generate_multiple_questions(
            base_requirement,
            num_questions,
            precomputed_queries=queries,
            precomputed_retrievals=retrievals,
            precomputed_summary=knowledge_summary,
        )

    async def _plan_sub_focuses(
        self,
        base_requirement: dict[str, Any],
        shared_context: str,
        num_questions: int,
    ) -> list[dict[str, Any]]:
        """Plan distinct sub-focuses for each question in one LLM call."""
        system_prompt = (
            "You are an educational content planner. Given a base requirement and knowledge context, "
            "create distinct sub-focuses for generating multiple questions on the SAME topic. "
            "Each sub-focus should describe a unique angle, scenario, or aspect to test. "
            'Output JSON with key "focuses" containing an array of objects, each with: '
            '"id" (string like "q_1"), "focus" (string describing the specific angle), '
            '"scenario_hint" (brief scenario suggestion).'
        )
        user_prompt = (
            f"Base requirement:\n{json.dumps(base_requirement, ensure_ascii=False, indent=2)}\n\n"
            f"Available knowledge context:\n{shared_context[:3000]}...\n\n"
            f"Generate exactly {num_questions} distinct sub-focuses in JSON."
        )
        try:
            content = await self._call_llm(
                system_prompt=system_prompt, user_prompt=user_prompt, stage="plan_sub_focuses"
            )
            parsed = json.loads(content)
            focuses = parsed.get("focuses", [])
            if not isinstance(focuses, list):
                focuses = []
        except Exception as e:
            self.logger.warning(f"Failed to plan sub-focuses: {e}")
            focuses = []

        # Fallback: create simple numbered focuses
        if len(focuses) < num_questions:
            for i in range(len(focuses), num_questions):
                focuses.append(
                    {
                        "id": f"q_{i + 1}",
                        "focus": f"Variant {i + 1}: Different scenario using the same knowledge point",
                        "scenario_hint": f"Create a distinct problem #{i + 1}",
                    }
                )

        return focuses[:num_questions]

    async def _generate_single_question_with_context(
        self,
        question_id: str,
        base_requirement: dict[str, Any],
        focus: dict[str, Any],
        shared_context: str,
        full_plan: list[dict[str, Any]],
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """Generate a single question with shared context and full plan awareness."""
        async with semaphore:
            try:
                # Send progress update
                await self._send_ws_update(
                    "question_update",
                    {
                        "question_id": question_id,
                        "status": "generating",
                        "focus": focus.get("focus", ""),
                    },
                )

                # Create a fresh agent for this question
                gen_agent_config = self.config.get("agents", {}).get("question_generation", {})
                max_gen_iterations = gen_agent_config.get("max_iterations", 5)

                question_agent = QuestionGenerationAgent(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    max_iterations=max_gen_iterations,
                    kb_name=self.kb_name,
                    token_stats_callback=self.update_token_stats,
                )

                # Build requirement with focus and plan awareness
                requirement_variant = copy.deepcopy(base_requirement)

                # Build plan summary to prevent duplication
                other_focuses = [f for f in full_plan if f.get("id") != question_id]
                plan_summary = "\n".join(
                    [f"- {f.get('id')}: {f.get('focus', 'N/A')}" for f in other_focuses]
                )

                focus_directive = (
                    f"[Question {question_id}]\n"
                    f"Focus: {focus.get('focus', 'Generate a question')}\n"
                    f"Scenario hint: {focus.get('scenario_hint', '')}\n\n"
                    "IMPORTANT: The following focuses are assigned to OTHER questions in this batch. "
                    "You MUST create a question that is DISTINCT from these:\n"
                    f"{plan_summary}\n\n"
                    "Use the provided knowledge context to ensure accuracy."
                )

                existing_extra = requirement_variant.get("additional_requirements", "").strip()
                requirement_variant["additional_requirements"] = "\n\n".join(
                    filter(None, [existing_extra, focus_directive])
                )
                requirement_variant["batch_index"] = question_id
                requirement_variant["_shared_context"] = shared_context

                # Set up the agent
                question_agent.set_requirement(requirement_variant)

                # Pre-populate retrieved knowledge with shared context
                question_agent.retrieved_knowledge = [
                    {
                        "query": "shared_batch_context",
                        "answer": shared_context,
                    }
                ]

                # Create message queue for this agent
                local_queue = asyncio.Queue()

                async def local_send_message(msg):
                    await local_queue.put(msg)

                question_agent.send_message = local_send_message

                # Run generation loop
                for round_num in range(1, self.max_rounds + 1):
                    await self._send_ws_update(
                        "question_update",
                        {"question_id": question_id, "status": "generating", "round": round_num},
                    )

                    question_agent.submitted = False
                    task = f"Generate a question based on the focus: {focus.get('focus', '')}"

                    if round_num > 1:
                        task = "Revise the question based on validation feedback"

                    question_result = await question_agent.run(
                        task=task,
                        context={"requirement": requirement_variant, "round_num": round_num},
                        send_message_callback=local_send_message,
                    )

                    if not question_result.get("success"):
                        continue

                    # Check for rejection
                    result_data = question_result.get("result")
                    if isinstance(result_data, dict) and result_data.get("task_rejected"):
                        return {
                            "success": False,
                            "question_id": question_id,
                            "error": "task_rejected",
                            "reason": result_data.get("reason", "Knowledge missing"),
                        }

                    if not question_agent.submitted:
                        continue

                    # Get submitted question from queue
                    question = None
                    while not local_queue.empty():
                        msg = await local_queue.get()
                        if msg.message_type == "validate_request":
                            question = msg.content.get("question")

                    if not question:
                        continue

                    # Validate
                    await self._send_ws_update(
                        "question_update",
                        {"question_id": question_id, "status": "validating", "round": round_num},
                    )

                    question["knowledge_point"] = base_requirement.get("knowledge_point", "")
                    reference_question = base_requirement.get("reference_question")
                    validation_result = await self.validation_workflow.validate(
                        question, reference_question
                    )

                    decision = validation_result.get("decision")

                    if decision == "approve":
                        await self._send_ws_update(
                            "question_update", {"question_id": question_id, "status": "done"}
                        )

                        # Save question to disk
                        output_dir = self._save_question_result(
                            question=question,
                            requirement=base_requirement,
                            validation=validation_result,
                            round_num=round_num,
                            extended=False,
                        )

                        result = {
                            "success": True,
                            "question_id": question_id,
                            "question": question,
                            "validation": validation_result,
                            "rounds": round_num,
                            "focus": focus,
                        }
                        if output_dir:
                            result["output_dir"] = output_dir
                        return result

                    # Send feedback for next round
                    if decision in ["request_modification", "request_regeneration"]:
                        message = Message(
                            from_agent="QuestionValidationWorkflow",
                            to_agent="QuestionGenerationAgent",
                            message_type=decision,
                            content={
                                "issues": validation_result.get("issues", []),
                                "suggestions": validation_result.get("suggestions", []),
                                "reasoning": validation_result.get("reasoning", ""),
                            },
                        )
                        question_agent.receive_message(message)

                # Max rounds reached - return as extended question instead of failure
                last_question = question_agent.current_question
                if last_question:
                    # Get extension analysis from validation workflow
                    extension_analysis = await self.validation_workflow.analyze_extension(
                        last_question, shared_context
                    )

                    await self._send_ws_update(
                        "question_update",
                        {"question_id": question_id, "status": "done", "extended": True},
                    )

                    validation = {
                        "decision": "extended",
                        "reasoning": extension_analysis.get("reasoning", ""),
                        "kb_connection": extension_analysis.get("kb_connection", ""),
                        "extended_aspect": extension_analysis.get("extended_aspect", ""),
                    }

                    # Save extended question to disk
                    output_dir = self._save_question_result(
                        question=last_question,
                        requirement=base_requirement,
                        validation=validation,
                        round_num=self.max_rounds,
                        extended=True,
                    )

                    result = {
                        "success": True,
                        "question_id": question_id,
                        "question": last_question,
                        "validation": validation,
                        "rounds": self.max_rounds,
                        "focus": focus,
                        "extended": True,
                    }
                    if output_dir:
                        result["output_dir"] = output_dir
                    return result
                else:
                    # No question was generated at all
                    await self._send_ws_update(
                        "question_update", {"question_id": question_id, "status": "error"}
                    )
                    return {
                        "success": False,
                        "question_id": question_id,
                        "error": f"Max rounds ({self.max_rounds}) reached without generating a question",
                    }

            except Exception as e:
                self.logger.error(f"Error generating question {question_id}: {e}")
                await self._send_ws_update(
                    "question_update", {"question_id": question_id, "status": "error"}
                )
                return {
                    "success": False,
                    "question_id": question_id,
                    "error": str(e),
                }

    async def generate_questions_parallel(
        self,
        base_requirement: dict[str, Any],
        num_questions: int,
    ) -> dict[str, Any]:
        """
        Generate multiple questions in parallel with shared context.

        New flow:
        1. Split user input into N RAG queries
        2. Run RAG queries in parallel
        3. Merge results into shared context
        4. Plan sub-focuses for all questions at once
        5. Generate questions in parallel (with semaphore control)
        """
        if num_questions <= 0:
            raise ValueError("num_questions must be greater than zero")

        self._suppress_logging()

        # Send initial progress
        await self._send_ws_update(
            "progress",
            {
                "stage": "planning",
                "progress": {"status": "splitting_queries"},
                "total": num_questions,
            },
        )

        # Step 1: Split into RAG queries
        self.logger.section(f"Parallel Generation: {num_questions} question(s)")
        self.logger.info("Step 1: Splitting into RAG queries...")

        queries = await self._generate_search_queries(base_requirement, self.rag_query_count)
        self.logger.info(f"Generated {len(queries)} search queries")

        # Step 2: Run RAG queries in parallel
        await self._send_ws_update(
            "progress",
            {"stage": "researching", "progress": {"status": "retrieving"}, "queries": queries},
        )
        self.logger.info("Step 2: Retrieving knowledge in parallel...")

        retrievals = await self._gather_retrieval_context(queries)

        # Step 3: Merge into shared context
        shared_context = self._summarize_retrievals(retrievals)

        # Check if we have any content
        has_content = any(r.get("answer", "").strip() for r in retrievals)
        if not has_content:
            return {
                "success": False,
                "error": "knowledge_not_found",
                "message": "Knowledge base does not contain relevant information for the request.",
                "search_queries": queries,
            }

        self.logger.info(f"Merged {len(retrievals)} retrieval results into shared context")

        # Step 4: Plan sub-focuses
        await self._send_ws_update(
            "progress", {"stage": "planning", "progress": {"status": "planning_focuses"}}
        )
        self.logger.info("Step 3: Planning sub-focuses for all questions...")

        sub_focuses = await self._plan_sub_focuses(base_requirement, shared_context, num_questions)
        self.logger.info(f"Planned {len(sub_focuses)} sub-focuses")

        # Send focuses to frontend
        await self._send_ws_update(
            "progress",
            {
                "stage": "generating",
                "progress": {"status": "starting_parallel"},
                "total": num_questions,
                "focuses": sub_focuses,
            },
        )

        # Step 5: Generate questions in parallel
        self.logger.info(
            f"Step 4: Generating {num_questions} questions in parallel (max {self.max_parallel_questions} concurrent)..."
        )

        semaphore = asyncio.Semaphore(self.max_parallel_questions)

        tasks = [
            self._generate_single_question_with_context(
                question_id=focus.get("id", f"q_{i + 1}"),
                base_requirement=base_requirement,
                focus=focus,
                shared_context=shared_context,
                full_plan=sub_focuses,
                semaphore=semaphore,
            )
            for i, focus in enumerate(sub_focuses)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 6: Aggregate results
        successes = []
        failures = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failures.append(
                    {
                        "question_id": f"q_{i + 1}",
                        "error": str(result),
                    }
                )
            elif result.get("success"):
                successes.append(result)
            else:
                failures.append(
                    {
                        "question_id": result.get("question_id", f"q_{i + 1}"),
                        "error": result.get("error", "Unknown error"),
                        "reason": result.get("reason", ""),
                    }
                )

        summary = {
            "success": len(successes) == num_questions,
            "requested": num_questions,
            "completed": len(successes),
            "failed": len(failures),
            "search_queries": queries,
            "shared_context": shared_context[:500] + "..."
            if len(shared_context) > 500
            else shared_context,
            "sub_focuses": sub_focuses,
            "results": successes,
            "failures": failures,
        }

        # Persist results if output_dir is provided
        if self.output_dir:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = Path(self.output_dir)
                out_path.mkdir(parents=True, exist_ok=True)
                batch_file = out_path / f"parallel_batch_{timestamp}.json"
                with open(batch_file, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                summary["output_file"] = str(batch_file)
                self.logger.info(f"Results saved to: {batch_file}")
            except Exception as e:
                self.logger.warning(f"Failed to save results: {e}")

        # Send completion
        await self._send_ws_update(
            "progress",
            {
                "stage": "complete",
                "completed": len(successes),
                "failed": len(failures),
                "total": num_questions,
            },
        )

        self.logger.section("Parallel Generation Summary")
        self.logger.info(f"Requested : {num_questions}")
        self.logger.info(f"Completed : {len(successes)}")
        self.logger.info(f"Failed    : {len(failures)}")

        return summary

    # =========================================================================
    # Custom Mode Methods - New streamlined flow without iteration
    # =========================================================================

    async def _single_rag_search_naive(self, query: str) -> dict[str, Any]:
        """Execute a single RAG search using naive mode."""
        result = await rag_search(
            query=query,
            kb_name=self.kb_name,
            mode="naive",
            only_need_context=True,
        )
        return {
            "query": query,
            "answer": result.get("answer", ""),
            "mode": "naive",
        }

    async def _gather_retrieval_context_naive(self, queries: list[str]) -> list[dict[str, Any]]:
        """Run retrieval for each query in parallel using naive mode."""
        self._update_agent_status("RetrievalTool", "running")
        self.logger.info(
            f"Retrieving background knowledge for {len(queries)} queries (naive mode)..."
        )

        # Execute all queries in parallel
        tasks = [self._single_rag_search_naive(query) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        retrievals = []
        for i, result in enumerate(results):
            query = queries[i]
            if isinstance(result, Exception):
                self.logger.warning(f"Retrieval failed for query '{query}': {result}")
                continue

            self.logger.debug(f"  → Query: {query[:50]}... (retrieved)")
            retrievals.append(
                {
                    "query": query,
                    "answer": result.get("answer", ""),
                }
            )

        self._update_agent_status("RetrievalTool", "done")
        return retrievals

    async def _generate_question_plan(
        self,
        base_requirement: dict[str, Any],
        knowledge_summary: str,
        num_questions: int,
    ) -> dict[str, Any]:
        """
        Generate a question plan with focuses for each question.

        Args:
            base_requirement: Base requirement with knowledge_point, difficulty, question_type
            knowledge_summary: Summary of retrieved background knowledge
            num_questions: Number of questions to generate

        Returns:
            Plan dict with "focuses" array containing {id, focus, type} for each question
        """
        difficulty = base_requirement.get("difficulty", "medium")
        question_type = base_requirement.get("question_type", "written")
        knowledge_point = base_requirement.get("knowledge_point", "")

        system_prompt = (
            "You are an educational content planner. Given a topic, difficulty level, "
            "question type, and background knowledge, create a structured question plan.\n\n"
            "Each question focus should:\n"
            "1. Test a specific aspect or angle of the knowledge point\n"
            "2. Be distinct from other focuses (different scenarios, applications, or perspectives)\n"
            "3. Match the specified difficulty level\n"
            "4. Be achievable with the provided background knowledge\n\n"
            "CRITICAL: Return ONLY valid JSON. Do not wrap in markdown code blocks (```json). "
            "Do not include any explanatory text before or after the JSON. "
            "Your response must start with { and end with }.\n\n"
            'Output JSON with key "focuses" containing an array of objects, each with:\n'
            '- "id": string like "q_1", "q_2", etc.\n'
            '- "focus": string describing what specific aspect this question will test\n'
            '- "type": "choice" or "written" (should match the requested type)\n'
        )

        user_prompt = (
            f"Topic/Knowledge Point: {knowledge_point}\n"
            f"Difficulty: {difficulty}\n"
            f"Question Type: {question_type}\n"
            f"Number of Questions: {num_questions}\n\n"
            f"Background Knowledge:\n{knowledge_summary[:3000]}...\n\n"
            f"Generate exactly {num_questions} distinct question focuses in JSON format."
        )

        try:
            content = await self._call_llm(
                system_prompt=system_prompt, user_prompt=user_prompt, stage="generate_question_plan"
            )

            # Validate content before JSON parsing
            if not content or content.strip() == "":
                self.logger.error("LLM returned empty content for question plan generation")
                self.logger.error(f"Response content: {repr(content)}")
                focuses = []
            else:
                try:
                    # Extract JSON from markdown code blocks if present
                    json_content = self._extract_json_from_markdown(content)
                    parsed = json.loads(json_content)
                    focuses = parsed.get("focuses", [])
                    if not isinstance(focuses, list):
                        focuses = []
                except json.JSONDecodeError as json_err:
                    self.logger.error(f"JSON parsing failed for question plan: {json_err}")
                    self.logger.error(f"Response content (first 500 chars): {content[:500]}")
                    focuses = []
        except Exception as e:
            self.logger.warning(f"Failed to generate question plan: {e}")
            focuses = []

        # Fallback: create simple numbered focuses
        if len(focuses) < num_questions:
            for i in range(len(focuses), num_questions):
                focuses.append(
                    {
                        "id": f"q_{i + 1}",
                        "focus": f"Aspect {i + 1} of {knowledge_point}",
                        "type": question_type,
                    }
                )

        # Ensure all focuses have the correct type
        for focus in focuses:
            if "type" not in focus:
                focus["type"] = question_type
            if "id" not in focus:
                focus["id"] = f"q_{focuses.index(focus) + 1}"

        return {
            "knowledge_point": knowledge_point,
            "difficulty": difficulty,
            "question_type": question_type,
            "num_questions": num_questions,
            "focuses": focuses[:num_questions],
        }

    def _save_knowledge_json(
        self,
        batch_dir: Path,
        queries: list[str],
        retrievals: list[dict[str, Any]],
    ) -> str:
        """Save background knowledge to knowledge.json."""
        knowledge_data = {
            "queries": queries,
            "retrievals": retrievals,
            "total_queries": len(queries),
            "successful_retrievals": len([r for r in retrievals if r.get("answer")]),
        }

        knowledge_file = batch_dir / "knowledge.json"
        with open(knowledge_file, "w", encoding="utf-8") as f:
            json.dump(knowledge_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Background knowledge saved to: {knowledge_file}")
        return str(knowledge_file)

    def _save_plan_json(self, batch_dir: Path, plan: dict[str, Any]) -> str:
        """Save question plan to plan.json."""
        plan_file = batch_dir / "plan.json"
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Question plan saved to: {plan_file}")
        return str(plan_file)

    def _save_custom_question_result(
        self,
        batch_dir: Path,
        question_id: str,
        question: dict[str, Any],
        validation: dict[str, Any],
        focus: dict[str, Any],
    ) -> str:
        """Save a single question result in custom mode."""
        question_dir = batch_dir / question_id
        question_dir.mkdir(parents=True, exist_ok=True)

        # Build result structure
        result = {
            "question_id": question_id,
            "focus": focus,
            "question": question,
            "validation": validation,
        }

        # Save result.json
        result_file = question_dir / "result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Build question.md
        relevance = validation.get("relevance", "unknown")
        kb_coverage = validation.get("kb_coverage", "")
        extension_points = validation.get("extension_points", "")

        md_content = f"""# Generated Question

**Focus**: {focus.get("focus", "N/A")}
**Type**: {focus.get("type", question.get("question_type", "N/A"))}

---

## Question
{question.get("question", "")}

"""
        if question.get("options"):
            md_content += "## Options\n"
            for key, value in question.get("options", {}).items():
                md_content += f"- **{key}**: {value}\n"
            md_content += "\n"

        md_content += f"""
## Answer
{question.get("correct_answer", "")}

## Explanation
{question.get("explanation", "")}

---

## Relevance Analysis

**Relevance Level**: {relevance}

**Knowledge Base Coverage**:
{kb_coverage}
"""
        if extension_points:
            md_content += f"""
**Extension Points**:
{extension_points}
"""

        md_file = question_dir / "question.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(md_content)

        return str(question_dir)

    async def _generate_single_question_custom(
        self,
        focus: dict[str, Any],
        base_requirement: dict[str, Any],
        knowledge_summary: str,
    ) -> dict[str, Any]:
        """
        Generate a single question without iteration loop (custom mode).

        Returns:
            Dict with question data
        """
        question_id = focus.get("id", "q_1")
        question_type = focus.get("type", base_requirement.get("question_type", "written"))
        focus_text = focus.get("focus", "")
        knowledge_point = base_requirement.get("knowledge_point", "")
        difficulty = base_requirement.get("difficulty", "medium")

        system_prompt = (
            "You are a professional question designer. Generate a high-quality exam question "
            "based on the provided focus and background knowledge.\n\n"
            "Requirements:\n"
            "1. The question must align with the specified focus\n"
            "2. Use the background knowledge to ensure accuracy\n"
            "3. Match the difficulty level\n"
            "4. Provide a detailed explanation\n\n"
            "CRITICAL: Return ONLY valid JSON. Do not wrap in markdown code blocks (```json). "
            "Do not include any explanatory text before or after the JSON. "
            "Your response must start with { and end with }.\n"
        )

        if question_type == "choice":
            output_format = """Output JSON format:
{
    "question_type": "choice",
    "question": "question content",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "correct_answer": "A/B/C/D",
    "explanation": "detailed explanation"
}"""
        else:
            output_format = """Output JSON format:
{
    "question_type": "written",
    "question": "question content",
    "correct_answer": "detailed answer",
    "explanation": "detailed explanation"
}"""

        user_prompt = (
            f"Knowledge Point: {knowledge_point}\n"
            f"Focus: {focus_text}\n"
            f"Difficulty: {difficulty}\n"
            f"Question Type: {question_type}\n\n"
            f"Background Knowledge:\n{knowledge_summary[:4000]}\n\n"
            f"{output_format}"
        )

        try:
            content = await self._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                stage=f"generate_question_{question_id}",
            )

            # Validate content before JSON parsing
            if not content or content.strip() == "":
                self.logger.error(f"LLM returned empty content for question {question_id}")
                self.logger.error(f"Response content: {repr(content)}")
                return {
                    "success": False,
                    "error": "LLM returned empty response",
                }

            try:
                # Extract JSON from markdown code blocks if present
                json_content = self._extract_json_from_markdown(content)
                question = json.loads(json_content)
                question["knowledge_point"] = knowledge_point
                return {
                    "success": True,
                    "question": question,
                }
            except json.JSONDecodeError as json_err:
                self.logger.error(f"JSON parsing failed for question {question_id}: {json_err}")
                self.logger.error(f"Response content (first 500 chars): {content[:500]}")
                return {
                    "success": False,
                    "error": f"Invalid JSON response: {str(json_err)}",
                }
        except Exception as e:
            self.logger.error(f"Failed to generate question {question_id}: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    async def generate_questions_custom(
        self,
        base_requirement: dict[str, Any],
        num_questions: int,
    ) -> dict[str, Any]:
        """
        Custom mode: Generate questions with the new streamlined flow.

        Flow:
        1. Researching: Generate RAG queries, retrieve with naive mode, save knowledge.json
        2. Planning: Generate question plan, save plan.json
        3. Generating: For each focus, generate question + relevance analysis

        Args:
            base_requirement: Dict with knowledge_point, difficulty, question_type
            num_questions: Number of questions to generate

        Returns:
            Summary dict with all results
        """
        if num_questions <= 0:
            raise ValueError("num_questions must be greater than zero")

        self._suppress_logging()

        # Create batch directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = Path(self.output_dir) / f"batch_{timestamp}" if self.output_dir else None
        if batch_dir:
            batch_dir.mkdir(parents=True, exist_ok=True)

        self.logger.section(f"Custom Mode Generation: {num_questions} question(s)")

        # =====================================================================
        # Stage 1: Researching - Retrieve background knowledge
        # =====================================================================
        self.logger.stage("Stage 1: Researching")
        await self._send_ws_update(
            "progress",
            {
                "stage": "researching",
                "progress": {"status": "generating_queries"},
                "total": num_questions,
            },
        )

        # Generate search queries
        requirement_text = json.dumps(base_requirement, ensure_ascii=False)
        queries = await self._generate_search_queries_from_text(
            requirement_text, self.rag_query_count
        )
        self.logger.info(f"Generated {len(queries)} search queries: {queries}")

        await self._send_ws_update(
            "progress",
            {"stage": "researching", "progress": {"status": "retrieving"}, "queries": queries},
        )

        # Retrieve using naive mode
        retrievals = await self._gather_retrieval_context_naive(queries)
        knowledge_summary = self._summarize_retrievals(retrievals)

        # Check if we have any content
        has_content = any(r.get("answer", "").strip() for r in retrievals)
        if not has_content:
            self.logger.warning("No content retrieved from knowledge base")
            return {
                "success": False,
                "error": "knowledge_not_found",
                "message": "Knowledge base does not contain relevant information for the request.",
                "search_queries": queries,
            }

        # Save knowledge.json
        if batch_dir:
            self._save_knowledge_json(batch_dir, queries, retrievals)

        await self._send_ws_update(
            "progress", {"stage": "researching", "progress": {"status": "completed"}}
        )
        await self._send_ws_update("knowledge_saved", {"queries": queries})

        # =====================================================================
        # Stage 2: Planning - Generate question plan
        # =====================================================================
        self.logger.stage("Stage 2: Planning")
        await self._send_ws_update(
            "progress", {"stage": "planning", "progress": {"status": "creating_plan"}}
        )

        plan = await self._generate_question_plan(
            base_requirement, knowledge_summary, num_questions
        )
        focuses = plan.get("focuses", [])
        self.logger.info(f"Generated plan with {len(focuses)} focuses")

        # Save plan.json
        if batch_dir:
            self._save_plan_json(batch_dir, plan)

        await self._send_ws_update(
            "progress",
            {"stage": "planning", "progress": {"status": "completed"}, "focuses": focuses},
        )
        await self._send_ws_update("plan_ready", {"plan": plan, "focuses": focuses})

        # =====================================================================
        # Stage 3: Generating - Generate each question
        # =====================================================================
        self.logger.stage("Stage 3: Generating")
        await self._send_ws_update(
            "progress",
            {
                "stage": "generating",
                "progress": {"current": 0, "total": num_questions},
                "focuses": focuses,
            },
        )

        results = []
        failures = []

        for idx, focus in enumerate(focuses):
            question_id = focus.get("id", f"q_{idx + 1}")
            self.logger.info(f"Generating question {question_id}: {focus.get('focus', '')[:50]}...")

            await self._send_ws_update(
                "question_update",
                {
                    "question_id": question_id,
                    "status": "generating",
                    "focus": focus.get("focus", ""),
                },
            )

            # Generate question (single pass, no iteration)
            gen_result = await self._generate_single_question_custom(
                focus=focus,
                base_requirement=base_requirement,
                knowledge_summary=knowledge_summary,
            )

            if not gen_result.get("success"):
                self.logger.error(f"Failed to generate question {question_id}")
                failures.append(
                    {
                        "question_id": question_id,
                        "error": gen_result.get("error", "Unknown error"),
                    }
                )
                await self._send_ws_update(
                    "question_update", {"question_id": question_id, "status": "error"}
                )
                continue

            question = gen_result["question"]

            # Perform relevance analysis
            await self._send_ws_update(
                "question_update", {"question_id": question_id, "status": "analyzing"}
            )

            validation = await self.validation_workflow.analyze_relevance(
                question=question,
                knowledge_summary=knowledge_summary,
            )

            # Save result
            if batch_dir:
                self._save_custom_question_result(
                    batch_dir=batch_dir,
                    question_id=question_id,
                    question=question,
                    validation=validation,
                    focus=focus,
                )

            result = {
                "question_id": question_id,
                "focus": focus,
                "question": question,
                "validation": validation,
            }
            results.append(result)

            await self._send_ws_update(
                "question_update", {"question_id": question_id, "status": "done"}
            )
            await self._send_ws_update(
                "result",
                {
                    "question_id": question_id,
                    "question": question,
                    "validation": validation,
                    "focus": focus,
                    "index": idx,
                    "rounds": 1,  # Custom mode has single-pass generation
                },
            )

            # Update progress
            await self._send_ws_update(
                "progress",
                {"stage": "generating", "progress": {"current": idx + 1, "total": num_questions}},
            )

        # =====================================================================
        # Complete
        # =====================================================================
        summary = {
            "success": len(results) == num_questions,
            "requested": num_questions,
            "completed": len(results),
            "failed": len(failures),
            "search_queries": queries,
            "plan": plan,
            "results": results,
            "failures": failures,
        }

        # Save summary.json
        if batch_dir:
            summary_file = batch_dir / "summary.json"
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            summary["output_dir"] = str(batch_dir)
            self.logger.info(f"Summary saved to: {summary_file}")

        await self._send_ws_update(
            "progress",
            {
                "stage": "complete",
                "completed": len(results),
                "failed": len(failures),
                "total": num_questions,
            },
        )

        self.logger.section("Custom Mode Generation Summary")
        self.logger.info(f"Requested : {num_questions}")
        self.logger.info(f"Completed : {len(results)}")
        self.logger.info(f"Failed    : {len(failures)}")

        return summary
