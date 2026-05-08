"""
EditAgent - Co-writer editing agent.
Inherits from unified BaseAgent.
"""

from datetime import datetime
import json
from typing import Any, Literal
import uuid

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.path_service import get_path_service
from deeptutor.tools.rag_tool import rag_search
from deeptutor.tools.web_search import web_search


# Resolved per-call so a per-user PathService (set after auth) routes
# co-writer history/tool-call files under the caller's own workspace.
def _user_dir():
    return get_path_service().get_co_writer_dir()


def _history_file():
    return get_path_service().get_co_writer_history_file()


def tool_calls_dir():
    return get_path_service().get_co_writer_tool_calls_dir()


def ensure_dirs():
    """Ensure directories exist"""
    _user_dir().mkdir(parents=True, exist_ok=True)
    tool_calls_dir().mkdir(parents=True, exist_ok=True)


def load_history() -> list:
    """Load history"""
    ensure_dirs()
    history_file = _history_file()
    if history_file.exists():
        try:
            with open(history_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history: list):
    """Save history"""
    ensure_dirs()
    with open(_history_file(), "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_tool_call(call_id: str, tool_type: str, data: dict[str, Any]) -> str:
    """Save tool call result, return file path"""
    ensure_dirs()
    filename = f"{call_id}_{tool_type}.json"
    filepath = tool_calls_dir() / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(filepath)


class EditAgent(BaseAgent):
    """Co-writer editing agent using unified BaseAgent."""

    def __init__(
        self,
        language: str = "en",
        enabled_tools: list[str] | None = None,
        **kwargs: Any,
    ):
        """
        Initialize EditAgent.

        Args:
            language: Language setting ('en' | 'zh'), default 'en'

        Note: LLM configuration (api_key, base_url, model, etc.) is loaded
        automatically from the unified config service. Use refresh_config()
        to pick up configuration changes made in Settings.
        """
        super().__init__(
            module_name="co_writer",
            agent_name="edit_agent",
            language=language,
            **kwargs,
        )
        self.enabled_tools = enabled_tools or ["rag", "web_search"]
        self._tool_registry = get_tool_registry()

    async def process(
        self,
        text: str,
        instruction: str,
        action: Literal["rewrite", "shorten", "expand"] = "rewrite",
        source: Literal["rag", "web"] | None = None,
        kb_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Process edit request

        Returns:
            Dict containing:
                - edited_text: Edited text
                - operation_id: Operation ID
        """
        operation_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

        context = ""
        tool_call_file = None
        tool_call_data = None

        if source == "rag" and "rag" not in self.enabled_tools:
            self.logger.warning("RAG source requested but tool is not enabled")
            source = None
        if source == "web" and "web_search" not in self.enabled_tools:
            self.logger.warning("Web source requested but tool is not enabled")
            source = None

        if source == "rag":
            if not kb_name:
                self.logger.warning(
                    "RAG source selected but no kb_name provided, skipping RAG search"
                )
                source = None
            else:
                self.logger.info(f"Searching RAG in KB: {kb_name} for: {instruction}")
                try:
                    search_result = await rag_search(
                        query=instruction, kb_name=kb_name, only_need_context=True
                    )
                    context = search_result.get("answer", "")
                    self.logger.info(f"RAG context found: {len(context)} chars")

                    tool_call_data = {
                        "type": "rag",
                        "timestamp": datetime.now().isoformat(),
                        "operation_id": operation_id,
                        "query": instruction,
                        "kb_name": kb_name,
                        "mode": "naive",
                        "context": context,
                        "raw_result": search_result,
                    }
                    tool_call_file = save_tool_call(operation_id, "rag", tool_call_data)
                except Exception as e:
                    self.logger.error(f"RAG search failed: {e}, continuing without context")
                    source = None

        elif source == "web":
            self.logger.info(f"Searching Web for: {instruction}")
            try:
                search_result = web_search(instruction)
                context = search_result.get("answer", "")
                self.logger.info(f"Web context found: {len(context)} chars")

                tool_call_data = {
                    "type": "web_search",
                    "timestamp": datetime.now().isoformat(),
                    "operation_id": operation_id,
                    "query": instruction,
                    "answer": context,
                    "citations": search_result.get("citations", []),
                    "search_results": search_result.get("search_results", []),
                    "usage": search_result.get("usage", {}),
                }
                tool_call_file = save_tool_call(operation_id, "web", tool_call_data)
            except Exception as e:
                self.logger.error(f"Web search failed: {e}, continuing without context")
                source = None

        # Build prompts
        system_template = self.get_prompt(
            "system",
            "You are an expert editor and writing assistant.\n\nAvailable reference tools:\n{available_tools}",
        )
        system_prompt = system_template.format(available_tools=self._build_available_tools_text())

        action_verbs = {"rewrite": "Rewrite", "shorten": "Shorten", "expand": "Expand"}
        action_verb = action_verbs.get(action, "Rewrite")

        action_template = self.get_prompt(
            "action_template",
            "{action_verb} the following text based on the user's instruction.\n\nUser Instruction: {instruction}\n\n",
        )
        user_prompt = action_template.format(action_verb=action_verb, instruction=instruction)

        if context:
            context_template = self.get_prompt(
                "context_template", "Reference Context ({source_label}):\n{context}\n\n"
            )
            user_prompt += context_template.format(
                context=context,
                source_label=self._get_source_label(source),
            )

        text_template = self.get_prompt(
            "user_template",
            "Target Text to Edit:\n{text}\n\nOutput only the edited text, without quotes or explanations.",
        )
        user_prompt += text_template.format(text=text)

        # Call LLM using inherited method
        self.logger.info(f"Calling LLM for {action}...")
        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage=f"edit_{action}",
        ):
            _chunks.append(_c)
        response = clean_thinking_tags("".join(_chunks), self.binding, self.get_model())

        # Record operation history
        history = load_history()
        operation_record = {
            "id": operation_id,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "source": source,
            "kb_name": kb_name,
            "input": {"original_text": text, "instruction": instruction},
            "output": {"edited_text": response},
            "tool_call_file": tool_call_file,
            "model": self.get_model(),
        }
        history.append(operation_record)
        save_history(history)

        self.logger.info(f"Operation {operation_id} recorded successfully")

        return {"edited_text": response, "operation_id": operation_id}

    async def auto_mark(self, text: str) -> dict[str, Any]:
        """
        AI auto-marking feature - Add annotation tags to text

        Returns:
            Dict containing:
                - marked_text: Text with annotations
                - operation_id: Operation ID
        """
        operation_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

        system_prompt = self.get_prompt("auto_mark_system", "")
        user_template = self.get_prompt(
            "auto_mark_user_template", "Process the following text:\n{text}"
        )
        user_prompt = user_template.format(text=text)

        self.logger.info("Calling LLM for auto-mark...")
        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="auto_mark",
        ):
            _chunks.append(_c)
        response = clean_thinking_tags("".join(_chunks), self.binding, self.get_model())

        # Record operation history
        history = load_history()
        operation_record = {
            "id": operation_id,
            "timestamp": datetime.now().isoformat(),
            "action": "automark",
            "source": None,
            "kb_name": None,
            "input": {"original_text": text, "instruction": "AI Auto Mark"},
            "output": {"edited_text": response},
            "tool_call_file": None,
            "model": self.get_model(),
        }
        history.append(operation_record)
        save_history(history)

        self.logger.info(f"Auto-mark operation {operation_id} recorded successfully")

        return {"marked_text": response, "operation_id": operation_id}

    def _build_available_tools_text(self) -> str:
        tool_names = [name for name in self.enabled_tools if name in {"rag", "web_search"}]
        if not tool_names:
            return (
                "（当前未启用外部参考工具）"
                if str(self.language).lower().startswith("zh")
                else "(no external reference tools enabled)"
            )
        return self._tool_registry.build_prompt_text(
            tool_names,
            format="list",
            language=self.language,
        )

    def _get_source_label(self, source: Literal["rag", "web"] | None) -> str:
        labels = {
            "en": {"rag": "knowledge base", "web": "web search"},
            "zh": {"rag": "知识库", "web": "网页搜索"},
        }
        lang = "zh" if str(self.language).lower().startswith("zh") else "en"
        if source in labels[lang]:
            return labels[lang][source]
        return "reference" if lang == "en" else "参考资料"


# Legacy compatibility - export get_stats pointing to BaseAgent's stats
def get_stats():
    """Get shared stats tracker for co_writer module."""
    return BaseAgent.get_stats("co_writer")


def reset_stats():
    """Reset shared stats for co_writer module."""
    BaseAgent.reset_stats("co_writer")


def print_stats():
    """Print stats summary for co_writer module."""
    BaseAgent.print_stats("co_writer")
