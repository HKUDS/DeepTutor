#!/usr/bin/env python
"""
ToolAgent - Tool executor
Responsible for reading tool calls in solve-chain, actually executing tools and producing summary
"""

from pathlib import Path
import re
import sys
import time
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.tools.code_executor import run_code
from src.tools.rag_tool import rag_search
from src.tools.web_search import web_search

from ..base_agent import BaseAgent
from ..memory import CitationMemory, SolveChainStep, SolveMemory
from ..memory.solve_memory import ToolCallRecord


class ToolAgent(BaseAgent):
    """Execute tool calls and generate summary"""

    def __init__(self, config: dict[str, Any], api_key: str, base_url: str, token_tracker=None):
        super().__init__(
            config=config,
            api_key=api_key,
            base_url=base_url,
            agent_name="tool_agent",
            use_prompt_loader=True,
            token_tracker=token_tracker,
        )
        # Read web_search enabled config from tools.web_search.enabled
        self.enable_web_search = config.get("tools", {}).get("web_search", {}).get("enabled", True)

    async def process(
        self,
        step: SolveChainStep,
        solve_memory: SolveMemory,
        citation_memory: CitationMemory,
        kb_name: str,
        output_dir: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        pending = [
            call
            for call in step.tool_calls
            if call.tool_type not in {"none", "finish"} and call.status in {"pending", "running"}
        ]

        if not pending:
            return {"step_id": step.step_id, "executed": [], "status": "idle"}

        logs: list[dict[str, Any]] = []
        base_dir = Path(output_dir).resolve() if output_dir else Path().resolve()
        artifacts_dir = base_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.logger.log_stage_progress(
            "Tool", "start", f"step={step.step_id}, pending_calls={len(pending)}"
        )

        for record in pending:
            call_label = f"{record.tool_type} | cite={record.cite_id or '-'}"
            self.logger.log_stage_progress(
                "Tool", "running", f"step={step.step_id}, call={call_label}"
            )
            start_ts = time.time()
            try:
                raw_answer, metadata = await self._execute_single_call(
                    record=record,
                    kb_name=kb_name,
                    output_dir=output_dir,
                    artifacts_dir=str(artifacts_dir),
                    verbose=verbose,
                )

                # Check if code execution failed
                is_failed = False
                if record.tool_type == "code_execution":
                    is_failed = metadata.get("execution_failed", False)
                    exit_code = metadata.get("exit_code", 0)
                    if exit_code != 0:
                        is_failed = True

                summary = await self._summarize_tool_result(
                    tool_type=record.tool_type, query=record.query, raw_answer=raw_answer
                )

                # Set correct status based on execution result
                status = "failed" if is_failed else "success"
                solve_memory.update_tool_call_result(
                    step_id=step.step_id,
                    call_id=record.call_id,
                    raw_answer=raw_answer,
                    summary=summary,
                    status=status,
                    metadata=metadata,  # Pass metadata to ensure artifacts are saved
                )
                citation_memory.update_citation(
                    cite_id=record.cite_id,
                    raw_result=raw_answer,
                    content=summary,
                    metadata=metadata,
                    step_id=step.step_id,
                )
                elapsed_ms = (time.time() - start_ts) * 1000
                self.logger.log_tool_call(
                    tool_name=record.tool_type,
                    tool_input={
                        "step_id": step.step_id,
                        "call_id": record.call_id,
                        "query": record.query,
                    },
                    tool_output=raw_answer,
                    status="success",
                    elapsed_ms=elapsed_ms,
                    step_id=step.step_id,
                    cite_id=record.cite_id,
                )
                logs.append(
                    {
                        "call_id": record.call_id,
                        "tool_type": record.tool_type,
                        "cite_id": record.cite_id,
                        "status": "success",
                        "summary": summary,
                    }
                )
            except Exception as e:
                error_msg = str(e)
                elapsed_ms = (time.time() - start_ts) * 1000
                solve_memory.update_tool_call_result(
                    step_id=step.step_id,
                    call_id=record.call_id,
                    raw_answer=error_msg,
                    summary=error_msg[:200],
                    status="failed",
                    metadata={"error": True},
                )
                citation_memory.update_citation(
                    cite_id=record.cite_id,
                    raw_result=error_msg,
                    content=error_msg[:200],
                    metadata={"error": True},
                    step_id=step.step_id,
                )
                self.logger.log_tool_call(
                    tool_name=record.tool_type,
                    tool_input={
                        "step_id": step.step_id,
                        "call_id": record.call_id,
                        "query": record.query,
                    },
                    tool_output=error_msg,
                    status="failed",
                    elapsed_ms=elapsed_ms,
                    step_id=step.step_id,
                    cite_id=record.cite_id,
                )
                self.logger.log_stage_progress(
                    "Tool", "warning", f"step={step.step_id}, call={call_label}, error={error_msg}"
                )
                logs.append(
                    {
                        "call_id": record.call_id,
                        "tool_type": record.tool_type,
                        "cite_id": record.cite_id,
                        "status": "failed",
                        "error": error_msg,
                    }
                )

        solve_memory.save()
        citation_memory.save()

        self.logger.log_stage_progress(
            "Tool", "complete", f"step={step.step_id}, executed={len(logs)}"
        )

        return {"step_id": step.step_id, "executed": logs, "status": "completed"}

    async def _execute_single_call(
        self,
        record: ToolCallRecord,
        kb_name: str,
        output_dir: str | None,
        artifacts_dir: str,
        verbose: bool,
    ) -> tuple[str, dict[str, Any]]:
        tool_type = record.tool_type
        query = record.query

        if tool_type == "rag_naive":
            result = await rag_search(query=query, kb_name=kb_name, mode="naive")
            answer = result.get("answer", "")
            source, auto_sources = self._infer_sources(answer)
            metadata = {"source": source, "auto_sources": auto_sources, "mode": "naive"}
            return answer, metadata

        if tool_type == "rag_hybrid":
            result = await rag_search(query=query, kb_name=kb_name, mode="hybrid")
            answer = result.get("answer", "")
            source, auto_sources = self._infer_sources(answer)
            metadata = {"source": source, "auto_sources": auto_sources, "mode": "hybrid"}
            return answer, metadata

        if tool_type == "web_search":
            # Check if web_search is enabled
            if not self.enable_web_search:
                self.logger.warning(
                    "Tool call rejected (web_search): web_search is disabled in config. "
                    "Falling back to RAG naive search."
                )
                # Fallback to RAG naive search when web_search is disabled
                result = await rag_search(query=query, kb_name=kb_name, mode="naive")
                answer = result.get("answer", "")
                source, auto_sources = self._infer_sources(answer)
                metadata = {"source": source, "auto_sources": auto_sources, "mode": "naive", "fallback_from": "web_search"}
                return answer, metadata
            
            result = web_search(query=query, output_dir=output_dir, verbose=verbose)
            answer = result.get("answer") or result.get("summary") or ""
            used_citation_ids = self._extract_answer_citations(answer)
            filtered_citations = self._select_web_citations(used_citation_ids, result)
            metadata = {"result_file": result.get("result_file"), "citations": filtered_citations}
            return answer, metadata

        if tool_type == "code_execution":
            artifacts_path = Path(artifacts_dir)
            before_snapshot = self._snapshot_image_artifacts(artifacts_path)

            if not query or not query.strip():
                # If code is empty, directly return failure without execution
                raw_answer = "【⚠️ Code execution failed】\nError: No valid code input received (Code is empty). Please check if [QUERY] contains a markdown code block."
                metadata = {
                    "exit_code": 1,
                    "artifacts": [],
                    "artifact_paths": [],
                    "artifact_rel_paths": [],
                    "work_dir": artifacts_dir,
                    "execution_failed": True,
                }
                return raw_answer, metadata

            exec_result = await run_code(
                language="python",
                code=query,
                timeout=self.agent_config.get("code_timeout", 20),
                assets_dir=artifacts_dir,
            )
            raw_answer = self._format_code_answer(exec_result, artifacts_dir)
            exit_code = exec_result.get("exit_code", 0)

            # Check if code execution failed
            is_failed = exit_code != 0
            if is_failed:
                stderr = exec_result.get("stderr", "")
                # Add obvious error prefix at the beginning of raw_answer
                error_prefix = "【⚠️ Code execution failed】\n"
                if "FileNotFoundError" in stderr and "artifacts/" in stderr:
                    error_prefix += "Path error detected: Code uses 'artifacts/xxx.png', but working directory is already the artifacts directory.\n"
                    error_prefix += "Please use 'xxx.png' instead of 'artifacts/xxx.png'.\n\n"
                raw_answer = error_prefix + raw_answer

            new_image_paths = self._collect_new_image_artifacts(
                artifacts_path=artifacts_path,
                before_snapshot=before_snapshot,
                output_dir=output_dir,
            )

            metadata = {
                "exit_code": exit_code,
                "artifacts": exec_result.get("artifacts", []),
                "artifact_paths": exec_result.get("artifact_paths", []),
                "artifact_rel_paths": new_image_paths,
                "work_dir": artifacts_dir,
                "execution_failed": is_failed,
            }
            return raw_answer, metadata

        raise ValueError(f"Unknown tool type: {tool_type}")

    def _format_code_answer(self, exec_result: dict[str, Any], artifacts_dir: str) -> str:
        stdout = exec_result.get("stdout", "")
        stderr = exec_result.get("stderr", "")
        artifacts = exec_result.get("artifacts", [])
        artifact_paths = exec_result.get("artifact_paths", [])

        lines = [
            "【Code Execution Result】",
            f"Exit code: {exec_result.get('exit_code')}",
            f"Elapsed time: {exec_result.get('elapsed_ms', 0):.2f} ms",
            f"Working directory: {artifacts_dir}",
            "",
            "stdout:",
            stdout or "(empty)",
            "",
            "stderr:",
            stderr or "(empty)",
        ]

        if artifacts:
            lines.append("")
            lines.append("Artifacts:")
            for idx, artifact in enumerate(artifacts):
                abs_path = (
                    artifact_paths[idx]
                    if idx < len(artifact_paths)
                    else str(Path(artifacts_dir) / artifact)
                )
                lines.append(f"- {abs_path}")

        return "\n".join(lines)

    async def _summarize_tool_result(self, tool_type: str, query: str, raw_answer: str) -> str:
        system_prompt = self.get_prompt("system") if self.has_prompts() else None
        if not system_prompt:
            raise ValueError(
                "ToolAgent missing system prompt, please configure system in prompts/{lang}/solve_loop/tool_agent.yaml"
            )

        template = self.get_prompt("user_template") if self.has_prompts() else None
        if not template:
            raise ValueError(
                "ToolAgent missing user_template, please configure user_template in prompts/{lang}/solve_loop/tool_agent.yaml"
            )

        user_prompt = template.format(
            tool_type=tool_type, query=query, raw_answer=raw_answer[:2000]
        )

        response = await self.call_llm(
            user_prompt=user_prompt, system_prompt=system_prompt, verbose=False
        )
        return response.strip()

    def _infer_sources(self, text: str) -> tuple[str, list[str]]:
        if not text:
            return "", []
        matches = re.findall(r"(https?://[^\s\)\]]+)", text)
        cleaned = []
        for item in matches:
            normalized = item.strip().strip(".,;:()[]{}")
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return (", ".join(cleaned), cleaned)

    def _extract_answer_citations(self, answer: str) -> list[str]:
        if not answer:
            return []
        pattern = re.compile(r"\[(\d+)\]")
        ids = pattern.findall(answer)
        unique: list[str] = []
        for cid in ids:
            if cid not in unique:
                unique.append(cid)
        return unique

    def _select_web_citations(
        self, used_ids: list[str], result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if not used_ids:
            return []
        raw_citations = result.get("citations") or []
        search_results = result.get("search_results") or []
        search_map = {item.get("url"): item for item in search_results if item.get("url")}

        selected: list[dict[str, Any]] = []
        for cid in used_ids:
            matched = None
            for raw in raw_citations:
                ref_id = str(raw.get("id")) if raw.get("id") is not None else ""
                ref_token = (raw.get("reference") or "").strip()
                normalized_token = ref_token.strip("[]")
                if cid == ref_id or cid == normalized_token:
                    matched = dict(raw)
                    break
            if not matched:
                continue

            url = matched.get("url")
            if url and url in search_map:
                fallback = search_map[url]
                matched.setdefault("title", fallback.get("title", ""))
                matched.setdefault("snippet", fallback.get("snippet", ""))

            selected.append(
                {
                    "id": matched.get("id") or (int(cid) if cid.isdigit() else cid),
                    "reference": matched.get("reference") or f"[{cid}]",
                    "url": matched.get("url"),
                    "title": matched.get("title", ""),
                }
            )
        return selected

    # ------------------------------------------------------------------ #
    # Artifacts helpers
    # ------------------------------------------------------------------ #
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".bmp"}

    def _snapshot_image_artifacts(self, artifacts_path: Path) -> set:
        if not artifacts_path.exists():
            return set()
        snapshot = set()
        for file_path in artifacts_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in self.IMAGE_SUFFIXES:
                snapshot.add(file_path.resolve())
        return snapshot

    def _collect_new_image_artifacts(
        self, artifacts_path: Path, before_snapshot: set, output_dir: str | None
    ) -> list[str]:
        after_snapshot = self._snapshot_image_artifacts(artifacts_path)
        new_files = sorted(after_snapshot - before_snapshot)
        if not new_files:
            return []

        rel_paths: list[str] = []
        output_base = Path(output_dir).resolve() if output_dir else None

        for file_path in new_files:
            rel_path: str | None = None
            if output_base:
                try:
                    rel_path = str(file_path.relative_to(output_base)).replace("\\", "/")
                except ValueError:
                    rel_path = None
            if rel_path is None:
                try:
                    rel_path = str(file_path.relative_to(artifacts_path.parent)).replace("\\", "/")
                except ValueError:
                    rel_path = str(Path("artifacts") / file_path.name)
            rel_paths.append(rel_path)

        return rel_paths
