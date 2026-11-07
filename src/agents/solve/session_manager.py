#!/usr/bin/env python
"""
SolverSessionManager - Solver session persistence and management.

This module handles:
- Creating new solver sessions
- Updating sessions with new messages
- Retrieving session history
- Listing recent sessions
- Deleting sessions

Now inherits from BaseSessionManager for consistent behavior across all modules.
"""

from typing import Any

from src.services.session import BaseSessionManager


class SolverSessionManager(BaseSessionManager):
    """
    Manages persistent storage of solver sessions.

    Sessions are stored in a JSON file at data/user/agent/solve/sessions.json.
    Each session contains:
    - session_id: Unique identifier
    - title: Session title (usually first user question)
    - messages: List of messages with role, content, output_dir, timestamp
    - kb_name: Knowledge base used
    - token_stats: Cost and token usage statistics
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    """

    DEFAULT_TOKEN_STATS = {
        "model": "Unknown",
        "calls": 0,
        "tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0,
    }

    def __init__(self):
        """Initialize SolverSessionManager."""
        super().__init__("solve")

    # =========================================================================
    # BaseSessionManager Abstract Method Implementations
    # =========================================================================

    def _get_session_id_prefix(self) -> str:
        """Return the prefix for session IDs."""
        return "solve_"

    def _get_default_title(self) -> str:
        """Return the default title for new sessions."""
        return "New Solver Session"

    def _create_session_data(
        self,
        kb_name: str = "",
        token_stats: dict[str, Any] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Create solver-specific session data.

        Args:
            kb_name: Knowledge base name
            token_stats: Token usage statistics

        Returns:
            Dict with kb_name and token_stats
        """
        return {
            "kb_name": kb_name,
            "token_stats": token_stats or self.DEFAULT_TOKEN_STATS.copy(),
        }

    def _get_session_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        """
        Create a summary of a solver session for listing.

        Args:
            session: The full session data

        Returns:
            Dict containing summary fields
        """
        messages = session.get("messages", [])
        return {
            "session_id": session.get("session_id"),
            "title": session.get("title"),
            "message_count": len(messages),
            "kb_name": session.get("kb_name"),
            "token_stats": session.get("token_stats"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            # Include preview of last message
            "last_message": (
                messages[-1].get("content", "")[:100] if messages else ""
            ),
        }

    # =========================================================================
    # Solver-Specific Methods
    # =========================================================================

    def create_session(
        self,
        title: str | None = None,
        kb_name: str = "",
        token_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new solver session.

        Args:
            title: Session title (uses default if None)
            kb_name: Knowledge base name
            token_stats: Optional token usage statistics

        Returns:
            New session dict with session_id
        """
        return super().create_session(
            title=title,
            kb_name=kb_name,
            token_stats=token_stats,
        )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        output_dir: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Add a single message to a session.

        Args:
            session_id: Session identifier
            role: Message role ('user' or 'assistant')
            content: Message content
            output_dir: Optional output directory (for assistant messages)

        Returns:
            Updated session or None if not found
        """
        return super().add_message(
            session_id=session_id,
            role=role,
            content=content,
            output_dir=output_dir,
        )

    def update_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]] | None = None,
        title: str | None = None,
        kb_name: str | None = None,
        token_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Update a session with new data.

        Args:
            session_id: Session identifier
            messages: New messages list (replaces existing)
            title: New title (optional)
            kb_name: New knowledge base name (optional)
            token_stats: New token stats (optional)

        Returns:
            Updated session or None if not found
        """
        return super().update_session(
            session_id=session_id,
            messages=messages,
            title=title,
            kb_name=kb_name,
            token_stats=token_stats,
        )

    def update_token_stats(
        self,
        session_id: str,
        token_stats: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Update token stats for a session.

        Args:
            session_id: Session identifier
            token_stats: Token usage statistics

        Returns:
            Updated session or None if not found
        """
        return self.update_session(session_id, token_stats=token_stats)


# Singleton instance for convenience
_solver_session_manager: SolverSessionManager | None = None


def get_solver_session_manager() -> SolverSessionManager:
    """Get or create the global SolverSessionManager instance."""
    global _solver_session_manager
    if _solver_session_manager is None:
        _solver_session_manager = SolverSessionManager()
    return _solver_session_manager


__all__ = ["SolverSessionManager", "get_solver_session_manager"]
