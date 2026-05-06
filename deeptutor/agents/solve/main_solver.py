"""
MainSolver — Plan -> ReAct -> Write pipeline controller.

External interface (preserved for API compatibility):
    solver = MainSolver(kb_name=..., ...)
    await solver.ainit()
    result = await solver.solve(question)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from pathlib import Path
import traceback
from typing import Any

import yaml

from deeptutor.core.trace import derive_trace_metadata, new_call_id

from ...services.config import parse_language
from ...services.path_service import get_path_service
from .agents import CriticAgent, PlannerAgent, SolverAgent, WriterAgent
from .memory import Scratchpad, Source
from .tool_runtime import SolveToolRuntime
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
        kb_name: str | None = None,
        output_base_dir: str | None = None,
        enabled_tools: list[str] | None = None,
        disable_memory: bool = False,
        disable_planner_retrieve: bool = False,
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
        self._enabled_tools = enabled_tools
        self.disable_memory = disable_memory
        self.disable_planner_retrieve = disable_planner_retrieve
        self._max_tokens_override = max_tokens
        self._temperature_override = temperature

        # Will be set in ainit()
        self.config: dict[str, Any] = {}
        self.api_key: str | None = None
        self.base_url: str | None = None
        self.api_version: str | None = None
        self.kb_name = kb_name or ""
        self.logger: logging.Logger = logging.getLogger("deeptutor.Solver")
        self.display_manager = None
        self._task_log_handler: logging.Handler | None = None
        self.token_tracker: TokenTracker | None = None
        self._trace_callback: Any = None
        self._conversation_context: str = ""

        # Agents (set in ainit)
        self.planner_agent: PlannerAgent | None = None
        self.solver_agent: SolverAgent | None = None
        self.writer_agent: WriterAgent | None = None
        self.tool_runtime: SolveToolRuntime | None = None

    # ------------------------------------------------------------------
    # Async initialisation
    # ------------------------------------------------------------------

    async def ainit(self) -> None:
        """Complete async initialisation: config, logger, agents."""
        await self._load_config()
        self._init_logging()
        self._init_agents()
        self.logger.info("Solver ready (Plan -> ReAct -> Write)")

    def set_trace_callback(self, callback) -> None:
        """Register a callback that receives structured LLM trace events."""
        self._trace_callback = callback
        for agent in (self.planner_agent, self.solver_agent, self.writer_agent):
            if agent is not None:
                agent.set_trace_callback(callback)

    async def _emit_trace_event(self, payload: dict[str, Any]) -> None:
        callback = self._trace_callback
        if callback is None:
            return
        try:
            result = callback(payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    async def _load_config(self) -> None:
        """Load configuration from main.yaml or custom path."""
        config_path = self._config_path
        language = self._language
        output_base_dir = self._output_base_dir

        if config_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            from ...services.config.loader import load_config_with_main_async

            full_config = await load_config_with_main_async("main.yaml", project_root)
            solve_config = full_config.get("capabilities", {}).get("solve", {})
            paths_config = full_config.get("paths", {})
            path_service = get_path_service()
            default_solve_dir = str(path_service.get_solve_dir())

            self.config = {
                "system": {
                    "output_base_dir": paths_config.get("solve_output_dir", default_solve_dir),
                    "save_intermediate_results": solve_config.get(
                        "save_intermediate_results", True
                    ),
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

        from deeptutor.services.llm import is_local_llm_server

        if not api_key and not is_local_llm_server(base_url):
            raise ValueError("API key not set. Provide api_key or set LLM_API_KEY in .env")
        if not api_key and is_local_llm_server(base_url):
            api_key = "sk-no-key-required"

        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.kb_name = self._kb_name or ""

    def _init_logging(self) -> None:
        """Initialise logger, display manager, and token tracker."""
        self.logger = logging.getLogger("deeptutor.Solver")
        self.display_manager = get_display_manager()

        self.token_tracker = TokenTracker(prefer_tiktoken=True)
        if self.display_manager:
            self.token_tracker.set_on_usage_added_callback(self.display_manager.update_token_stats)

        self._log_section("Solver Initialising (Plan -> ReAct -> Write)")
        self.logger.info(f"Knowledge Base: {self.kb_name}")

    def _log_section(self, title: str) -> None:
        self.logger.info("=" * 60)
        self.logger.info(title)
        self.logger.info("=" * 60)

    def _log_stage(self, stage_name: str, status: str = "start", detail: str | None = None) -> None:
        suffix = f" | {detail}" if detail else ""
        self.logger.info("%s %s%s", stage_name, status, suffix, extra={"stage": stage_name})

    def _add_task_log_handler(self, task_log: str) -> None:
        self._remove_task_log_handler()
        path = Path(task_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
        )
        self.logger.addHandler(handler)
        self._task_log_handler = handler

    def _remove_task_log_handler(self) -> None:
        if self._task_log_handler is None:
            return
        self.logger.removeHandler(self._task_log_handler)
        self._task_log_handler.close()
        self._task_log_handler = None

    def _update_token_stats(self, summary: dict[str, Any]) -> None:
        if self.display_manager and summary:
            self.display_manager.update_token_stats(summary)

    def _init_agents(self) -> None:
        """Create the three agents."""
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        lang = parse_language(self.config.get("system", {}).get("language", "en"))
        self._core_tool_registry = get_tool_registry()
        self.tool_runtime = SolveToolRuntime(
            enabled_tools=self._enabled_tools,
            language=lang,
            core_registry=self._core_tool_registry,
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
            tool_runtime=self.tool_runtime,
            enable_pre_retrieve=not self.disable_planner_retrieve,
        )
        self.solver_agent = SolverAgent(**common, tool_runtime=self.tool_runtime)
        self.critic_agent = CriticAgent(**common, tool_runtime=self.tool_runtime)
        self.writer_agent = WriterAgent(**common)
        if self._trace_callback is not None:
            self.set_trace_callback(self._trace_callback)

        # Apply per-run overrides from benchmark config (pipeline.max_tokens / pipeline.temperature)
        if self._max_tokens_override is not None or self._temperature_override is not None:
            for agent in (self.planner_agent, self.solver_agent, self.critic_agent, self.writer_agent):
                if self._max_tokens_override is not None:
                    agent._agent_params["max_tokens"] = self._max_tokens_override
                if self._temperature_override is not None:
                    agent._agent_params["temperature"] = self._temperature_override

        self.logger.info(
            f"Agents initialised (lang={lang}), tools registered: {self.tool_runtime.tool_names}"
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def solve(
        self,
        question: str,
        image_url: str | None = None,
        attachments: list[Any] | None = None,
        verbose: bool = True,
        detailed: bool | None = None,
        conversation_context: str = "",
    ) -> dict[str, Any]:
        """Run the full Plan -> ReAct -> Write pipeline.

        Args:
            question: The user question to solve.
            image_url: Optional image URL for multimodal questions.
            attachments: Optional multimodal attachments from the chat composer.
            verbose: Enable verbose logging.
            detailed: If True, use iterative detailed writing. If None, read from config.

        Returns a dict compatible with the existing API contract.
        """
        # Resolve detailed flag: explicit param > config > default False
        if detailed is None:
            detailed = self.config.get("solve", {}).get("detailed_answer", False)
        self._detailed = detailed
        self._conversation_context = conversation_context.strip()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_service = get_path_service()
        output_base = self.config.get("system", {}).get(
            "output_base_dir", str(path_service.get_solve_dir())
        )
        output_dir = os.path.join(output_base, f"solve_{timestamp}")
        os.makedirs(output_dir, exist_ok=True)

        # Task-level log file
        task_log = os.path.join(output_dir, "task.log")
        self._add_task_log_handler(task_log)

        self._log_section("Problem Solving Started")
        self.logger.info(f"Question: {question[:100]}{'...' if len(question) > 100 else ''}")
        self.logger.info(f"Output: {output_dir}")

        try:
            # Pre-plan question quality gate
            quality = await self._check_question_quality(
                question=question,
                image_url=image_url,
                attachments=attachments,
            )
            if quality["needs_clarification"]:
                from deeptutor.agents.solve.pipeline_errors import (
                    QuestionNeedsClarification,
                )

                issues = (
                    "; ".join(quality["question_issues"])
                    if quality["question_issues"]
                    else "请补充完整信息后重试"
                )
                clarification = quality["clarification_prompt"] or issues
                raise QuestionNeedsClarification(
                    message=clarification,
                    question_issues=quality["question_issues"],
                )

            result = await self._run_pipeline(
                question,
                output_dir,
                image_url=image_url,
                attachments=attachments,
            )
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
                    result["metadata"]["cost_summary"] = {
                        "total_cost_usd": summary.get("total_cost_usd", 0),
                        "total_tokens": summary.get("total_tokens", 0),
                        "total_calls": summary.get("total_calls", 0),
                    }
                    self.token_tracker.reset()

            self.logger.info("Problem solving completed")
            self._remove_task_log_handler()
            return result

        except Exception as exc:
            self.logger.error(f"Solving failed: {exc}")
            self.logger.error(traceback.format_exc())
            self._remove_task_log_handler()
            raise

    # ------------------------------------------------------------------
    # Question quality gate
    # ------------------------------------------------------------------

    async def _check_question_quality(
        self,
        question: str,
        image_url: str | None = None,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Lightweight pre-plan check whether the question needs clarification.

        Returns {
            "needs_clarification": bool,
            "clarification_prompt": str,  # presented to the user if needs_clarification=True
            "question_issues": list[str],  # specific deficiencies found
        }
        """
        from deeptutor.core.context import Attachment

        system_prompt = (
            "You are a question quality assessor. Evaluate whether a user question "
            "is sufficiently complete and clear to be solved without clarification.\n\n"
            "IMPORTANT: If the user has attached an image (math problem, diagram, chart), "
            "the image CONTENT is the question — evaluate whether that image content is "
            "sufficiently clear and complete, not just the text surrounding it.\n\n"
            "A question needs clarification when:\n"
            "  - Key information is missing (e.g., undefined variables, unspecified constraints)\n"
            "  - The problem goal is ambiguous or has multiple interpretations\n"
            "  - Critical context is absent (e.g., referenced prior steps, prior conversation)\n"
            "  - The scope is unclear (e.g., 'solve this' without specifying what to solve)\n"
            "  - An image is present but the problem in the image is incomplete or ambiguous\n\n"
            "Output JSON only (no extra text):\n"
            '  {"needs_clarification": true/false, "clarification_prompt": "...", "question_issues": ["issue1", ...]}'
        )

        user_prompt = f"## Question to evaluate\n{question}"
        if image_url or (attachments and any(getattr(a, "type", "") == "image" for a in attachments)):
            user_prompt += "\n\n[Image is present — evaluate whether the image content is sufficiently clear and complete]"

        trace_meta = derive_trace_metadata(
            call_id=new_call_id("question-check"),
            phase="planning",
            label="QuestionQualityCheck",
            call_kind="single_turn",
            trace_id="question-check",
            trace_role="reasoning",
            trace_group="question_check",
        )

        llm_kwargs: dict[str, object] = {
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "response_format": {"type": "json_object"},
            "stage": "question_quality_check",
            "trace_meta": trace_meta,
        }

        if attachments:
            image_atts = [a for a in attachments if getattr(a, "type", "") == "image"]
            if image_atts:
                llm_kwargs["attachments"] = image_atts

        chunks: list[str] = []
        async for chunk in self.planner_agent.stream_llm(**llm_kwargs):
            chunks.append(chunk)
        response = "".join(chunks)

        try:
            import json

            data = json.loads(response)
            return {
                "needs_clarification": bool(data.get("needs_clarification", False)),
                "clarification_prompt": str(data.get("clarification_prompt", "")),
                "question_issues": list(data.get("question_issues", [])),
            }
        except Exception:
            # If parsing fails, be permissive — let the pipeline proceed
            return {
                "needs_clarification": False,
                "clarification_prompt": "",
                "question_issues": [],
            }

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        question: str,
        output_dir: str,
        image_url: str | None = None,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        solve_cfg = self.config.get("solve", {})
        max_react = solve_cfg.get("max_react_iterations", 5)
        max_replans = solve_cfg.get("max_replans", 2)

        scratchpad = Scratchpad.load_or_create(output_dir, question)

        # ============================================================
        # Phase 1: PLAN
        # ============================================================
        self._log_stage("Phase 1", "start", "Planning")
        if self.display_manager:
            self.display_manager.set_agent_status("PlannerAgent", "running")
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
            attachments=attachments,
        )
        scratchpad.set_plan(plan)
        scratchpad.save(output_dir)

        if self.display_manager:
            self.display_manager.set_agent_status("PlannerAgent", "done")
        self.logger.info(f"Plan: {len(plan.steps)} steps — {plan.analysis[:80]}")
        for s in plan.steps:
            self.logger.info(f"  [{s.id}] {s.goal}")
        self._update_token_stats(self.token_tracker.get_summary())

        # ============================================================
        # Phase 2: SOLVE (ReAct loop per step)
        # ============================================================
        self._log_stage("Phase 2", "start", "Solving")
        if self.display_manager:
            self.display_manager.set_agent_status("SolverAgent", "running")
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
            step_index = (
                next(
                    (i + 1 for i, s in enumerate(scratchpad.plan.steps) if s.id == step.id),
                    0,
                )
                if scratchpad.plan
                else 0
            )
            if hasattr(self, "_send_progress_update"):
                self._send_progress_update(
                    "solve",
                    {
                        "step_id": step.id,
                        "step_index": step_index,
                        "step_target": step.goal,
                    },
                )

            for round_num in range(max_react):
                decision = await self.solver_agent.process(
                    question=question,
                    current_step=step,
                    scratchpad=scratchpad,
                    memory_context=step_memory_context,
                    image_url=image_url,
                    round_index=round_num + 1,
                )

                action = decision["action"]
                action_input = decision["action_input"]
                thought = decision["thought"]
                self_note = decision["self_note"]
                trace_meta = decision.get("_trace", {})

                self.logger.info(f"    Round {round_num + 1}: {action}({action_input[:60]}...)")
                self.logger.debug(f"    Thought: {thought[:120]}")

                if action == "done":
                    if self_note:
                        await self._emit_trace_event(
                            {
                                "event": "llm_observation",
                                "state": "complete",
                                "response": self_note,
                                **trace_meta,
                            }
                        )
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
                    if self_note:
                        await self._emit_trace_event(
                            {
                                "event": "llm_observation",
                                "state": "complete",
                                "response": self_note,
                                **trace_meta,
                            }
                        )
                    replan_count += 1
                    self.logger.info(
                        f"    -> Replan requested ({replan_count}/{max_replans}): {action_input[:80]}"
                    )
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
                        if self.display_manager:
                            self.display_manager.set_agent_status("PlannerAgent", "running")
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
                            attachments=attachments,
                        )
                        scratchpad.update_plan(new_plan)
                        scratchpad.save(output_dir)
                        if self.display_manager:
                            self.display_manager.set_agent_status("PlannerAgent", "done")
                        self.logger.info(f"    Plan revised: {len(new_plan.steps)} steps")
                    else:
                        self.logger.warning("    Max replans reached — marking step completed")
                        scratchpad.mark_step_status(step.id, "completed")
                        scratchpad.save(output_dir)
                    break

                # Execute tool
                await self._emit_trace_event(
                    {
                        "event": "tool_call",
                        "state": "running",
                        "tool_name": action,
                        "tool_args": {"input": action_input},
                        **trace_meta,
                    }
                )
                observation, sources = await self._execute_tool(
                    action=action,
                    action_input=action_input,
                    output_dir=output_dir,
                    question=question,
                    scratchpad=scratchpad,
                    trace_meta=trace_meta,
                )
                await self._emit_trace_event(
                    {
                        "event": "tool_result",
                        "state": "complete",
                        "tool_name": action,
                        "result": observation,
                        "sources": [s.to_dict() for s in sources],
                        **trace_meta,
                    }
                )
                if self_note:
                    await self._emit_trace_event(
                        {
                            "event": "llm_observation",
                            "state": "complete",
                            "response": self_note,
                            **trace_meta,
                        }
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
                self._update_token_stats(self.token_tracker.get_summary())
            else:
                # Max rounds exhausted for this step
                self.logger.warning(f"    Max ReAct iterations reached for {step.id}")
                scratchpad.mark_step_status(step.id, "completed")
                scratchpad.save(output_dir)

        if self.display_manager:
            self.display_manager.set_agent_status("SolverAgent", "done")

        completed = scratchpad.get_completed_steps()
        total = len(scratchpad.plan.steps) if scratchpad.plan else 0
        self.logger.info(f"  Solve phase done: {len(completed)}/{total} steps completed")
        self._update_token_stats(self.token_tracker.get_summary())

        # ============================================================
        # Phase 2.5: CRITIC AUDIT
        # ============================================================
        self._log_stage("Phase 2.5", "start", "Auditing evidence and references")
        if self.display_manager:
            self.display_manager.set_agent_status("CriticAgent", "running")

        step_memory_context = "" if self.disable_memory else await self._get_planner_memory_context(question)
        scratchpad, verification_report = await self.critic_agent.process(
            question=question,
            scratchpad=scratchpad,
            memory_context=step_memory_context,
            kb_name=self.kb_name,
        )
        self.logger.info(
            f"  Critic audit done: {verification_report.get('rounds', 0)} rounds, "
            f"summary={verification_report.get('summary', 'N/A')}"
        )
        self._update_token_stats(self.token_tracker.get_summary())
        if self.display_manager:
            self.display_manager.set_agent_status("CriticAgent", "done")

        scratchpad.save(output_dir)

        # ============================================================
        # Phase 3: WRITE
        # ============================================================
        detailed = getattr(self, "_detailed", False)
        write_mode = "detailed iterative" if detailed else "simple"
        self._log_stage("Phase 3", "start", f"Writing answer ({write_mode})")
        if self.display_manager:
            self.display_manager.set_agent_status("WriterAgent", "running")
        if hasattr(self, "_send_progress_update"):
            self._send_progress_update("write", {"status": "writing"})

        language = self.config.get("system", {}).get("language", "en")
        lang_code = parse_language(language)

        preference = "" if self.disable_memory else self._get_user_preference()

        content_cb = getattr(self, "_content_callback", None)

        if detailed:
            final_answer = await self.writer_agent.process_iterative(
                question=question,
                scratchpad=scratchpad,
                language=lang_code,
                preference=preference,
                on_content_chunk=content_cb,
            )
        else:
            final_answer = await self.writer_agent.process(
                question=question,
                scratchpad=scratchpad,
                language=lang_code,
                preference=preference,
                on_content_chunk=content_cb,
            )

        if self.display_manager:
            self.display_manager.set_agent_status("WriterAgent", "done")

        # Save final answer
        answer_file = Path(output_dir) / "final_answer.md"
        with open(answer_file, "w", encoding="utf-8") as f:
            f.write(final_answer)
        self.logger.info(f"Final answer saved: {answer_file}")
        self._update_token_stats(self.token_tracker.get_summary())

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
        trace_meta: dict[str, Any] | None = None,
    ) -> tuple[str, list[Source]]:
        """Execute a tool and return (observation_text, sources)."""
        obs_max = self.config.get("solve", {}).get("observation_max_tokens", 2000)
        sources: list[Source] = []
        retrieve_trace = self._build_retrieve_trace_meta(action, action_input, trace_meta)

        try:
            if self.tool_runtime is None:
                raise RuntimeError("Solve tool runtime is not initialised.")
            if action not in self.tool_runtime.valid_actions:
                observation = f"Unknown action: {action}"
                return observation, sources

            async def _event_sink(
                event_type: str,
                message: str = "",
                metadata: dict[str, Any] | None = None,
            ) -> None:
                if retrieve_trace is None or not message:
                    return
                await self._emit_trace_event(
                    {
                        "event": "tool_log",
                        "message": message,
                        **derive_trace_metadata(
                            retrieve_trace,
                            trace_kind=str(event_type or "tool_log"),
                            **(metadata or {}),
                        ),
                    }
                )

            if retrieve_trace is not None:
                await self._emit_trace_event(
                    {
                        "event": "tool_log",
                        "message": f"Query: {action_input}"
                        if action_input
                        else "Starting retrieval",
                        **derive_trace_metadata(
                            retrieve_trace,
                            trace_kind="call_status",
                            call_state="running",
                        ),
                    }
                )

            result = await self.tool_runtime.execute(
                action,
                action_input,
                kb_name=self.kb_name or None,
                output_dir=output_dir,
                reason_context=self._build_reason_context(question, scratchpad),
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.solver_agent.get_model() if self.solver_agent else None,
                event_sink=_event_sink if retrieve_trace is not None else None,
            )
            if retrieve_trace is not None:
                await self._emit_trace_event(
                    {
                        "event": "tool_log",
                        "message": f"Retrieve complete ({len(result.content)} chars)",
                        **derive_trace_metadata(
                            retrieve_trace,
                            trace_kind="call_status",
                            call_state="complete",
                        ),
                    }
                )
            observation = self._format_tool_observation(
                action, result.content, result.metadata, obs_max
            )
            sources = self._convert_tool_sources(result.sources, result.metadata)
        except Exception as exc:
            observation = f"Tool error ({action}): {exc}"
            self.logger.warning(f"    Tool error: {exc}")
            if retrieve_trace is not None:
                await self._emit_trace_event(
                    {
                        "event": "tool_log",
                        "message": f"Retrieve failed: {exc}",
                        **derive_trace_metadata(
                            retrieve_trace,
                            trace_kind="call_status",
                            call_state="error",
                            error=str(exc),
                        ),
                    }
                )

        return observation, sources

    def _build_retrieve_trace_meta(
        self,
        action: str,
        action_input: str,
        trace_meta: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if self.tool_runtime is None or not trace_meta:
            return None
        resolved_tool = self.tool_runtime.resolve_tool_name(action)
        if resolved_tool != "rag":
            return None
        return derive_trace_metadata(
            trace_meta,
            call_id=new_call_id("solve-retrieve"),
            label="Retrieve",
            call_kind="rag_retrieval",
            trace_role="retrieve",
            trace_group="retrieve",
            trace_id=f"{trace_meta.get('trace_id', 'solve')}-retrieve",
            query=action_input,
            tool_name=resolved_tool,
        )

    def _build_reason_context(
        self,
        question: str,
        scratchpad: Scratchpad | None,
    ) -> str:
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

        return "\n\n".join(context_parts)

    @staticmethod
    def _format_tool_observation(
        action: str,
        content: str,
        metadata: dict[str, Any],
        max_chars: int,
    ) -> str:
        text = (content or "").strip() or "(no results)"
        if action in {"code_execution", "code_execute", "run_code"}:
            code = (metadata.get("code") or "").strip()
            if code:
                text = f"Code:\n```python\n{code}\n```\n\n{text}"
        return text[: max_chars * 4]

    @staticmethod
    def _convert_tool_sources(
        tool_sources: list[dict[str, Any]] | None,
        metadata: dict[str, Any],
    ) -> list[Source]:
        sources: list[Source] = []
        for item in tool_sources or []:
            if not isinstance(item, dict):
                continue
            sources.append(
                Source(
                    type=str(item.get("type", "reference")),
                    file=item.get("file") or item.get("title") or item.get("kb_name"),
                    page=item.get("page"),
                    url=item.get("url"),
                    chunk_id=item.get("chunk_id") or item.get("query") or item.get("identifier"),
                )
            )

        for artifact_path in metadata.get("artifact_paths", []):
            sources.append(Source(type="code", file=Path(artifact_path).name))
        return sources

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_preference(self) -> str:
        """Get personalisation preference (optional)."""
        try:
            from deeptutor.services.memory import get_memory_service

            return get_memory_service().get_preferences_text()
        except Exception:
            return ""

    async def _get_planner_memory_context(self, question: str) -> str:
        _ = question
        return self._merge_memory_context("")

    async def _get_solver_memory_context(self, step_goal: str) -> str:
        _ = step_goal
        return self._merge_memory_context(
            "",
            include_conversation=False,
        )

    def _merge_memory_context(
        self,
        memory_context: str,
        include_conversation: bool = True,
    ) -> str:
        parts = []
        if include_conversation and self._conversation_context:
            parts.append(f"Conversation context:\n{self._conversation_context}")
        if memory_context:
            parts.append(memory_context)
        return "\n\n".join(part for part in parts if part)

    async def _publish_event(
        self,
        question: str,
        answer: str,
        scratchpad: Scratchpad,
        output_dir: str,
    ) -> None:
        """Publish SOLVE_COMPLETE event for personalisation."""
        try:
            from deeptutor.events.event_bus import Event, EventType, get_event_bus

            task_id = Path(output_dir).name
            tools_used = list(
                {e.action for e in scratchpad.entries if e.action not in ("done", "replan")}
            )

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
