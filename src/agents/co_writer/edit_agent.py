"""
EditAgent - Co-writer editing agent.
Uses unified PromptManager for prompt loading.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any, Literal
import uuid

# Add project root for imports
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.logging import LLMStats, get_logger
from src.services.storage.history_store import list_history, upsert_history_item
from src.services.config import get_agent_params, load_config_with_main
from src.services.llm import complete as llm_complete
from src.services.llm import get_llm_config
from src.services.prompt import get_prompt_manager
from src.tools.rag_tool import rag_search
from src.tools.web_search import web_search

# Initialize logger with config
try:
    config = load_config_with_main(
        "solve_config.yaml", _project_root
    )  # Use any config to get main.yaml
    log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get(
        "log_dir"
    )
    logger = get_logger("CoWriter", log_dir=log_dir)
except Exception:
    # Fallback to standard logging
    logger = logging.getLogger(__name__)

# Shared stats tracker for co_writer
_co_writer_stats: LLMStats | None = None


def get_stats() -> LLMStats:
    """Get or create shared stats tracker."""
    global _co_writer_stats
    if _co_writer_stats is None:
        _co_writer_stats = LLMStats(module_name="CoWriter")
    return _co_writer_stats


def reset_stats():
    """Reset shared stats."""
    global _co_writer_stats
    if _co_writer_stats:
        _co_writer_stats.reset()


def print_stats():
    """Print stats summary."""
    global _co_writer_stats
    if _co_writer_stats:
        _co_writer_stats.print_summary()


USER_DIR = Path(__file__).parent.parent.parent.parent / "data" / "user" / "co-writer"
TOOL_CALLS_DIR = USER_DIR / "tool_calls"


def ensure_dirs():
    """Ensure directories exist"""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    TOOL_CALLS_DIR.mkdir(parents=True, exist_ok=True)


def load_history() -> list:
    """Load history"""
    ensure_dirs()
    return list_history()


def save_history(history: list):
    """Save history"""
    ensure_dirs()
    for item in history:
        upsert_history_item(item)


def save_tool_call(call_id: str, tool_type: str, data: dict[str, Any]) -> str:
    """Save tool call result, return file path"""
    ensure_dirs()
    filename = f"{call_id}_{tool_type}.json"
    filepath = TOOL_CALLS_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(filepath)


class EditAgent:
    def __init__(self, language: str = "en"):
        # Load agent parameters from unified config (agents.yaml)
        self._agent_params = get_agent_params("co_writer")
        self.language = language

        # Load prompts using unified PromptManager
        self._prompts = get_prompt_manager().load_prompts(
            module_name="co_writer",
            agent_name="edit_agent",
            language=language,
        )

        try:
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to load LLM config: {e}")
            self.llm_config = None

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
        # Always refresh LLM config before starting to avoid stale credentials
        try:
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to refresh LLM config: {e}")

        if not self.llm_config:
            raise ValueError("LLM configuration not available")

        operation_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

        context = ""
        tool_call_file = None
        tool_call_data = None

        if source == "rag":
            if not kb_name:
                logger.warning("RAG source selected but no kb_name provided, skipping RAG search")
                source = None
            else:
                logger.info(f"Searching RAG in KB: {kb_name} for: {instruction}")
                try:
                    search_result = await rag_search(
                        query=instruction, kb_name=kb_name, mode="naive", only_need_context=True
                    )
                    context = search_result.get("answer", "")
                    logger.info(f"RAG context found: {len(context)} chars")

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
                    logger.error(f"RAG search failed: {e}, continuing without context")
                    source = None

        elif source == "web":
            logger.info(f"Searching Web for: {instruction}")
            try:
                search_result = web_search(instruction)
                context = search_result.get("answer", "")
                logger.info(f"Web context found: {len(context)} chars")

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
                logger.error(f"Web search failed: {e}, continuing without context")
                source = None

        # 2. Construct Prompt
        system_prompt = self._prompts.get(
            "system", "You are an expert editor and writing assistant."
        )

        action_verbs = {"rewrite": "Rewrite", "shorten": "Shorten", "expand": "Expand"}
        action_verb = action_verbs.get(action, "Rewrite")

        action_template = self._prompts.get(
            "action_template",
            "{action_verb} the following text based on the user's instruction.\n\nUser Instruction: {instruction}\n\n",
        )
        user_prompt = action_template.format(action_verb=action_verb, instruction=instruction)

        if context:
            context_template = self._prompts.get(
                "context_template", "Reference Context:\n{context}\n\n"
            )
            user_prompt += context_template.format(context=context)

        text_template = self._prompts.get(
            "user_template",
            "Target Text to Edit:\n{text}\n\nOutput only the edited text, without quotes or explanations.",
        )
        user_prompt += text_template.format(text=text)

        # 3. Call LLM
        logger.info(f"Calling LLM for {action}...")
        model = self.llm_config.model
        response = await llm_complete(
            binding=self.llm_config.binding,
            model=model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
            temperature=self._agent_params["temperature"],
            max_tokens=self._agent_params["max_tokens"],
        )

        # Track token usage
        stats = get_stats()
        stats.add_call(
            model=model, system_prompt=system_prompt, user_prompt=user_prompt, response=response
        )

        # 4. Record operation history
        operation_record = {
            "id": operation_id,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "source": source,
            "kb_name": kb_name,
            "input": {"original_text": text, "instruction": instruction},
            "output": {"edited_text": response},
            "tool_call_file": tool_call_file,
            "model": self.llm_config.model,
        }
        upsert_history_item(operation_record)

        logger.info(f"Operation {operation_id} recorded successfully")

        return {"edited_text": response, "operation_id": operation_id}

    async def auto_mark(self, text: str) -> dict[str, Any]:
        """
        AI auto-marking feature - Add annotation tags to text

        Returns:
            Dict containing:
                - marked_text: Text with annotations
                - operation_id: Operation ID
        """
        # Always refresh LLM config before starting to avoid stale credentials
        try:
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to refresh LLM config: {e}")

        if not self.llm_config:
            raise ValueError("LLM configuration not available")

        operation_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

        system_prompt = self._prompts.get("auto_mark_system", "")
        user_template = self._prompts.get(
            "auto_mark_user_template", "Process the following text:\n{text}"
        )
        user_prompt = user_template.format(text=text)

        logger.info("Calling LLM for auto-mark...")
        model = self.llm_config.model
        response = await llm_complete(
            binding=self.llm_config.binding,
            model=model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
            temperature=self._agent_params["temperature"],
            max_tokens=self._agent_params["max_tokens"],
        )

        # Track token usage
        stats = get_stats()
        stats.add_call(
            model=model, system_prompt=system_prompt, user_prompt=user_prompt, response=response
        )

        # Record operation history
        operation_record = {
            "id": operation_id,
            "timestamp": datetime.now().isoformat(),
            "action": "automark",
            "source": None,
            "kb_name": None,
            "input": {"original_text": text, "instruction": "AI Auto Mark"},
            "output": {"edited_text": response},
            "tool_call_file": None,
            "model": self.llm_config.model,
        }
        upsert_history_item(operation_record)

        logger.info(f"Auto-mark operation {operation_id} recorded successfully")

        return {"marked_text": response, "operation_id": operation_id}
