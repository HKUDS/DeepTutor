#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ResearchPipeline 2.0 - Research workflow based on dynamic topic queue
Coordinates three stages: Planning -> Researching -> Reporting
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Callable


def _get_project_root() -> Path:
    """
    Get project root directory robustly by looking for marker files.
    Works regardless of how the script is invoked.
    """
    # Start from current file's directory
    current = Path(__file__).resolve().parent

    # Walk up looking for project markers (pyproject.toml, requirements.txt, or src/ directory)
    markers = ["pyproject.toml", "requirements.txt", ".git"]

    for _ in range(10):  # Limit to 10 levels up
        for marker in markers:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    # Fallback: use relative path from this file
    # This file is at: src/agents/research/research_pipeline.py
    # So project root is: ../../../
    return Path(__file__).resolve().parent.parent.parent.parent


# Get project root
PROJECT_ROOT = _get_project_root()

# Add project root to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.research.agents import (
    DecomposeAgent,
    ManagerAgent,
    NoteAgent,
    RephraseAgent,
    ReportingAgent,
    ResearchAgent,
)
from src.agents.research.data_structures import DynamicTopicQueue
from src.agents.research.utils import coerce_text
from src.agents.research.utils.citation_manager import CitationManager
from src.logging import get_logger
from src.tools.code_executor import run_code
from src.tools.paper_search_tool import PaperSearchTool
from src.tools.query_item_tool import query_numbered_item
from src.tools.rag_tool import rag_search
from src.tools.web_search import web_search


