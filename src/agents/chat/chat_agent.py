#!/usr/bin/env python
"""
ChatAgent - Lightweight conversational AI with multi-turn support.

This agent provides:
- Multi-turn conversation with history management
- Token-based context truncation
- Optional RAG and Web Search augmentation
- Streaming response generation

Uses the unified LLM factory from BaseAgent for both cloud and local LLM support.
"""

from pathlib import Path
import sys
from typing import Any, AsyncGenerator

# Add project root to path
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agents.base_agent import BaseAgent
from src.tools import rag_search, web_search


class ChatAgent(BaseAgent):
    """
    Lightweight conversational agent with multi-turn support.

    Features:
    - Conversation history management with token limits
    - RAG (Retrieval-Augmented Generation) support
    - Web search integration
    - Streaming response generation via BaseAgent.stream_llm()
    """

    # Default token limit for conversation history
    DEFAULT_MAX_HISTORY_TOKENS = 32000

    def __init__(
        self,
        language: str = "zh",
        config: dict[str, Any] | None = None,
        max_history_tokens: int | None = None,
        **kwargs,
    ):
        """
        Initialize ChatAgent.

        Args:
            language: Language setting ('zh' | 'en')
            config: Optional configuration dictionary
            max_history_tokens: Maximum tokens for conversation history
            **kwargs: Additional arguments passed to BaseAgent
        """
        super().__init__(
            module_name="chat",
            agent_name="chat_agent",
            language=language,
            config=config,
            **kwargs,
        )

        # Configure history token limit
        self.max_history_tokens = max_history_tokens or self.agent_config.get(
            "max_history_tokens", self.DEFAULT_MAX_HISTORY_TOKENS
        )

        self.logger.info(f"ChatAgent initialized: model={self.model}, base_url={self.base_url}")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.

        Falls back to character-based estimation if tiktoken unavailable.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        try:
            import tiktoken

            # Use cl100k_base encoding (GPT-4, GPT-3.5-turbo)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            # Fallback: rough estimate of 4 characters per token
            return len(text) // 4

    def truncate_history(
        self,
        history: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> list[dict[str, str]]:
        """
        Truncate conversation history to fit within token limit.

        Keeps the most recent messages, discarding older ones first.

        Args:
            history: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens allowed (uses default if None)

        Returns:
            Truncated history list
        """
        max_tokens = max_tokens or self.max_history_tokens

        if not history:
            return []

        # Calculate tokens for each message
        message_tokens = []
        for msg in history:
            content = msg.get("content", "")
            tokens = self.count_tokens(content)
            message_tokens.append((msg, tokens))

        # Build history from newest to oldest, stop when limit reached
        truncated = []
        total_tokens = 0

        for msg, tokens in reversed(message_tokens):
            if total_tokens + tokens > max_tokens:
                break
            truncated.insert(0, msg)
            total_tokens += tokens

        if len(truncated) < len(history):
            self.logger.info(
                f"Truncated history from {len(history)} to {len(truncated)} messages "
                f"({total_tokens} tokens)"
            )

        return truncated

    def _extract_research_reports_from_history(self, history: list[dict[str, str]]) -> str:
        """
        Extract research reports from conversation history.

        Looks for assistant messages containing research reports (marked with specific patterns).

        Args:
            history: Conversation history

        Returns:
            Extracted report content as string
        """
        reports = []
        for msg in history:
            if msg.get("role") != "assistant":
                continue

            content = msg.get("content", "")

            # Check for research report markers
            if "📚 深度研究完成" in content or "# 深度研究报告" in content:
                # Extract the report content, removing the banner
                lines = content.split("\n")
                report_lines = []
                skip_banner = False

                for line in lines:
                    # Skip the completion banner
                    if "📚 深度研究完成" in line or "深度研究完成" in line:
                        skip_banner = True
                        continue
                    if skip_banner and not line.strip():
                        skip_banner = False
                        continue
                    if not skip_banner:
                        report_lines.append(line)

                report_content = "\n".join(report_lines).strip()
                if report_content:
                    reports.append(report_content)

        if reports:
            combined = "\n\n---\n\n".join(reports)
            return f"[Conversation History - Research Reports]\n{combined}"

        return ""

    def format_history_for_prompt(self, history: list[dict[str, str]]) -> str:
        """
        Format conversation history as a string for the prompt.

        Args:
            history: List of message dicts

        Returns:
            Formatted history string
        """
        if not history:
            return ""

        lines = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content}")

        return "\n\n".join(lines)

    async def retrieve_context(
        self,
        message: str,
        kb_name: str | None = None,
        sources_kb_name: str | None = None,
        enable_rag: bool = False,
        enable_web_search: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """
        Retrieve context from RAG and/or Web Search.

        Args:
            message: User message to search for
            kb_name: Knowledge base name for RAG
            sources_kb_name: Knowledge base name for selected sources
            enable_rag: Whether to use RAG
            enable_web_search: Whether to use Web Search

        Returns:
            Tuple of (context_string, sources_dict)
        """
        context_parts = []
        sources = {"rag": [], "web": []}

        # RAG retrieval
        if enable_rag and kb_name:
            try:
                self.logger.info(f"RAG search: {message[:50]}...")
                rag_result = await rag_search(
                    query=message,
                    kb_name=kb_name,
                    mode="hybrid",
                )
                rag_answer = rag_result.get("answer", "")
                if rag_answer:
                    context_parts.append(f"[Knowledge Base: {kb_name}]\n{rag_answer}")
                    sources["rag"].append(
                        {
                            "kb_name": kb_name,
                            "content": rag_answer[:500] + "..."
                            if len(rag_answer) > 500
                            else rag_answer,
                        }
                    )
                    self.logger.info(f"RAG retrieved {len(rag_answer)} chars")
            except Exception as e:
                self.logger.warning(f"RAG search failed: {e}")

        # Selected sources KB retrieval (always-on if provided)
        if sources_kb_name and sources_kb_name != kb_name:
            try:
                self.logger.info(f"Sources KB search: {message[:50]}...")
                sources_result = await rag_search(
                    query=message,
                    kb_name=sources_kb_name,
                    mode="hybrid",
                )
                sources_answer = sources_result.get("answer", "")
                if sources_answer:
                    context_parts.append(f"[Selected Sources]\n{sources_answer}")
                    sources["rag"].append(
                        {
                            "kb_name": sources_kb_name,
                            "content": sources_answer[:500] + "..."
                            if len(sources_answer) > 500
                            else sources_answer,
                        }
                    )
                    self.logger.info(f"Sources KB retrieved {len(sources_answer)} chars")
            except Exception as e:
                self.logger.warning(f"Sources KB search failed: {e}")

        # Web search
        if enable_web_search:
            try:
                self.logger.info(f"Web search: {message[:50]}...")
                web_result = web_search(query=message, verbose=False)
                web_answer = web_result.get("answer", "")
                web_citations = web_result.get("citations", [])

                if web_answer:
                    context_parts.append(f"[Web Search Results]\n{web_answer}")
                    sources["web"] = web_citations[:5]
                    self.logger.info(
                        f"Web search returned {len(web_answer)} chars, "
                        f"{len(web_citations)} citations"
                    )
                elif web_citations:
                    # Fallback for providers that don't return an 'answer' (like volcengine)
                    # Construct a combined context from snippets
                    self.logger.info(f"Web search answer empty, using {len(web_citations)} citations as context")
                    snippet_parts = []
                    for i, cit in enumerate(web_citations[:10], 1):
                        snippet = cit.get("snippet", "")
                        title = cit.get("title", "")
                        if snippet:
                            snippet_parts.append(f"Source [{i}] ({title}): {snippet}")
                    
                    if snippet_parts:
                        combined_snippets = "\n\n".join(snippet_parts)
                        context_parts.append(f"[Web Search Results (Snippets)]\n{combined_snippets}")
                        sources["web"] = web_citations[:5]
                        self.logger.info(f"Combined {len(snippet_parts)} snippets into context ({len(combined_snippets)} chars)")
            except Exception as e:
                self.logger.warning(f"Web search failed: {e}")

        context = "\n\n".join(context_parts)
        return context, sources

    def build_messages(
        self,
        message: str,
        history: list[dict[str, str]],
        context: str = "",
        enable_rag: bool = False,
        enable_web_search: bool = False,
        require_sources: bool = False,
    ) -> list[dict[str, str]]:
        """
        Build the messages array for the LLM API call.

        Args:
            message: Current user message
            history: Truncated conversation history
            context: Retrieved context (RAG/Web)
            enable_rag: Whether RAG is enabled
            enable_web_search: Whether Web Search is enabled
            require_sources: Whether to enforce strict grounded QA (notebook mode)

        Returns:
            List of message dicts for OpenAI API
        """
        messages = []

        # Select system prompt based on mode
        if require_sources:
            # Notebook mode: use notebook-specific system prompt
            base_system_prompt = self.get_prompt("notebook_system", "You are a knowledgeable AI assistant.")
        else:
            # Chat mode: use open chat system prompt
            base_system_prompt = self.get_prompt("system", "You are a knowledgeable AI assistant.")

        instructions = []
        if context:
            if require_sources:
                # Notebook mode: strict grounded QA — only answer from provided sources
                instructions.append("Answer the user's question based STRICTLY on the provided Reference Information.")
                instructions.append("Do NOT use your own internal knowledge to answer. You must only use the information present in the Reference Information.")
                instructions.append("If the answer is not found in the Reference Information, explicitly state that you cannot find the answer in the provided sources.")
            else:
                # Chat mode: use context as supplementary reference, not as strict constraint
                instructions.append("Reference Information is provided below for your consideration.")
                instructions.append("Use it to enhance your answer, but you may also draw on your own knowledge to provide a comprehensive response.")
                instructions.append("If the Reference Information is relevant, incorporate and cite it; if not, feel free to answer based on your own knowledge.")

            if enable_web_search:
                instructions.append("The Reference Information contains Web Search Results.")
                instructions.append("Please summarize these search results to provide a comprehensive and readable answer.")
                instructions.append("Do not just list links; synthesize the information.")

        # Combine instructions
        if instructions:
            system_prompt = f"{base_system_prompt}\n\nInstructions:\n" + "\n".join(f"- {i}" for i in instructions)
        else:
            system_prompt = base_system_prompt

        messages.append({"role": "system", "content": system_prompt})

        # Add context if available
        if context:
            context_template = self.get_prompt("context_template", "Reference Information:\n{context}")
            context_msg = context_template.format(context=context)
            messages.append({"role": "system", "content": context_msg})

        # Add conversation history
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message})

        return messages

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming response from LLM.

        Uses BaseAgent.stream_llm() which routes to the appropriate provider
        (cloud or local) based on configuration.

        Args:
            messages: Messages array for OpenAI API

        Yields:
            Response chunks as strings
        """
        # Extract system prompt from messages
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        # Get the last user message as user_prompt (for logging/tracking)
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break

        # Use BaseAgent's stream_llm which routes through the factory
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            messages=messages,
            stage="chat_stream",
        ):
            yield chunk

    async def generate(self, messages: list[dict[str, str]]) -> str:
        """
        Generate complete response from LLM (non-streaming).

        Uses BaseAgent.call_llm() which routes to the appropriate provider
        (cloud or local) based on configuration.

        Args:
            messages: Messages array for OpenAI API

        Returns:
            Complete response string
        """
        # Extract system prompt from messages
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                break

        # Get the last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_prompt = msg.get("content", "")
                break

        # Use BaseAgent's call_llm which routes through the factory
        # Note: call_llm expects simple prompt/system_prompt, but for multi-turn
        # we need to use the factory directly with messages
        from src.services.llm import complete as llm_complete

        response = await llm_complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=self.get_model(),
            api_key=self.api_key,
            base_url=self.base_url,
            messages=messages,
            temperature=self.get_temperature(),
        )

        # Track token usage
        self._track_tokens(
            model=self.get_model(),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            stage="chat",
        )

        return response

    async def process(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        kb_name: str | None = None,
        sources_kb_name: str | None = None,
        enable_rag: bool = False,
        enable_web_search: bool = False,
        require_sources: bool = False,
        stream: bool = False,
    ) -> dict[str, Any] | AsyncGenerator[dict[str, Any], None]:
        """
        Process a chat message with optional context retrieval.

        Args:
            message: User message
            history: Conversation history (will be truncated if needed)
            kb_name: Knowledge base name for RAG
            sources_kb_name: Knowledge base name for selected sources
            enable_rag: Whether to enable RAG retrieval
            enable_web_search: Whether to enable web search
            require_sources: Whether to require sources before answering
            stream: Whether to stream the response

        Returns:
            If stream=False: Dict with 'response', 'sources', 'truncated_history'
            If stream=True: AsyncGenerator yielding chunks
        """
        history = history or []

        # Truncate history to fit token limit
        truncated_history = self.truncate_history(history)

        # Retrieve context if needed
        context, sources = await self.retrieve_context(
            message=message,
            kb_name=kb_name,
            sources_kb_name=sources_kb_name,
            enable_rag=enable_rag,
            enable_web_search=enable_web_search,
        )

        # Extract research reports from conversation history if available
        history_context = self._extract_research_reports_from_history(truncated_history)
        if history_context:
            if context:
                context = f"{context}\n\n{history_context}"
            else:
                context = history_context
            self.logger.info(f"Added {len(history_context)} chars from conversation history reports")

        # Check if we should fail without sources
        # Now we're more lenient: allow answering based on conversation history
        if require_sources and not context.strip():
            self.logger.warning(
                f"No context found for query (kb_name={kb_name}, sources_kb_name={sources_kb_name})"
            )
            fallback = "未在已选来源或知识库中找到相关信息。"
            if stream:
                async def stream_generator():
                    yield {
                        "type": "complete",
                        "response": fallback,
                        "sources": sources,
                        "truncated_history": truncated_history,
                    }

                return stream_generator()
            return {
                "response": fallback,
                "sources": sources,
                "truncated_history": truncated_history,
            }

        # Build messages for LLM
        messages = self.build_messages(
            message=message,
            history=truncated_history,
            context=context,
            enable_rag=enable_rag,
            enable_web_search=enable_web_search,
            require_sources=require_sources,
        )

        if stream:
            # Return async generator for streaming
            async def stream_generator():
                full_response = ""
                async for chunk in self.generate_stream(messages):
                    full_response += chunk
                    yield {"type": "chunk", "content": chunk}

                # Yield final result with sources
                yield {
                    "type": "complete",
                    "response": full_response,
                    "sources": sources,
                    "truncated_history": truncated_history,
                }

            return stream_generator()
        else:
            # Generate complete response
            response = await self.generate(messages)

            return {
                "response": response,
                "sources": sources,
                "truncated_history": truncated_history,
            }


__all__ = ["ChatAgent"]
