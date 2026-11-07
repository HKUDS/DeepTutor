"""
MainSolver — Plan -> ReAct -> Write pipeline controller.

External interface (preserved for API compatibility):
    solver = MainSolver(kb_name=..., ...)
    await solver.ainit()
    result = await solver.solve(question)
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ...services.config import parse_language
from ...services.path_service import get_path_service
from .agents import PlannerAgent, SolverAgent, WriterAgent
from .memory import Scratchpad, Source
from .tools import ToolRegistry
from .utils.display_manager import get_display_manager
from .utils.token_tracker import TokenTracker


class MainSolver:
    """Problem-Solving System Controller — Plan -> ReAct -> Write."""

    def __init__(
        self,
        config_path: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        model: str | None = None,
        language: str | None = None,
        kb_name: str = "ai-textbook",
        output_base_dir: str | None = None,
        tool_registry: ToolRegistry | None = None,
        disable_memory: bool = False,
        disable_planner_retrieve: bool = False,
        rag_mode: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        # Store init params for ainit()
        self._config_path = config_path
        self._api_key = api_key
        self._base_url = base_url
        self._api_version = api_version
        self._model = model
        self._language = language
        self._kb_name = kb_name
        self._output_base_dir = output_base_dir
        self._external_tool_registry = tool_registry
        self.disable_memory = disable_memory
        self.disable_planner_retrieve = disable_planner_retrieve
        self._rag_mode_override = rag_mode
        self._max_tokens_override = max_tokens
        self._temperature_override = temperature

        # Will be set in ainit()
        self.config: dict[str, Any] = {}
        self.api_key: str | None = None
        self.base_url: str | None = None
        self.api_version: str | None = None
        self.kb_name = kb_name
        self.logger: Any = None
        self.token_tracker: TokenTracker | None = None

        # Agents (set in ainit)
        self.planner_agent: PlannerAgent | None = None
        self.solver_agent: SolverAgent | None = None
        self.writer_agent: WriterAgent | None = None

    # ------------------------------------------------------------------
    # Async initialisation
    # ------------------------------------------------------------------

    async def ainit(self) -> None:
        """Complete async initialisation: config, logger, agents."""
        await self._load_config()
        self._init_logging()
        self._init_agents()
        self.logger.success("Solver ready (Plan -> ReAct -> Write)")

    async def _load_config(self) -> None:
        """Load configuration from main.yaml or custom path."""
        config_path = self._config_path
        language = self._language
        output_base_dir = self._output_base_dir

        if config_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            from ...services.config.loader import load_config_with_main_async

            full_config = await load_config_with_main_async("main.yaml", project_root)
            solve_config = full_config.get("solve", {})
            paths_config = full_config.get("paths", {})
            path_service = get_path_service()
            default_solve_dir = str(path_service.get_solve_dir())

            self.config = {
                "system": {
                    "output_base_dir": paths_config.get("solve_output_dir", default_solve_dir),
                    "save_intermediate_results": solve_config.get("save_intermediate_results", True),
                    "language": full_config.get("system", {}).get("language", "en"),
                },
                "logging": full_config.get("logging", {}),
                "tools": full_config.get("tools", {}),
                "paths": paths_config,
                "solve": solve_config,
            }
        else:
            local_config: dict[str, Any] = {}
            if Path(config_path).exists():
                try:
                    def _load(p: str) -> dict:
                        with open(p, encoding="utf-8") as f:
                            return yaml.safe_load(f) or {}
                    local_config = await asyncio.to_thread(_load, config_path)
                except Exception:
                    pass
            self.config = local_config if isinstance(local_config, dict) else {}

        if not isinstance(self.config, dict):
            self.config = {}

        # Override language from UI
        if language:
            self.config.setdefault("system", {})
            self.config["system"]["language"] = parse_language(language)

        # Override output dir
        if output_base_dir:
            self.config.setdefault("system", {})
            self.config["system"]["output_base_dir"] = str(output_base_dir)

        # Load LLM credentials
        api_key = self._api_key
        base_url = self._base_url
        api_version = self._api_version

        if api_key is None or base_url is None:
            try:
                from ...services.llm.config import get_llm_config_async

                llm_config = await get_llm_config_async()
                api_key = api_key or llm_config.api_key
                base_url = base_url or llm_config.base_url
                api_version = api_version or getattr(llm_config, "api_version", None)
            except ValueError as exc:
                raise ValueError(f"LLM config error: {exc}") from exc

        from src.services.llm import is_local_llm_server

        if not api_key and not is_local_llm_server(base_url):
            raise ValueError("API key not set. Provide api_key or set LLM_API_KEY in .env")
        if not api_key and is_local_llm_server(base_url):
            api_key = "sk-no-key-required"

        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.kb_name = self._kb_name

    def _init_logging(self) -> None:
        """Initialise logger, display manager, and token tracker."""
        from src.logging import Logger

        logging_config = self.config.get("logging", {})
        log_dir = (
            self.config.get("paths", {}).get("user_log_dir")
            or logging_config.get("log_dir")
        )

        self.logger = Logger(
            name="Solver",
            level=logging_config.get("level", "INFO"),
            log_dir=log_dir,
            console_output=logging_config.get("console_output", True),
            file_output=logging_config.get("save_to_file", True),
        )
        self.logger.display_manager = get_display_manager()

        self.token_tracker = TokenTracker(prefer_tiktoken=True)
        if self.logger.display_manager:
            self.token_tracker.set_on_usage_added_callback(
                self.logger.display_manager.update_token_stats
            )

        self.logger.section("Solver Initialising (Plan -> ReAct -> Write)")
        self.logger.info(f"Knowledge Base: {self.kb_name}")

    def _init_agents(self) -> None:
        """Create the three agents."""
        lang = parse_language(self.config.get("system", {}).get("language", "en"))
        self.tool_registry = (
            self._external_tool_registry
            or ToolRegistry.create_default(language=lang)
        )
        common = dict(
            config=self.config,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            model=self._model,
            token_tracker=self.token_tracker,
            language=lang,
        )
        self.planner_agent = PlannerAgent(
            **common,
            tool_registry=self.tool_registry,
            enable_pre_retrieve=not self.disable_planner_retrieve,
        )
        self.solver_agent = SolverAgent(**common, tool_registry=self.tool_registry)
        self.writer_agent = WriterAgent(**common)

        # Apply per-run overrides from benchmark config (pipeline.max_tokens / pipeline.temperature)
        if self._max_tokens_override is not None or self._temperature_override is not None:
            for agent in (self.planner_agent, self.solver_agent, self.writer_agent):
                if self._max_tokens_override is not None:
                    agent._agent_params["max_tokens"] = self._max_tokens_override
                if self._temperature_override is not None:
                    agent._agent_params["temperature"] = self._temperature_override

        self.logger.info(
            f"Agents initialised (lang={lang}), tools registered: {self.tool_registry.tool_names}"
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def solve(
        self,
        question: str,
        image_url: str | None = None,
        verbose: bool = True,
        detailed: bool | None = None,
    ) -> dict[str, Any]:
        """Run the full Plan -> ReAct -> Write pipeline.

        Args:
            question: The user question to solve.
            image_url: Optional image URL for multimodal questions.
            verbose: Enable verbose logging.
            detailed: If True, use iterative detailed writing. If None, read from config.

        Returns a dict compatible with the existing API contract.
        """
        # Resolve detailed flag: explicit param > config > default False
        if detailed is None:
            detailed = self.config.get("solve", {}).get("detailed_answer", False)
        self._detailed = detailed

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_service = get_path_service()
        output_base = self.config.get("system", {}).get(
            "output_base_dir", str(path_service.get_solve_dir())
        )
        output_dir = os.path.join(output_base, f"solve_{timestamp}")
        os.makedirs(output_dir, exist_ok=True)

        # Task-level log file
        task_log = os.path.join(output_dir, "task.log")
        self.logger.add_task_log_handler(task_log)

        self.logger.section("Problem Solving Started")
        self.logger.info(f"Question: {question[:100]}{'...' if len(question) > 100 else ''}")
        self.logger.info(f"Output: {output_dir}")

        try:
            result = await self._run_pipeline(question, output_dir, image_url=image_url)
            result["metadata"] = {
                **result.get("metadata", {}),
                "mode": "plan_react_write",
                "timestamp": timestamp,
                "output_dir": output_dir,
            }

            # Cost report
            if self.token_tracker:
                summary = self.token_tracker.get_summary()
                if summary["total_calls"] > 0:
                    self.logger.info(f"\n{self.token_tracker.format_summary()}")
                    cost_file = os.path.join(output_dir, "cost_report.json")
                    self.token_tracker.save(cost_file)
                    self.token_tracker.reset()

            self.logger.success("Problem solving completed")
            self.logger.remove_task_log_handlers()
            return result

        except Exception as exc:
            self.logger.error(f"Solving failed: {exc}")
            self.logger.error(traceback.format_exc())
            self.logger.remove_task_log_handlers()
            raise
        finally:
            if hasattr(self, "logger"):
                self.logger.shutdown()

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        question: str,
        output_dir: str,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        solve_cfg = self.config.get("solve", {})
        max_react = solve_cfg.get("max_react_iterations", 5)
        max_replans = solve_cfg.get("max_replans", 2)

        scratchpad = Scratchpad.load_or_create(output_dir, question)

        # ============================================================
        # Phase 1: PLAN
        # ============================================================
        self.logger.stage("Phase 1", "start", "Planning")
        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("PlannerAgent", "running")
        if hasattr(self, "_send_progress_update"):
            self._send_progress_update("plan", {"status": "planning"})

        memory_ctx = ""
        if not self.disable_memory:
            memory_ctx = await self._get_planner_memory_context(question)

        plan = await self.planner_agent.process(
            question=question,
            scratchpad=scratchpad,
            kb_name=self.kb_name,
            memory_context=memory_ctx,
            image_url=image_url,
        )
        scratchpad.set_plan(plan)
        scratchpad.save(output_dir)

        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("PlannerAgent", "done")
        self.logger.info(f"Plan: {len(plan.steps)} steps — {plan.analysis[:80]}")
        for s in plan.steps:
            self.logger.info(f"  [{s.id}] {s.goal}")
        self.logger.update_token_stats(self.token_tracker.get_summary())

        # ============================================================
        # Phase 2: SOLVE (ReAct loop per step)
        # ============================================================
        self.logger.stage("Phase 2", "start", "Solving")
        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("SolverAgent", "running")
        if hasattr(self, "_send_progress_update"):
            self._send_progress_update("solve", {"status": "starting"})

        replan_count = 0
        safety_limit = (len(plan.steps) + max_replans) * (max_react + 1)
        iterations = 0

        while not scratchpad.is_all_completed():
            iterations += 1
            if iterations > safety_limit:
                self.logger.warning("Safety iteration limit reached")
                break

            step = scratchpad.get_next_pending_step()
            if step is None:
                break

            scratchpad.mark_step_status(step.id, "in_progress")
            self.logger.info(f"  Step {step.id}: {step.goal}")
            step_memory_context = ""
            if not self.disable_memory:
                step_memory_context = await self._get_solver_memory_context(step.goal)

            # Compute step index for progress reporting
            step_index = next(
                (i + 1 for i, s in enumerate(scratchpad.plan.steps) if s.id == step.id),
                0,
            ) if scratchpad.plan else 0
            if hasattr(self, "_send_progress_update"):
                self._send_progress_update("solve", {
                    "step_id": step.id,
                    "step_index": step_index,
                    "step_target": step.goal,
                })

            for round_num in range(max_react):
                decision = await self.solver_agent.process(
                    question=question,
                    current_step=step,
                    scratchpad=scratchpad,
                    memory_context=step_memory_context,
                    image_url=image_url,
                )

                action = decision["action"]
                action_input = decision["action_input"]
                thought = decision["thought"]
                self_note = decision["self_note"]

                self.logger.info(f"    Round {round_num + 1}: {action}({action_input[:60]}...)")
                self.logger.debug(f"    Thought: {thought[:120]}")

                if action == "done":
                    scratchpad.add_entry(
                        step_id=step.id,
                        round_num=round_num,
                        thought=thought,
                        action="done",
                        action_input="",
                        observation="",
                        self_note=self_note,
                    )
                    scratchpad.mark_step_status(step.id, "completed")
                    scratchpad.save(output_dir)
                    self.logger.info(f"    -> Step {step.id} completed")
                    break

                if action == "replan":
                    replan_count += 1
                    self.logger.info(f"    -> Replan requested ({replan_count}/{max_replans}): {action_input[:80]}")
                    # Record the replan entry
                    scratchpad.add_entry(
                        step_id=step.id,
                        round_num=round_num,
                        thought=thought,
                        action="replan",
                        action_input=action_input,
                        observation="",
                        self_note=self_note,
                    )
                    if replan_count <= max_replans:
                        if self.logger.display_manager:
                            self.logger.display_manager.set_agent_status("PlannerAgent", "running")
                        replan_memory = ""
                        if not self.disable_memory:
                            replan_memory = await self._get_planner_memory_context(question)
                        new_plan = await self.planner_agent.process(
                            question=question,
                            scratchpad=scratchpad,
                            kb_name=self.kb_name,
                            replan=True,
                            memory_context=replan_memory,
                            image_url=image_url,
                        )
                        scratchpad.update_plan(new_plan)
                        scratchpad.save(output_dir)
                        if self.logger.display_manager:
                            self.logger.display_manager.set_agent_status("PlannerAgent", "done")
                        self.logger.info(f"    Plan revised: {len(new_plan.steps)} steps")
                    else:
                        self.logger.warning("    Max replans reached — marking step completed")
                        scratchpad.mark_step_status(step.id, "completed")
                        scratchpad.save(output_dir)
                    break

                # Execute tool
                observation, sources = await self._execute_tool(
                    action=action,
                    action_input=action_input,
                    output_dir=output_dir,
                    question=question,
                    scratchpad=scratchpad,
                )

                scratchpad.add_entry(
                    step_id=step.id,
                    round_num=round_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation,
                    self_note=self_note,
                    sources=sources,
                )
                scratchpad.save(output_dir)
                self.logger.update_token_stats(self.token_tracker.get_summary())
            else:
                # Max rounds exhausted for this step
                self.logger.warning(f"    Max ReAct iterations reached for {step.id}")
                scratchpad.mark_step_status(step.id, "completed")
                scratchpad.save(output_dir)

        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("SolverAgent", "done")

        completed = scratchpad.get_completed_steps()
        total = len(scratchpad.plan.steps) if scratchpad.plan else 0
        self.logger.info(f"  Solve phase done: {len(completed)}/{total} steps completed")
        self.logger.update_token_stats(self.token_tracker.get_summary())

        # ============================================================
        # Phase 3: WRITE
        # ============================================================
        detailed = getattr(self, "_detailed", False)
        write_mode = "detailed iterative" if detailed else "simple"
        self.logger.stage("Phase 3", "start", f"Writing answer ({write_mode})")
        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("WriterAgent", "running")
        if hasattr(self, "_send_progress_update"):
            self._send_progress_update("write", {"status": "writing"})

        language = self.config.get("system", {}).get("language", "en")
        lang_code = parse_language(language)

        preference = "" if self.disable_memory else self._get_user_preference()

        if detailed:
            final_answer = await self.writer_agent.process_iterative(
                question=question,
                scratchpad=scratchpad,
                language=lang_code,
                preference=preference,
            )
        else:
            final_answer = await self.writer_agent.process(
                question=question,
                scratchpad=scratchpad,
                language=lang_code,
                preference=preference,
            )

        if self.logger.display_manager:
            self.logger.display_manager.set_agent_status("WriterAgent", "done")

        # Save final answer
        answer_file = Path(output_dir) / "final_answer.md"
        with open(answer_file, "w", encoding="utf-8") as f:
            f.write(final_answer)
        self.logger.success(f"Final answer saved: {answer_file}")
        self.logger.update_token_stats(self.token_tracker.get_summary())

        if not self.disable_memory:
            await self._publish_event(question, final_answer, scratchpad, output_dir)

        return {
            "question": question,
            "output_dir": output_dir,
            "final_answer": final_answer,
            "output_md": str(answer_file),
            "output_json": str(Path(output_dir) / "scratchpad.json"),
            "formatted_solution": final_answer,
            "citations": [s["id"] for s in scratchpad.get_all_sources()],
            "pipeline": "plan_react_write",
            "total_steps": total,
            "completed_steps": len(completed),
            "total_react_entries": len(scratchpad.entries),
            "plan_revisions": scratchpad.metadata.get("plan_revisions", 0),
            "metadata": {
                "total_steps": total,
                "completed_steps": len(completed),
                "plan_revisions": scratchpad.metadata.get("plan_revisions", 0),
            },
        }

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(
        self,
        action: str,
        action_input: str,
        output_dir: str,
        question: str = "",
        scratchpad: Scratchpad | None = None,
    ) -> tuple[str, list[Source]]:
        """Execute a tool and return (observation_text, sources)."""
        obs_max = self.config.get("solve", {}).get("observation_max_tokens", 2000)
        sources: list[Source] = []

        try:
            if action == "rag_search":
                observation, sources = await self._tool_rag(action_input, obs_max)
            elif action == "web_search":
                observation, sources = await self._tool_web(action_input, output_dir, obs_max)
            elif action == "code_execute":
                observation, sources = await self._tool_code(action_input, obs_max, output_dir)
            elif action == "reason":
                observation, sources = await self._tool_reason(
                    action_input, question, scratchpad, obs_max,
                )
            else:
                observation = f"Unknown action: {action}"
        except Exception as exc:
            observation = f"Tool error ({action}): {exc}"
            self.logger.warning(f"    Tool error: {exc}")

        return observation, sources

    async def _tool_rag(
        self, query: str, max_chars: int
    ) -> tuple[str, list[Source]]:
        from src.tools.rag_tool import rag_search

        solve_cfg = self.config.get("solve", {})
        rag_mode = self._rag_mode_override or solve_cfg.get("rag_mode", "hybrid")
        result = await rag_search(
            query=query,
            kb_name=self.kb_name,
            mode=rag_mode,
            top_k=8,
        )
        answer = result.get("answer", "") or result.get("content", "")
        observation = answer[:max_chars * 4] if answer else "(no results)"

        sources: list[Source] = []
        # Extract source from the answer metadata if available
        if answer:
            sources.append(Source(type="rag", file=self.kb_name, chunk_id=query[:50]))

        return observation, sources

    async def _tool_web(
        self, query: str, output_dir: str, max_chars: int
    ) -> tuple[str, list[Source]]:
        from src.tools.web_search import web_search

        result = await asyncio.to_thread(web_search, query=query, output_dir=output_dir)
        answer = result.get("answer", "")
        observation = answer[:max_chars * 4] if answer else "(no results)"

        sources: list[Source] = []
        for cit in result.get("citations", [])[:5]:
            sources.append(Source(
                type="web",
                url=cit.get("url", ""),
                file=cit.get("title", ""),
            ))

        return observation, sources

    async def _tool_code(
        self, intent: str, max_chars: int, output_dir: str | None = None
    ) -> tuple[str, list[Source]]:
        """Generate Python code from intent, then execute it."""
        # Step 1: Generate code from the intent description
        code = await self._generate_code(intent)

        # Step 2: Execute (all outputs go to run_code_workspace automatically)
        from src.tools.code_executor import run_code

        result = await run_code(
            language="python",
            code=code,
            timeout=30,
            workspace_dir=(os.path.join(output_dir, "code_runs") if output_dir else None),
        )

        parts: list[str] = []
        if result.get("stdout"):
            parts.append(f"Output:\n{result['stdout']}")
        if result.get("stderr"):
            parts.append(f"Stderr:\n{result['stderr']}")
        if result.get("artifacts"):
            parts.append(f"Artifacts: {', '.join(result['artifacts'])}")
        if result.get("exit_code", 0) != 0:
            parts.append(f"Exit code: {result['exit_code']}")

        observation = "\n".join(parts)[:max_chars * 4] if parts else "(no output)"
        observation = f"Code:\n```python\n{code}\n```\n\n{observation}"

        sources: list[Source] = []
        for art in result.get("artifact_paths", []):
            sources.append(Source(type="code", file=Path(art).name))

        return observation, sources

    async def _generate_code(self, intent: str) -> str:
        """Use the LLM to generate Python code from a natural-language intent."""
        system = (
            "You are a Python code generator. Given a description of what to compute, "
            "output ONLY valid Python code (no markdown, no explanation). "
            "Use standard libraries (numpy, matplotlib, sympy, scipy) as needed. "
            "Print results to stdout. Save any plots to the current directory."
        )
        response = await self.solver_agent.call_llm(
            user_prompt=intent,
            system_prompt=system,
            stage="codegen",
        )
        # Strip markdown fences if present
        code = response.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]  # Remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        return code

    async def _tool_reason(
        self,
        query: str,
        question: str,
        scratchpad: Scratchpad | None,
        max_chars: int,
    ) -> tuple[str, list[Source]]:
        """Invoke the stateless deep-reasoning tool."""
        from src.tools.reason import reason

        # Build context from scratchpad so the reasoning LLM has background
        context_parts: list[str] = []
        if question:
            context_parts.append(f"Original question: {question}")
        if scratchpad:
            if scratchpad.plan:
                context_parts.append(f"Plan:\n{scratchpad._format_plan()}")
            # Summaries of completed steps
            completed = scratchpad.get_completed_steps()
            if completed:
                notes: list[str] = []
                for step in completed:
                    entries = scratchpad.get_entries_for_step(step.id)
                    step_notes = [e.self_note for e in entries if e.self_note]
                    if step_notes:
                        notes.append(f"[{step.id}] {step.goal}: {' '.join(step_notes)}")
                if notes:
                    context_parts.append("Knowledge from previous steps:\n" + "\n".join(notes))

        context = "\n\n".join(context_parts)

        result = await reason(
            query=query,
            context=context,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.solver_agent.get_model(),
        )

        observation = result.get("answer", "(no reasoning output)")
        return observation[:max_chars * 4], []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_preference(self) -> str:
        """Get personalisation preference (optional)."""
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if reader:
            try:
                return reader.get_writer_context()
            except Exception:
                pass
        return ""

    async def _get_planner_memory_context(self, question: str) -> str:
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if not reader:
            return ""
        try:
            return await reader.get_planner_context(question)
        except Exception:
            return ""

    async def _get_solver_memory_context(self, step_goal: str) -> str:
        from src.personalization.memory_reader import get_memory_reader_instance

        reader = get_memory_reader_instance()
        if not reader:
            return ""
        try:
            return await reader.get_solver_context(step_goal)
        except Exception:
            return ""

    async def _publish_event(
        self,
        question: str,
        answer: str,
        scratchpad: Scratchpad,
        output_dir: str,
    ) -> None:
        """Publish SOLVE_COMPLETE event for personalisation."""
        try:
            from src.core.event_bus import Event, EventType, get_event_bus

            task_id = Path(output_dir).name
            tools_used = list({e.action for e in scratchpad.entries if e.action not in ("done", "replan")})

            event = Event(
                type=EventType.SOLVE_COMPLETE,
                task_id=task_id,
                user_input=question,
                agent_output=answer[:2000],
                tools_used=tools_used,
                success=True,
                metadata={
                    "total_steps": len(scratchpad.plan.steps) if scratchpad.plan else 0,
                    "completed_steps": len(scratchpad.get_completed_steps()),
                    "citations_count": len(scratchpad.get_all_sources()),
                    "output_dir": output_dir,
                },
            )
            await get_event_bus().publish(event)
            self.logger.debug("Published SOLVE_COMPLETE event")
        except Exception as exc:
            self.logger.debug(f"Failed to publish event: {exc}")
