# -*- coding: utf-8 -*-
"""
Personalization Service
=======================

Service layer that coordinates personalization memory management.
Listens to events, builds traces, and runs three specialized memory
agents (Reflection, Summary, Weakness) in parallel.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.agents.base_agent import BaseAgent
from src.core.event_bus import Event, EventType, get_event_bus
from src.services.path_service import get_path_service

from .agents import ReflectionAgent, SummaryAgent, WeaknessAgent
from .memory_reader import MemoryReader
from .react_runner import ReActRunner
from .trace_forest import TraceForest
from .trace_tools import TraceToolkit
from .trace_tree import TraceNode, TraceTree

logger = logging.getLogger(__name__)


class PersonalizationService:
    """Orchestrates trace registration and three memory agents.

    After each ``SOLVE_COMPLETE`` or ``QUESTION_COMPLETE`` event the
    service:

    1. Builds and registers a :class:`TraceTree`.
    2. Launches three memory agents in parallel via :class:`ReActRunner`:

       * **ReflectionAgent** → ``reflection.md``
       * **SummaryAgent** → ``memory.md``
       * **WeaknessAgent** → ``weakness.md``

    Each agent explores the trace forest through the five-tool
    :class:`TraceToolkit` and writes its own document.
    """

    _instance: Optional["PersonalizationService"] = None
    _initialized: bool = False

    def __new__(cls) -> "PersonalizationService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if PersonalizationService._initialized:
            return

        self._running = False
        self._forest: Optional[TraceForest] = None
        self._reader: Optional[MemoryReader] = None
        self._config: Dict[str, Any] = {}
        self._language = "en"

        self._reflection_agent: Optional[ReflectionAgent] = None
        self._summary_agent: Optional[SummaryAgent] = None
        self._weakness_agent: Optional[WeaknessAgent] = None

        self._load_config()

        PersonalizationService._initialized = True
        logger.debug("PersonalizationService initialized")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        config_path = get_path_service().project_root / "config" / "memory.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
                logger.debug("Loaded memory config: %s", config_path)
            except Exception as e:
                logger.warning("Failed to load memory config: %s", e)
                self._config = {}
        else:
            self._config = {}

    @property
    def auto_update(self) -> bool:
        return self._config.get("memory", {}).get("auto_update", True)

    @property
    def max_react_rounds(self) -> int:
        return self._config.get("memory", {}).get("max_react_rounds", 6)

    def _agent_enabled(self, name: str) -> bool:
        agents_cfg = self._config.get("agents", {})
        return agents_cfg.get(name, {}).get("enabled", True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the personalization service."""
        if self._running:
            logger.debug("PersonalizationService already running")
            return

        self._running = True
        self._forest = TraceForest()
        self._reader = MemoryReader(forest=self._forest)

        llm_config = self._config.get("llm", {})
        temperature = llm_config.get("temperature", 0.5)

        self._reflection_agent = ReflectionAgent(
            language=self._language, temperature=temperature,
        )
        self._summary_agent = SummaryAgent(
            language=self._language, temperature=temperature,
        )
        self._weakness_agent = WeaknessAgent(
            language=self._language, temperature=temperature,
        )

        if self.auto_update:
            event_bus = get_event_bus()
            event_bus.subscribe(EventType.SOLVE_COMPLETE, self._handle_event)
            event_bus.subscribe(EventType.QUESTION_COMPLETE, self._handle_event)
            logger.info("PersonalizationService started, subscribed to events")
        else:
            logger.info("PersonalizationService started (auto-update disabled)")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self.auto_update:
            event_bus = get_event_bus()
            event_bus.unsubscribe(EventType.SOLVE_COMPLETE, self._handle_event)
            event_bus.unsubscribe(EventType.QUESTION_COMPLETE, self._handle_event)
        logger.info("PersonalizationService stopped")

    # ------------------------------------------------------------------
    # Event handling (write path)
    # ------------------------------------------------------------------

    async def _handle_event(self, event: Event) -> None:
        if not self._running or not self._forest:
            return

        try:
            event_type_str = event.type.value if hasattr(event.type, "value") else str(event.type)
            logger.info(
                "[MEM-WRITE] Received event: %s (task_id=%s)",
                event_type_str, event.task_id,
            )

            trace = self._build_trace_from_event(event)
            if trace:
                logger.info(
                    "[MEM-WRITE] Registering trace: id=%s type=%s nodes=%d",
                    trace.trace_id, trace.trace_type, len(trace.nodes),
                )
                await self._forest.register(trace)
                logger.info("[MEM-WRITE] Trace registered and indexed")
            else:
                logger.warning("[MEM-WRITE] No trace built from event")
                return

            if trace.trace_type == "question":
                logger.info(
                    "[MEM-WRITE] Question trace registered; "
                    "memory agents deferred until all answers are recorded."
                )
                return

            await self._run_memory_agents(trace)

        except Exception as e:
            logger.error("Failed to process event: %s", e, exc_info=True)

    async def _run_memory_agents(self, trace: TraceTree) -> None:
        """Launch the three memory agents in parallel."""
        toolkit = TraceToolkit(self._forest, self._forest.memory_dir)

        session_summary = self._build_session_summary(trace)
        full_context = self._build_full_context(trace)

        context_base = {
            "trace_id": trace.trace_id,
            "trace_type": trace.trace_type,
            "question": trace.root.text,
            "answer_path": trace.answer_path,
            "session_summary": session_summary,
            "full_context": full_context,
        }

        tasks: list[asyncio.Task] = []

        if self._agent_enabled("reflection") and self._reflection_agent:
            ctx = {**context_base, "current_document": self._read_md("reflection.md")}
            tasks.append(
                asyncio.create_task(
                    self._run_single_agent(
                        self._reflection_agent, toolkit, ctx,
                    ),
                    name="reflection",
                )
            )

        if self._agent_enabled("summary") and self._summary_agent:
            tasks.append(
                asyncio.create_task(
                    self._run_single_agent(
                        self._summary_agent, toolkit, context_base,
                    ),
                    name="summary",
                )
            )

        if self._agent_enabled("weakness") and self._weakness_agent:
            ctx = {**context_base, "current_document": self._read_md("weakness.md")}
            tasks.append(
                asyncio.create_task(
                    self._run_single_agent(
                        self._weakness_agent, toolkit, ctx,
                    ),
                    name="weakness",
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for task, result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.error(
                        "[MEM-WRITE] Agent '%s' failed: %s",
                        task.get_name(), result,
                    )
                else:
                    logger.info("[MEM-WRITE] Agent '%s' completed", task.get_name())

    async def _run_single_agent(
        self,
        agent: BaseAgent,
        toolkit: TraceToolkit,
        context: dict[str, str],
    ) -> None:
        """Run one memory agent through the ReAct loop."""
        system_prompt = agent.get_prompt("system", "")
        if not system_prompt:
            logger.warning("[MEM-WRITE] No system prompt for %s", agent.agent_name)
            return

        user_template = agent.get_prompt("user_template", "")
        if not user_template:
            logger.warning("[MEM-WRITE] No user_template for %s", agent.agent_name)
            return

        initial_context = user_template.format(**context)

        log_dir = self._forest.memory_dir / "logs" if self._forest else None
        runner = ReActRunner(
            agent=agent,
            toolkit=toolkit,
            max_rounds=self.max_react_rounds,
            log_dir=log_dir,
        )
        await runner.run(system_prompt=system_prompt, initial_context=initial_context)

    # ------------------------------------------------------------------
    # Trace building
    # ------------------------------------------------------------------

    def _build_trace_from_event(self, event: Event) -> Optional[TraceTree]:
        try:
            event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
            if event_type == EventType.SOLVE_COMPLETE.value:
                return self._build_solve_trace(event)
            if event_type == EventType.QUESTION_COMPLETE.value:
                return self._build_question_trace(event)
            return None
        except Exception as exc:
            logger.warning("[MEM-WRITE] Failed to build trace from event: %s", exc)
            return None

    def _build_solve_trace(self, event: Event) -> Optional[TraceTree]:
        metadata = event.metadata or {}
        output_dir = metadata.get("output_dir")
        scratchpad_path: Optional[Path] = None

        if output_dir:
            scratchpad_path = Path(output_dir) / "scratchpad.json"
        else:
            path_service = get_path_service()
            candidates = [
                path_service.get_solve_task_dir(event.task_id) / "scratchpad.json",
                path_service.user_data_dir / "solve" / event.task_id / "scratchpad.json",
            ]
            scratchpad_path = next((p for p in candidates if p.exists()), None)

        if not scratchpad_path or not scratchpad_path.exists():
            logger.warning(
                "[MEM-WRITE] Scratchpad not found (output_dir=%s, task_id=%s)",
                output_dir, event.task_id,
            )
            return None

        scratchpad_payload = self._load_json(scratchpad_path)
        if not isinstance(scratchpad_payload, dict):
            logger.warning("[MEM-WRITE] Invalid scratchpad JSON at %s", scratchpad_path)
            return None

        answer_path = ""
        if output_dir:
            candidate = Path(output_dir) / "final_answer.md"
            if candidate.exists():
                answer_path = str(candidate)

        logger.info("[MEM-WRITE] Building solve trace from %s", scratchpad_path)
        return TraceTree.from_scratchpad(
            scratchpad_payload,
            task_id=event.task_id,
            answer_path=answer_path,
        )

    def _build_question_trace(self, event: Event) -> Optional[TraceTree]:
        metadata = event.metadata or {}
        batch_dir = metadata.get("batch_dir")
        if not batch_dir:
            logger.warning("[MEM-WRITE] No batch_dir in question event metadata")
            return None

        summary_path = Path(batch_dir) / "summary.json"
        if not summary_path.exists():
            logger.warning("[MEM-WRITE] Summary not found at %s", summary_path)
            return None

        summary_payload = self._load_json(summary_path)
        if not isinstance(summary_payload, dict):
            return None

        user_topic = str(metadata.get("user_topic", "") or "")
        if not user_topic:
            try:
                user_input_payload = json.loads(event.user_input)
                user_topic = str(user_input_payload.get("topic", "") or "")
            except Exception:
                user_topic = ""
        trace_id = Path(batch_dir).name or event.task_id

        answer_path = str(summary_path)
        return TraceTree.from_question_summary(
            summary=summary_payload,
            user_topic=user_topic,
            task_id=trace_id,
            include_answers=False,
            answer_path=answer_path,
        )

    def _read_md(self, filename: str) -> str:
        """Read a markdown file from the memory directory, returning its content or a placeholder."""
        if not self._forest:
            return "(document not found)"
        p = self._forest.memory_dir / filename
        try:
            return p.read_text(encoding="utf-8").strip() or "(empty document)"
        except FileNotFoundError:
            return "(document not found)"

    @staticmethod
    def _load_json(path: Path) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Context builders for memory agents
    # ------------------------------------------------------------------

    def _build_session_summary(self, trace: TraceTree) -> str:
        """Build a concise structured summary from a trace tree.

        For solve traces: steps, rounds, tools, per-step goal+status.
        For question traces: per-question type/difficulty/result + totals.
        """
        if trace.trace_type == "solve":
            return self._build_solve_summary(trace)
        if trace.trace_type == "question":
            return self._build_question_summary(trace)
        return "(unknown trace type)"

    @staticmethod
    def _build_solve_summary(trace: TraceTree) -> str:
        steps = [n for n in trace.nodes.values() if n.node_type == "step"]
        tools = sorted(trace.tools_used) if trace.tools_used else ["none"]
        total_rounds = sum(1 for n in trace.nodes.values() if n.node_type == "round")

        lines = [
            f"Solve summary: {len(steps)} steps, {total_rounds} ReAct rounds, "
            f"tools: {', '.join(tools)}",
        ]
        for step in steps:
            n_rounds = len(step.children)
            status = step.data.get("status", "?")
            goal = step.data.get("step_goal", step.text)
            lines.append(f"- {step.short_id} \"{goal}\" ({n_rounds} rounds) -> {status}")
        return "\n".join(lines)

    @staticmethod
    def _build_question_summary(trace: TraceTree) -> str:
        templates = [n for n in trace.nodes.values() if n.node_type == "template"]
        correct = wrong = skipped = 0

        q_lines: list[str] = []
        for tmpl in templates:
            qtype = tmpl.data.get("question_type", "?")
            diff = tmpl.data.get("difficulty", "?")
            conc = tmpl.data.get("concentration", tmpl.text)

            answer_nodes = [
                trace.nodes[cid]
                for cid in tmpl.children
                if cid in trace.nodes and trace.nodes[cid].node_type == "answer"
            ]
            if answer_nodes:
                result = str(answer_nodes[0].data.get("judged_result", "unknown"))
                if result.lower() in ("correct", "true"):
                    correct += 1
                elif result.lower() in ("wrong", "incorrect", "false"):
                    wrong += 1
                else:
                    skipped += 1
            else:
                result = "no_answer"
                skipped += 1

            q_lines.append(f"- {tmpl.short_id} [{qtype}/{diff}] \"{conc}\" -> {result}")

        total = correct + wrong + skipped
        header = (
            f"Question summary: {total} questions | "
            f"correct {correct}, wrong {wrong}, skipped {skipped}"
        )
        return "\n".join([header] + q_lines)

    def _build_full_context(self, trace: TraceTree) -> str:
        """Build the complete session content for the first ReAct round.

        For solve traces: full final_answer.md content.
        For question traces: full Q&A pairs from summary.json.
        """
        if trace.trace_type == "solve":
            return self._build_solve_full_context(trace)
        if trace.trace_type == "question":
            return self._build_question_full_context(trace)
        return "(unknown trace type)"

    def _build_solve_full_context(self, trace: TraceTree) -> str:
        if not trace.answer_path:
            return "(no final answer available)"
        p = Path(trace.answer_path)
        if not p.exists():
            return "(no final answer available)"
        try:
            content = p.read_text(encoding="utf-8").strip()
            return content if content else "(final answer file is empty)"
        except Exception:
            return "(failed to read final answer)"

    def _build_question_full_context(self, trace: TraceTree) -> str:
        """Extract full Q&A content from summary.json, with user answers from trace."""
        summary_data = None
        if trace.answer_path:
            summary_data = self._load_json(Path(trace.answer_path))

        results = []
        if isinstance(summary_data, dict):
            results = list(summary_data.get("results", []) or [])

        if not results:
            return self._build_question_full_context_from_trace(trace)

        parts: list[str] = []
        templates = [n for n in trace.nodes.values() if n.node_type == "template"]
        tmpl_by_qid: dict[str, TraceNode] = {}
        for t in templates:
            qid = t.data.get("question_id", "")
            if qid:
                tmpl_by_qid[qid] = t

        for idx, result in enumerate(results, 1):
            qa = result.get("qa_pair", {}) or {}
            template = result.get("template", {}) or {}

            qid = str(template.get("question_id") or qa.get("question_id") or f"q_{idx}")
            qtype = str(template.get("question_type") or qa.get("question_type") or "?")
            diff = str(template.get("difficulty") or qa.get("difficulty") or "?")
            question_text = str(qa.get("question", "") or "")
            correct_answer = str(qa.get("correct_answer", "") or qa.get("answer", "") or "")
            explanation = str(qa.get("explanation", "") or "")
            options = qa.get("options", None)

            tmpl_node = tmpl_by_qid.get(qid)
            user_answer = ""
            judged = "no_answer"
            if tmpl_node:
                for cid in tmpl_node.children:
                    child = trace.nodes.get(cid)
                    if child and child.node_type == "answer":
                        user_answer = str(child.data.get("user_answer", "") or "")
                        judged = str(child.data.get("judged_result", "unknown") or "unknown")
                        break

            block = [f"--- Question {idx} [{qtype}/{diff}] ---"]
            if question_text:
                block.append(f"Question: {question_text}")
            if options and isinstance(options, (list, dict)):
                if isinstance(options, list):
                    for opt in options:
                        block.append(f"  {opt}")
                elif isinstance(options, dict):
                    for key, val in options.items():
                        block.append(f"  {key}. {val}")
            if correct_answer:
                block.append(f"Correct answer: {correct_answer}")
            block.append(f"User answer: {user_answer or '(none)'}")
            block.append(f"Judged: {judged}")
            if explanation:
                block.append(f"Explanation: {explanation}")
            parts.append("\n".join(block))

        return "\n\n".join(parts)

    @staticmethod
    def _build_question_full_context_from_trace(trace: TraceTree) -> str:
        """Fallback: build Q&A context directly from trace nodes."""
        templates = [n for n in trace.nodes.values() if n.node_type == "template"]
        if not templates:
            return "(no question data available)"

        parts: list[str] = []
        for idx, tmpl in enumerate(templates, 1):
            qtype = tmpl.data.get("question_type", "?")
            diff = tmpl.data.get("difficulty", "?")
            conc = tmpl.data.get("concentration", tmpl.text)

            block = [f"--- Question {idx} [{qtype}/{diff}] ---"]
            block.append(f"Topic: {conc}")

            for cid in tmpl.children:
                child = trace.nodes.get(cid)
                if child and child.node_type == "answer":
                    user_answer = str(child.data.get("user_answer", "") or "")
                    judged = str(child.data.get("judged_result", "unknown") or "unknown")
                    block.append(f"User answer: {user_answer or '(none)'}")
                    block.append(f"Judged: {judged}")
                    break

            parts.append("\n".join(block))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Record user answer (question flow phase 2)
    # ------------------------------------------------------------------

    async def record_user_answer(
        self,
        trace_id: str,
        question_id: str,
        user_answer: str,
        judged_result: str,
    ) -> bool:
        """Append/update an L3 answer node after the user answers a question."""
        if not self._forest:
            self._forest = TraceForest()

        logger.info(
            "[MEM-WRITE] record_user_answer: trace=%s question=%s judged=%s",
            trace_id, question_id, judged_result,
        )

        tree = self._forest.load_tree(trace_id)
        if tree is None:
            logger.warning("record_user_answer: trace %s not found", trace_id)
            return False

        q_idx = question_id.replace("q_", "")
        tmpl_short = f"T{q_idx}" if q_idx.isdigit() else f"T{question_id}"
        template_node = tree.nodes.get(tmpl_short)
        if template_node is None:
            for node in tree.nodes.values():
                if node.node_type == "template" and node.data.get("question_id") == question_id:
                    template_node = node
                    tmpl_short = node.short_id
                    break
        if template_node is None:
            logger.warning(
                "record_user_answer: template node for %s not found in trace %s",
                question_id, trace_id,
            )
            return False

        answer_short = f"{tmpl_short}.A1"
        answer_text = (user_answer or "").strip() or question_id

        answer_node = TraceNode(
            short_id=answer_short,
            level=3,
            text=answer_text,
            node_type="answer",
            data={
                "question_id": question_id,
                "user_answer": user_answer,
                "judged_result": judged_result,
                "question": template_node.data.get("concentration", ""),
            },
            parent=tmpl_short,
        )

        is_new = answer_short not in tree.nodes
        if is_new:
            template_node.children.append(answer_short)
        tree.nodes[answer_short] = answer_node

        try:
            await self._forest.register(tree)
            logger.info(
                "[MEM-WRITE] Answer node %s (%s) -> trace re-registered",
                "created" if is_new else "updated", answer_short,
            )
        except Exception as exc:
            logger.error("record_user_answer: failed to persist tree: %s", exc)
            return False

        return True

    async def flush_memory_agents(self, trace_id: str) -> None:
        """Run memory agents on a completed trace (e.g. after all answers recorded).

        Called explicitly by the caller (e.g. question CLI) once the full
        interaction is finished, so that agents see the complete trace.
        """
        if not self._forest:
            self._forest = TraceForest()

        tree = self._forest.load_tree(trace_id)
        if tree is None:
            logger.warning("[MEM-WRITE] flush_memory_agents: trace %s not found", trace_id)
            return

        logger.info(
            "[MEM-WRITE] flush_memory_agents: running agents on trace %s (%d nodes)",
            trace_id, len(tree.nodes),
        )
        await self._run_memory_agents(tree)

    # ------------------------------------------------------------------
    # Public interface (read path)
    # ------------------------------------------------------------------

    def get_memory_reader(self) -> MemoryReader:
        if not self._forest:
            self._forest = TraceForest()
        if not self._reader:
            self._reader = MemoryReader(forest=self._forest)
        return self._reader

    async def find_node(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if not self._forest:
            self._forest = TraceForest()
        results = await self._forest.semantic_search(query=query, top_k=top_k)
        return results

    def set_language(self, language: str) -> None:
        self._language = language
        for agent in (self._reflection_agent, self._summary_agent, self._weakness_agent):
            if agent:
                agent.language = language

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            cls._instance._running = False
        cls._instance = None
        cls._initialized = False


# Module-level singleton accessor
_personalization_service: Optional[PersonalizationService] = None


def get_personalization_service() -> PersonalizationService:
    global _personalization_service
    if _personalization_service is None:
        _personalization_service = PersonalizationService()
    return _personalization_service