class ResearchPipeline:
    """DR-in-KG 2.0 Research workflow"""

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str,
        base_url: str,
        research_id: str | None = None,
        kb_name: str | None = None,
        progress_callback: Callable | None = None,
    ):
        """
        Initialize research workflow

        Args:
            config: Configuration dictionary
            api_key: API key
            base_url: API endpoint
            research_id: Research task ID (optional)
            kb_name: Knowledge base name (optional, if provided overrides config file setting)
            progress_callback: Progress callback function (optional), signature: callback(event: Dict[str, Any])
        """
        self.config = config
        self.progress_callback = progress_callback

        # If kb_name is provided, override config
        if kb_name is not None:
            if "rag" not in self.config:
                self.config["rag"] = {}
            self.config["rag"]["kb_name"] = kb_name
        self.api_key = api_key
        self.base_url = base_url
        self.input_topic: str | None = None
        self.optimized_topic: str | None = None

        # Generate research ID
        if research_id is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.research_id = f"research_{timestamp}"
        else:
            self.research_id = research_id

        # Set directories
        system_config = config.get("system", {})
        self.cache_dir = Path(system_config.get("output_base_dir", "./cache")) / self.research_id
        self.reports_dir = Path(system_config.get("reports_dir", "./reports"))

        # Create directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.plan_progress_file = self.cache_dir / "planning_progress.json"
        self.report_progress_file = self.cache_dir / "reporting_progress.json"
        self.queue_progress_file = self.cache_dir / "queue_progress.json"
        self._stage_events: dict[str, list[dict[str, Any]]] = {
            "planning": [],
            "reporting": [],
        }

        # Initialize queue
        queue_cfg = config.get("queue", {})
        self.queue = DynamicTopicQueue(
            self.research_id,
            max_length=queue_cfg.get("max_length"),
            state_file=str(self.queue_progress_file),
        )

        # Initialize unified logging system (must be before _init_agents)
        self._init_logger()

        # Initialize Agents
        self.agents = {}
        self._init_agents()

        # Tool instances
        self._paper_tool: PaperSearchTool | None = None

        # Citation manager
        self.citation_manager = CitationManager(self.research_id, self.cache_dir)

        # Lock for thread-safe progress file writing in parallel mode
        import threading

        self._progress_file_lock = threading.Lock()

    def _init_logger(self):
        """Initialize unified logging system"""
        # Get log_dir from config paths (user_log_dir from main.yaml)
        log_dir = self.config.get("paths", {}).get("user_log_dir") or self.config.get(
            "logging", {}
        ).get("log_dir")

        self.logger = get_logger(name="Research", log_dir=log_dir)
        self.logger.success("Logger initialized")

    def _init_agents(self):
        """Initialize all Agents"""
        if self.logger:
            self.logger.info("Initializing Agents...")

        self.agents = {
            "rephrase": RephraseAgent(self.config, self.api_key, self.base_url),
            "decompose": DecomposeAgent(self.config, self.api_key, self.base_url),
            "manager": ManagerAgent(self.config, self.api_key, self.base_url),
            "research": ResearchAgent(self.config, self.api_key, self.base_url),
            "note": NoteAgent(self.config, self.api_key, self.base_url),
            "reporting": ReportingAgent(self.config, self.api_key, self.base_url),
        }

        # Set Manager's queue
        self.agents["manager"].set_queue(self.queue)

        if self.logger:
            self.logger.success(f"Initialized {len(self.agents)} Agents")

    async def _call_tool_with_timeout(
        self, coro, timeout: float = 60.0, tool_name: str = "tool"
    ) -> Any:
        """
        Execute a coroutine with timeout support

        Args:
            coro: Coroutine to execute
            timeout: Timeout in seconds (default 60s)
            tool_name: Name of the tool for logging

        Returns:
            Result of the coroutine

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            self.logger.warning(f"Tool {tool_name} timed out after {timeout}s")
            raise

    async def _call_tool_with_retry(
        self,
        tool_func,
        *args,
        max_retries: int = 2,
        timeout: float = 60.0,
        tool_name: str = "tool",
        **kwargs,
    ) -> Any:
        """
        Call a tool function with retry and timeout support

        Args:
            tool_func: Tool function to call
            *args: Positional arguments for the function
            max_retries: Maximum number of retries (default 2)
            timeout: Timeout per attempt in seconds (default 60s)
            tool_name: Name of the tool for logging
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the tool function
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(tool_func):
                    result = await self._call_tool_with_timeout(
                        tool_func(*args, **kwargs), timeout=timeout, tool_name=tool_name
                    )
                else:
                    # For sync functions, run in executor
                    import functools

                    loop = asyncio.get_event_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, functools.partial(tool_func, *args, **kwargs)),
                        timeout=timeout,
                    )
                return result
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < max_retries:
                    self.logger.warning(
                        f"Tool {tool_name} attempt {attempt + 1} timed out, retrying..."
                    )
                    await asyncio.sleep(1)  # Brief pause before retry
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    self.logger.warning(
                        f"Tool {tool_name} attempt {attempt + 1} failed: {e}, retrying..."
                    )
                    await asyncio.sleep(1)

        # All retries exhausted
        self.logger.error(f"Tool {tool_name} failed after {max_retries + 1} attempts: {last_error}")
        raise last_error if last_error else RuntimeError(f"{tool_name} failed")

    async def _call_tool(self, tool_type: str, query: str) -> str:
        """Call tool and return raw string answer (JSON string or text)"""
        tool_type = (tool_type or "").lower()

        # Get timeout and retry settings from config
        tool_config = self.config.get("researching", {})
        default_timeout = tool_config.get("tool_timeout", 60)
        max_retries = tool_config.get("tool_max_retries", 2)

        try:
            if tool_type in ("rag_hybrid", "rag_naive", "rag"):
                rag_cfg = self.config.get("rag", {})
                kb_name = rag_cfg.get("kb_name", "DE-all")
                default_mode = rag_cfg.get("default_mode", "hybrid")
                fallback_mode = rag_cfg.get("fallback_mode", "naive")
                if tool_type == "rag_hybrid":
                    mode = "hybrid"
                elif tool_type == "rag_naive":
                    mode = "naive"
                else:
                    mode = default_mode
                try:
                    res = await self._call_tool_with_retry(
                        rag_search,
                        query=query,
                        kb_name=kb_name,
                        mode=mode,
                        max_retries=max_retries,
                        timeout=default_timeout,
                        tool_name=f"rag_search({mode})",
                    )
                except Exception:
                    # Retry with fallback mode
                    res = await self._call_tool_with_retry(
                        rag_search,
                        query=query,
                        kb_name=kb_name,
                        mode=fallback_mode,
                        max_retries=1,
                        timeout=default_timeout,
                        tool_name=f"rag_search({fallback_mode})",
                    )
                return json.dumps(res, ensure_ascii=False)

            if tool_type == "web_search":
                res = await self._call_tool_with_retry(
                    web_search,
                    query=query,
                    output_dir=str(self.cache_dir),
                    max_retries=max_retries,
                    timeout=default_timeout,
                    tool_name="web_search",
                )
                return json.dumps(res, ensure_ascii=False)

            if tool_type == "query_item":
                kb_name = self.config.get("rag", {}).get("kb_name", "ai_textbook")
                res = await self._call_tool_with_retry(
                    query_numbered_item,
                    identifier=query,
                    kb_name=kb_name,
                    max_retries=max_retries,
                    timeout=default_timeout,
                    tool_name="query_item",
                )
                return json.dumps(res, ensure_ascii=False)

            if tool_type == "paper_search":
                if self._paper_tool is None:
                    self._paper_tool = PaperSearchTool()
                years_limit = self.config.get("researching", {}).get("paper_search_years_limit", 3)
                papers = await self._call_tool_with_retry(
                    self._paper_tool.search_papers,
                    query=query,
                    max_results=3,
                    years_limit=years_limit,
                    max_retries=max_retries,
                    timeout=default_timeout,
                    tool_name="paper_search",
                )
                return json.dumps({"papers": papers}, ensure_ascii=False)

            if tool_type == "run_code":
                # Code execution has its own internal timeout (10s), wrapper timeout is 30s
                result = await self._call_tool_with_retry(
                    run_code,
                    language="python",
                    code=query,
                    max_retries=1,
                    timeout=30,  # Wrapper timeout
                    tool_name="run_code",
                )
                return json.dumps(result, ensure_ascii=False)

            # Default fallback to RAG hybrid
            kb_name = self.config.get("rag", {}).get("kb_name", "ai_textbook")
            res = await self._call_tool_with_retry(
                rag_search,
                query=query,
                kb_name=kb_name,
                mode="hybrid",
                max_retries=max_retries,
                timeout=default_timeout,
                tool_name="rag_search(hybrid)",
            )
            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            return json.dumps(
                {"status": "failed", "error": str(e), "tool": tool_type, "query": query},
                ensure_ascii=False,
            )

    async def run(self, topic: str) -> dict[str, Any]:
        """
        Execute complete research workflow

        Args:
            topic: Research topic

        Returns:
            Research result
        """
        if self.logger:
            self.logger.section("DR-in-KG 2.0 - Deep Research System Based on Dynamic Topic Queue")
            self.logger.info(f"Research Topic: {topic}")
            self.logger.info(f"Research ID: {self.research_id}")
        self.input_topic = topic

        try:
            # ========== Phase 1: Planning (Planning and Initialization) ==========
            self.logger.info("\n" + "═" * 70)
            self.logger.info("▶ Phase 1: Planning - Planning and Initialization")
            self.logger.info("═" * 70)

            optimized_topic = await self._phase1_planning(topic)

            # ========== Phase 2: Researching (Dynamic Research Loop) ==========
            self.logger.info("\n" + "═" * 70)
            self.logger.info("▶ Phase 2: Researching - Dynamic Research Loop")
            self.logger.info("═" * 70)

            await self._phase2_researching()

            # ========== Phase 3: Reporting (Report Generation) ==========
            self.logger.info("\n" + "═" * 70)
            self.logger.info("▶ Phase 3: Reporting - Report Generation")
            self.logger.info("═" * 70)

            report_result = await self._phase3_reporting(optimized_topic)

            # ========== Save Results ==========
            self.logger.info("\n" + "═" * 70)
            self.logger.info("▶ Save Results")
            self.logger.info("═" * 70 + "\n")

            report_file = self.reports_dir / f"{self.research_id}.md"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report_result["report"])
            self.logger.success(f"Final Report: {report_file}")

            # Save queue
            queue_file = self.cache_dir / "queue.json"
            self.queue.save_to_json(str(queue_file))
            self.logger.success(f"Queue Data: {queue_file}")

            # Save outline (if exists)
            if "outline" in report_result:
                outline_file = self.cache_dir / "outline.json"
                with open(outline_file, "w", encoding="utf-8") as f:
                    json.dump(report_result["outline"], f, ensure_ascii=False, indent=2)
                self.logger.success(f"Report Outline: {outline_file}")

            # Extract sources
            sources = report_result.get("sources", {"web": [], "rag": []})

            # Save metadata
            metadata = {
                "research_id": self.research_id,
                "topic": topic,
                "optimized_topic": optimized_topic,
                "statistics": self.queue.get_statistics(),
                "report_word_count": report_result["word_count"],
                "web_sources": sources.get("web", []),  # Flatten for frontend
                "rag_sources": sources.get("rag", []),  # Flatten for frontend
                "source_catalog": report_result.get("source_catalog", []),
                "completed_at": datetime.now().isoformat(),
            }

            metadata_file = self.reports_dir / f"{self.research_id}_metadata.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            self.logger.success(f"Metadata: {metadata_file}")

            # ===== Token Cost Statistics =====
            try:
                from src.agents.research.utils.token_tracker import get_token_tracker

                tracker = get_token_tracker()
                cost_summary = tracker.format_summary()
                self.logger.info(cost_summary)
                cost_file = self.cache_dir / "token_cost_summary.json"
                tracker.save(str(cost_file))
                self.logger.success(f"Cost statistics saved: {cost_file}")
            except Exception as _e:
                self.logger.warning(f"Cost statistics failed: {_e}")

            self.logger.info("\n" + "=" * 70)
            self.logger.success("Research Completed!")
            self.logger.info("=" * 70)
            self.logger.info(f"Research ID: {self.research_id}")
            self.logger.info(f"Topic: {topic}")
            self.logger.info(f"Final Report: {report_file}")
            self.logger.info(f"Report Word Count: {report_result['word_count']}")
            self.logger.info(f"Topic Blocks: {len(self.queue.blocks)}")
            self.logger.info("=" * 70 + "\n")

            return {
                "research_id": self.research_id,
                "topic": topic,
                "final_report_path": str(report_file),
                "metadata": metadata,
            }

        except KeyboardInterrupt:
            self.logger.warning("\n\n⚠️  Research interrupted by user")
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"\n\n✗ Research failed: {e!s}")
            import traceback

            self.logger.error(traceback.format_exc())
            raise

    async def _phase1_planning(self, topic: str) -> str:
        """
        Phase 1: Planning and Initialization

        Args:
            topic: User input topic

        Returns:
            Optimized topic
        """
        self._log_progress("planning", "planning_started", user_topic=topic)

        # Check if topic rephrasing is enabled
        rephrase_config = self.config.get("planning", {}).get("rephrase", {})
        rephrase_enabled = rephrase_config.get("enabled", True)

        if rephrase_enabled:
            self.logger.info("\n【Step 1】Topic Rephrasing...")

            # Use RephraseAgent to optimize topic (supports user interaction)
            max_iterations = rephrase_config.get("max_iterations", 3)

            rephrase_result = None
            iteration = 0
            user_feedback = None  # Initialize user feedback variable

            # Check if running in frontend mode (has progress_callback)
            # In frontend mode, skip interactive input loop - user controls via frontend UI
            is_frontend_mode = self.progress_callback is not None

            while iteration < max_iterations:
                # Execute rephrasing
                if iteration == 0:
                    rephrase_result = await self.agents["rephrase"].process(
                        topic, iteration=iteration
                    )
                # Continue rephrasing based on user feedback
                elif user_feedback:
                    rephrase_result = await self.agents["rephrase"].process(
                        user_feedback, iteration=iteration, previous_result=rephrase_result
                    )
                else:
                    # If no feedback, use previous result
                    break

                iteration += 1

                # In frontend mode, only do one iteration and exit
                # User will control further iterations via frontend UI (/optimize_topic API)
                if is_frontend_mode:
                    self.logger.info(f"\n{'=' * 70}")
                    self.logger.info("📋 Rephrase Result (Frontend Mode):")
                    self.logger.info(f"{'=' * 70}")
                    self.logger.info(
                        f"Optimized Research Topic: {rephrase_result.get('topic', '')}"
                    )
                    self.logger.info(f"{'=' * 70}")
                    self.logger.success(
                        "Frontend mode: Using current result, proceeding to next stage"
                    )
                    break

                # CLI mode: Ask user opinion (unless max iterations reached)
                if iteration < max_iterations:
                    self.logger.info(f"\n{'=' * 70}")
                    self.logger.info("📋 Current Rephrasing Result:")
                    self.logger.info(f"{'=' * 70}")
                    self.logger.info(
                        f"Optimized Research Topic: {rephrase_result.get('topic', '')}"
                    )
                    self.logger.info(f"{'=' * 70}")
                    self.logger.info("\n💬 Are you satisfied with this rephrasing result?")
                    self.logger.info(
                        "   - Enter 'satisfied', 'ok', etc. to indicate satisfaction, will proceed to next stage"
                    )
                    self.logger.info(
                        "   - Enter specific modification suggestions, will continue optimizing based on your feedback"
                    )
                    self.logger.info("   - Press Enter directly to use current result")

                    user_input = input("\nYour choice: ").strip()

                    if not user_input:
                        self.logger.success("Using current result, proceeding to next stage")
                        break

                    # Determine user intent
                    satisfaction = await self.agents["rephrase"].check_user_satisfaction(
                        rephrase_result, user_input
                    )

                    if satisfaction.get("user_satisfied", False):
                        self.logger.success("User satisfied, proceeding to next stage")
                        break

                    if not satisfaction.get("should_continue", True):
                        self.logger.success("Proceeding to next stage")
                        break

                    # Continue iteration, use user input as feedback
                    user_feedback = user_input

            # Ensure there is a result
            if rephrase_result is None:
                rephrase_result = {"topic": topic}

            optimized_topic = rephrase_result.get("topic", topic)
            self._log_progress(
                "planning",
                "rephrase_completed",
                optimized_topic=optimized_topic,
                iterations=iteration,
            )
        else:
            self.logger.info("\n【Step 1】Topic Rephrasing (disabled, skipping)...")
            optimized_topic = topic
            self._log_progress(
                "planning",
                "rephrase_skipped",
                optimized_topic=optimized_topic,
                reason="rephrase feature disabled",
            )

        self.optimized_topic = optimized_topic

        self.logger.info("\n【Step 2】Topic Decomposition...")

        # Use DecomposeAgent to decompose topic
        decompose_config = self.config.get("planning", {}).get("decompose", {})
        mode = decompose_config.get("mode", "manual")

        if mode == "auto":
            # Auto mode: use auto_max_subtopics as limit
            num_subtopics = decompose_config.get(
                "auto_max_subtopics", decompose_config.get("initial_subtopics", 5)
            )
            self.logger.info(f"📌 Using Auto mode, max subtopics: {num_subtopics}")
        else:
            # Manual mode: use initial_subtopics
            num_subtopics = decompose_config.get("initial_subtopics", 5)
            self.logger.info(f"📌 Using Manual mode, expected subtopics: {num_subtopics}")

        self._log_progress(
            "planning", "decompose_started", requested_subtopics=num_subtopics, mode=mode
        )

        # Set citation manager to DecomposeAgent
        self.agents["decompose"].set_citation_manager(self.citation_manager)

        decompose_result = await self.agents["decompose"].process(
            topic=optimized_topic, num_subtopics=num_subtopics, mode=mode
        )
        self._log_progress(
            "planning",
            "decompose_completed",
            generated_subtopics=decompose_result.get("total_subtopics", 0),
            rag_context_length=len(decompose_result.get("rag_context", "") or ""),
        )

        # Save Planning stage results (includes sub_queries / rag_context / sub_topics)
        try:
            step1_path = self.cache_dir / "step1_planning.json"
            with open(step1_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "main_topic": optimized_topic,
                        "sub_queries": decompose_result.get("sub_queries", []),
                        "rag_context": decompose_result.get("rag_context", ""),
                        "sub_topics": decompose_result.get("sub_topics", []),
                        "total_subtopics": decompose_result.get("total_subtopics", 0),
                        "timestamp": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            self.logger.success(f"Planning stage data saved: {step1_path}")
        except Exception as _e:
            self.logger.warning(f"Failed to save Planning stage data: {_e}")

        # Add subtopics to queue
        self.logger.info("\n【Step 3】Initializing Queue...")
        for sub_topic_data in decompose_result.get("sub_topics", []):
            title = coerce_text(sub_topic_data.get("title")).strip()
            overview = coerce_text(sub_topic_data.get("overview"))
            if not title:
                continue
            try:
                block = self.queue.add_block(sub_topic=title, overview=overview)
                self._log_progress(
                    "planning",
                    "queue_seeded",
                    block_id=block.block_id,
                    sub_topic=block.sub_topic,
                    total_blocks=len(self.queue.blocks),
                )
            except RuntimeError as err:
                self._log_progress(
                    "planning", "queue_capacity_reached", error=str(err), attempted_topic=title
                )
                self.logger.warning(
                    f"Queue reached capacity limit, stopping addition of initial topics: {err}"
                )
                break

        stats = self.queue.get_statistics()
        self._log_progress("planning", "planning_completed", total_blocks=stats["total_blocks"])
        self.logger.success("\nPhase 1 Completed:")
        self.logger.info(f"  - Optimized Topic: {optimized_topic}")
        self.logger.info(f"  - Subtopic Count: {stats['total_blocks']}")
        self.agents["manager"].set_primary_topic(optimized_topic)

        return optimized_topic

    async def _phase2_researching(self):
        """
        Phase 2: Dynamic Research Loop
        Routes to series or parallel execution based on configuration
        """
        execution_mode = self.config.get("researching", {}).get("execution_mode", "series")

        if execution_mode == "parallel":
            await self._phase2_researching_parallel()
        else:
            await self._phase2_researching_series()

    async def _phase2_researching_series(self):
        """
        Phase 2: Dynamic Research Loop (Series Mode - Original Implementation)
        """
        # Initialize researching stage event list
        if "researching" not in self._stage_events:
            self._stage_events["researching"] = []

        manager = self.agents["manager"]
        research = self.agents["research"]

        total_blocks = len(self.queue.blocks)
        completed_blocks = 0

        self._log_researching_progress(
            "researching_started", total_blocks=total_blocks, execution_mode="series"
        )

        while not manager.is_research_complete():
            # Get next task to research
            block = manager.get_next_task()
            if not block:
                break

            self._log_researching_progress(
                "block_started",
                block_id=block.block_id,
                sub_topic=block.sub_topic,
                current_block=completed_blocks + 1,
                total_blocks=total_blocks,
            )

            # Create iteration progress callback for this block
            iteration_callback = self._create_iteration_progress_callback(
                block_id=block.block_id,
                sub_topic=block.sub_topic,
                execution_mode="series",
                current_block=completed_blocks + 1,
                total_blocks=total_blocks,
            )

            # Execute research loop (unified handling by ResearchAgent.process)
            result = await research.process(
                topic_block=block,
                call_tool_callback=self._call_tool,
                note_agent=self.agents["note"],
                citation_manager=self.citation_manager,
                queue=self.queue,
                manager_agent=manager,
                config=self.config,
                progress_callback=iteration_callback,
            )

            # Mark as completed
            manager.complete_task(block.block_id)
            completed_blocks += 1

            # Update total_blocks in case new topics were added
            total_blocks = len(self.queue.blocks)

            self._log_researching_progress(
                "block_completed",
                block_id=block.block_id,
                sub_topic=block.sub_topic,
                iterations=result.get("iterations", 0),
                tools_used=result.get("tools_used", []),
                queries_used=result.get("queries_used", []),
                current_block=completed_blocks,
                total_blocks=total_blocks,
            )

            # Display statistics
            manager.get_queue_status()

        stats = self.queue.get_statistics()
        self._log_researching_progress(
            "researching_completed",
            completed_blocks=stats["completed"],
            total_tool_calls=stats["total_tool_calls"],
        )

        self.logger.success("\nPhase 2 Completed:")
        self.logger.info(f"  - Completed Topics: {stats['completed']}")
        self.logger.info(f"  - Total Tool Calls: {stats['total_tool_calls']}")

    async def _phase2_researching_parallel(self):
        """
        Phase 2: Dynamic Research Loop (Parallel Mode)
        Executes multiple topic blocks in parallel with concurrency limit
        """
        # Initialize researching stage event list
        if "researching" not in self._stage_events:
            self._stage_events["researching"] = []

        manager = self.agents["manager"]
        research = self.agents["research"]

        # Get configuration
        max_parallel = self.config.get("researching", {}).get("max_parallel_topics", 5)
        semaphore = asyncio.Semaphore(max_parallel)

        # Get all pending blocks at the start
        from src.agents.research.data_structures import TopicStatus

        pending_blocks = [b for b in self.queue.blocks if b.status == TopicStatus.PENDING]
        total_blocks = len(self.queue.blocks)

        self.logger.info(
            f"\n🚀 Starting parallel research mode (max {max_parallel} concurrent topics)"
        )
        self._log_researching_progress(
            "researching_started",
            total_blocks=total_blocks,
            execution_mode="parallel",
            max_parallel=max_parallel,
            initial_pending=len(pending_blocks),
        )

        # Track completed blocks
        completed_count = {"value": 0}  # Use dict to allow modification in nested function

        # Create async wrappers for thread-safe operations in parallel mode
        class AsyncCitationManagerWrapper:
            """Wrapper to use async citation manager methods in parallel mode"""

            def __init__(self, cm):
                self._cm = cm

            async def add_citation(self, citation_id, tool_type, tool_trace, raw_answer):
                return await self._cm.add_citation_async(
                    citation_id, tool_type, tool_trace, raw_answer
                )

            def __getattr__(self, name):
                # Forward other attributes to original citation_manager
                return getattr(self._cm, name)

        class AsyncManagerAgentWrapper:
            """Wrapper to use async manager agent methods in parallel mode"""

            def __init__(self, ma):
                self._ma = ma

            async def add_new_topic(self, sub_topic, overview):
                return await self._ma.add_new_topic_async(sub_topic, overview)

            def __getattr__(self, name):
                # Forward other attributes to original manager_agent
                return getattr(self._ma, name)

        async_citation_manager = AsyncCitationManagerWrapper(self.citation_manager)
        async_manager_agent = AsyncManagerAgentWrapper(manager)

        # Track active tasks for parallel progress display
        active_tasks: dict[str, dict[str, Any]] = {}  # block_id -> task info
        active_tasks_lock = asyncio.Lock()

        async def update_active_task(block_id: str, info: dict[str, Any] | None):
            """Update active task info (thread-safe)"""
            async with active_tasks_lock:
                if info is None:
                    active_tasks.pop(block_id, None)
                else:
                    active_tasks[block_id] = info
                # Send parallel status update
                self._log_researching_progress(
                    "parallel_status_update",
                    active_tasks=list(active_tasks.values()),
                    active_count=len(active_tasks),
                    completed_count=completed_count["value"],
                    total_blocks=total_blocks,
                )

        async def research_single_block(block: Any) -> dict[str, Any] | None:
            """
            Research a single topic block with semaphore control

            Args:
                block: TopicBlock to research

            Returns:
                Research result or None if failed
            """
            async with semaphore:
                try:
                    # Mark as researching (thread-safe)
                    async with manager._lock:
                        # Refresh block status from queue
                        current_block = self.queue.get_block_by_id(block.block_id)
                        if current_block and current_block.status == TopicStatus.PENDING:
                            self.queue.mark_researching(block.block_id)

                    # Add to active tasks
                    await update_active_task(
                        block.block_id,
                        {
                            "block_id": block.block_id,
                            "sub_topic": block.sub_topic,
                            "status": "starting",
                            "iteration": 0,
                            "current_tool": None,
                            "current_query": None,
                        },
                    )

                    self._log_researching_progress(
                        "block_started",
                        block_id=block.block_id,
                        sub_topic=block.sub_topic,
                        execution_mode="parallel",
                        active_count=len(active_tasks),
                    )

                    if self.logger:
                        self.logger.info(
                            f"\n[{block.block_id}] 🔍 Starting research: {block.sub_topic}"
                        )

                    # Get max_iterations from config for this closure
                    config_max_iterations = self.config.get("researching", {}).get(
                        "max_iterations", 5
                    )

                    # Create iteration callback for parallel mode
                    def parallel_iteration_callback(event_type: str, **data):
                        """Handle iteration progress in parallel mode"""
                        # Update active task info
                        task_info = {
                            "block_id": block.block_id,
                            "sub_topic": block.sub_topic,
                            "status": event_type,
                            "iteration": data.get("iteration", 0),
                            "max_iterations": data.get("max_iterations", config_max_iterations),
                            "current_tool": data.get("tool_type"),
                            "current_query": data.get("query"),
                            "tools_used": data.get("tools_used", []),
                        }
                        # Schedule async update
                        asyncio.create_task(update_active_task(block.block_id, task_info))

                        # Also log the detailed progress
                        self._log_researching_progress(
                            event_type,
                            block_id=block.block_id,
                            sub_topic=block.sub_topic,
                            execution_mode="parallel",
                            **data,
                        )

                    # Execute research loop with async wrappers
                    result = await research.process(
                        topic_block=block,
                        call_tool_callback=self._call_tool,
                        note_agent=self.agents["note"],
                        citation_manager=async_citation_manager,
                        queue=self.queue,
                        manager_agent=async_manager_agent,
                        config=self.config,
                        progress_callback=parallel_iteration_callback,
                    )

                    # Mark as completed (thread-safe)
                    await manager.complete_task_async(block.block_id)
                    completed_count["value"] += 1

                    # Remove from active tasks
                    await update_active_task(block.block_id, None)

                    self._log_researching_progress(
                        "block_completed",
                        block_id=block.block_id,
                        sub_topic=block.sub_topic,
                        iterations=result.get("iterations", 0),
                        tools_used=result.get("tools_used", []),
                        queries_used=result.get("queries_used", []),
                        current_block=completed_count["value"],
                        total_blocks=total_blocks,
                        execution_mode="parallel",
                    )

                    if self.logger:
                        self.logger.success(f"[{block.block_id}] ✓ Completed: {block.sub_topic}")

                    return result

                except Exception as e:
                    # Mark as failed (thread-safe)
                    await manager.fail_task_async(block.block_id, str(e))
                    completed_count["value"] += 1

                    # Remove from active tasks
                    await update_active_task(block.block_id, None)

                    if self.logger:
                        self.logger.error(f"[{block.block_id}] ✗ Failed: {block.sub_topic} - {e}")

                    self._log_researching_progress(
                        "block_failed",
                        block_id=block.block_id,
                        sub_topic=block.sub_topic,
                        error=str(e),
                        execution_mode="parallel",
                    )
                    return None

        # Execute all research tasks in parallel
        tasks = [research_single_block(block) for block in pending_blocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that weren't caught
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                block = pending_blocks[i]
                await manager.fail_task_async(block.block_id, str(result))
                if self.logger:
                    self.logger.error(f"[{block.block_id}] ✗ Exception: {result}")

        # Wait for any dynamically added topics (if manager adds new topics during research)
        # Continue until all tasks are processed (completed or failed)
        max_wait_iterations = 100  # Prevent infinite loop
        wait_count = 0

        while True:
            # Check if all blocks are processed (COMPLETED or FAILED, not PENDING or RESEARCHING)
            stats = self.queue.get_statistics()
            pending_count = stats.get("pending", 0)
            researching_count = stats.get("researching", 0)

            # Exit if no pending or researching tasks
            if pending_count == 0 and researching_count == 0:
                break

            # Get any newly added pending blocks
            new_pending = [b for b in self.queue.blocks if b.status == TopicStatus.PENDING]
            if not new_pending:
                # No pending blocks, but there might be researching ones
                # Wait a bit for them to complete
                wait_count += 1
                if wait_count > max_wait_iterations:
                    self.logger.warning(
                        "Max wait iterations reached, exiting parallel research loop"
                    )
                    break
                await asyncio.sleep(0.1)
                continue

            # Reset wait count when we have new work
            wait_count = 0

            # Research newly added blocks
            new_tasks = [research_single_block(block) for block in new_pending]
            new_results = await asyncio.gather(*new_tasks, return_exceptions=True)

            for i, result in enumerate(new_results):
                if isinstance(result, Exception):
                    block = new_pending[i]
                    await manager.fail_task_async(block.block_id, str(result))

        stats = self.queue.get_statistics()
        self._log_researching_progress(
            "researching_completed",
            completed_blocks=stats["completed"],
            total_tool_calls=stats["total_tool_calls"],
            execution_mode="parallel",
        )

        self.logger.success("\nPhase 2 Completed (Parallel Mode):")
        self.logger.info(f"  - Completed Topics: {stats['completed']}")
        self.logger.info(f"  - Total Tool Calls: {stats['total_tool_calls']}")
        self.logger.info(f"  - Failed Topics: {stats.get('failed', 0)}")

    def _log_researching_progress(self, status: str, **payload: Any) -> None:
        """Record researching stage progress (thread-safe for parallel mode)"""
        event = {"status": status, "timestamp": datetime.now().isoformat()}
        event.update({k: v for k, v in payload.items() if v is not None})

        # Use lock to prevent concurrent file writes in parallel mode
        with self._progress_file_lock:
            if "researching" not in self._stage_events:
                self._stage_events["researching"] = []
            self._stage_events["researching"].append(event)

            # Save to file
            research_progress_file = self.cache_dir / "researching_progress.json"
            context = {
                "research_id": self.research_id,
                "stage": "researching",
                "input_topic": self.input_topic,
                "optimized_topic": self.optimized_topic,
                "events": self._stage_events["researching"],
            }
            with open(research_progress_file, "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)

        # Send progress via callback
        if self.progress_callback:
            try:
                progress_event = {
                    "type": "progress",
                    "stage": "researching",
                    "status": status,
                    "research_id": self.research_id,
                    **{k: v for k, v in payload.items() if v is not None},
                }
                self.progress_callback(progress_event)
            except Exception as e:
                self.logger.warning(f"Progress callback failed: {e}")

    def _create_iteration_progress_callback(
        self,
        block_id: str,
        sub_topic: str,
        execution_mode: str,
        current_block: int = None,
        total_blocks: int = None,
    ) -> Callable:
        """
        Create a progress callback for research iterations

        Args:
            block_id: Block ID for the current topic
            sub_topic: Current sub-topic being researched
            execution_mode: 'series' or 'parallel'
            current_block: Current block number (for series mode)
            total_blocks: Total number of blocks

        Returns:
            Callback function for iteration progress
        """

        def iteration_callback(event_type: str, **data: Any):
            """Callback for iteration progress events"""
            payload = {
                "block_id": block_id,
                "sub_topic": sub_topic,
                "execution_mode": execution_mode,
            }
            if current_block is not None:
                payload["current_block"] = current_block
            if total_blocks is not None:
                payload["total_blocks"] = total_blocks
            payload.update(data)

            self._log_researching_progress(event_type, **payload)

        return iteration_callback

    async def _phase3_reporting(self, topic: str) -> dict[str, Any]:
        """
        Phase 3: Report Generation

        Args:
            topic: Research topic

        Returns:
            Report result
        """
        reporting = self.agents["reporting"]

        # Set citation manager
        reporting.set_citation_manager(self.citation_manager)

        # Generate report
        report_result = await reporting.process(
            self.queue, topic, progress_callback=self._report_progress_callback
        )

        self.logger.success("\nPhase 3 Completed:")
        self.logger.info(f"  - Report Word Count: {report_result['word_count']}")
        self.logger.info(f"  - Sections: {report_result['sections']}")
        self.logger.info(f"  - Citations: {report_result['citations']}")

        return report_result

    def _log_progress(self, stage: str, status: str, **payload: Any) -> None:
        """Record stage progress to JSON file and send progress via callback"""
        if stage not in self._stage_events:
            return
        event = {"status": status, "timestamp": datetime.now().isoformat()}
        event.update({k: v for k, v in payload.items() if v is not None})
        self._stage_events[stage].append(event)
        file_path = self.plan_progress_file if stage == "planning" else self.report_progress_file
        context = {
            "research_id": self.research_id,
            "stage": stage,
            "input_topic": self.input_topic,
            "optimized_topic": self.optimized_topic,
            "events": self._stage_events[stage],
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(context, f, ensure_ascii=False, indent=2)

        # Send progress via callback (if callback function is set)
        if self.progress_callback:
            try:
                progress_event = {
                    "type": "progress",
                    "stage": stage,
                    "status": status,
                    "research_id": self.research_id,
                    **{k: v for k, v in payload.items() if v is not None},
                }
                self.progress_callback(progress_event)
            except Exception as e:
                self.logger.warning(f"Progress callback failed: {e}")

    def _report_progress_callback(self, event: dict[str, Any]) -> None:
        """Reporting stage progress callback"""
        status = event.pop("status", "unknown")
        self._log_progress("reporting", status, **event)


async def main():
    """Main function"""
    import argparse

    from dotenv import load_dotenv
    import yaml

    from src.services.llm import get_llm_config

    # Load environment variables
    load_dotenv()

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="DR-in-KG 2.0 - Deep Research System")
    parser.add_argument("--topic", type=str, required=True, help="Research topic")
    parser.add_argument("--config", type=str, default="config.yaml", help="Configuration file")
    parser.add_argument(
        "--preset", type=str, choices=["quick", "medium", "deep", "auto"], help="Preset mode"
    )

    args = parser.parse_args()

    # Load configuration
    config_path = PROJECT_ROOT / args.config
    if not config_path.exists():
        logger = get_logger("Research")
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Apply preset
    if args.preset and "presets" in config and args.preset in config["presets"]:
        preset = config["presets"][args.preset]
        # Merge preset configuration
        for key, value in preset.items():
            if key in config and isinstance(value, dict):
                config[key].update(value)

    # Get LLM configuration
    llm_config = get_llm_config()

    # Create research pipeline
    pipeline = ResearchPipeline(
        config=config, api_key=llm_config.api_key, base_url=llm_config.base_url
    )

    # Execute research
    result = await pipeline.run(args.topic)

    logger = get_logger("Research")
    logger.success("\n🎉 Research completed!")
    logger.info(f"Report location: {result['final_report_path']}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())


# Backward compatibility alias: old code can use ResearchPipeline, new code referencing ResearchPipeline2 won't error
ResearchPipeline2 = ResearchPipeline
__all__ = ["ResearchPipeline", "ResearchPipeline2"]
