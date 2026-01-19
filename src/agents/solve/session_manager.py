#!/usr/bin/env python
"""
SolverSessionManager - Solver session persistence and management.

This module handles:
- Creating new solver sessions
- Updating sessions with new messages
- Retrieving session history
- Listing recent sessions
- Deleting sessions
"""

import json
from pathlib import Path
import time
from typing import Any
import uuid


class SolverSessionManager:
    """
    Manages persistent storage of solver sessions.

    Sessions are stored in a JSON file at data/user/solver_sessions.json.
    Each session contains:
    - session_id: Unique identifier
    - title: Session title (usually first user question)
    - messages: List of messages with role, content, outputDir, timestamp
    - kb_name: Knowledge base used
    - token_stats: Cost and token usage statistics
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    """

    def __init__(self, base_dir: str | None = None):
        """
        Initialize SolverSessionManager.

        Args:
            base_dir: Base directory for session storage.
                     Defaults to project_root/data/user
        """
        if base_dir is None:
            # Current file: src/agents/solve/session_manager.py
            # Project root: 4 levels up
            project_root = Path(__file__).resolve().parents[3]
            base_dir_path = project_root / "data" / "user"
        else:
            base_dir_path = Path(base_dir)

        self.base_dir = base_dir_path
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.sessions_file = self.base_dir / "solver_sessions.json"
        self._ensure_file()

    def _ensure_file(self):
        """Ensure the sessions file exists with correct format."""
        if not self.sessions_file.exists():
            initial_data = {
                "version": "1.0",
                "sessions": [],
            }
            self._save_data(initial_data)

    def _load_data(self) -> dict[str, Any]:
        """Load sessions data from file."""
        try:
            with open(self.sessions_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"version": "1.0", "sessions": []}

    def _save_data(self, data: dict[str, Any]):
        """Save sessions data to file."""
        with open(self.sessions_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _get_sessions(self) -> list[dict[str, Any]]:
        """Get list of all sessions."""
        data = self._load_data()
        return data.get("sessions", [])

    def _save_sessions(self, sessions: list[dict[str, Any]]):
        """Save sessions list."""
        data = self._load_data()
        data["sessions"] = sessions
        self._save_data(data)

    def create_session(
        self,
        title: str = "New Solver Session",
        kb_name: str = "",
        token_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new solver session.

        Args:
            title: Session title
            kb_name: Knowledge base name
            token_stats: Optional token usage statistics

        Returns:
            New session dict with session_id
        """
        session_id = f"solver_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        now = time.time()

        session = {
            "session_id": session_id,
            "title": title[:100],  # Limit title length
            "messages": [],
            "kb_name": kb_name,
            "token_stats": token_stats or {
                "model": "Unknown",
                "calls": 0,
                "tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
            },
            "created_at": now,
            "updated_at": now,
        }

        sessions = self._get_sessions()
        sessions.insert(0, session)  # Add to front (newest first)

        # Limit total sessions to prevent file bloat
        max_sessions = 100
        if len(sessions) > max_sessions:
            sessions = sessions[:max_sessions]

        self._save_sessions(sessions)

        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Get a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session dict or None if not found
        """
        sessions = self._get_sessions()
        for session in sessions:
            if session.get("session_id") == session_id:
                return session
        return None

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
        sessions = self._get_sessions()

        for i, session in enumerate(sessions):
            if session.get("session_id") == session_id:
                if messages is not None:
                    session["messages"] = messages
                if title is not None:
                    session["title"] = title[:100]
                if kb_name is not None:
                    session["kb_name"] = kb_name
                if token_stats is not None:
                    session["token_stats"] = token_stats

                session["updated_at"] = time.time()

                # Move to front (most recently updated)
                sessions.pop(i)
                sessions.insert(0, session)

                self._save_sessions(sessions)
                return session

        return None

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
        session = self.get_session(session_id)
        if not session:
            return None

        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        if output_dir:
            message["output_dir"] = output_dir

        messages = session.get("messages", [])
        messages.append(message)

        # Update title from first user message if still default
        if session.get("title") == "New Solver Session" and role == "user":
            new_title = content[:50] + ("..." if len(content) > 50 else "")
            return self.update_session(session_id, messages=messages, title=new_title)

        return self.update_session(session_id, messages=messages)

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

    def list_sessions(
        self,
        limit: int = 20,
        include_messages: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List recent sessions.

        Args:
            limit: Maximum number of sessions to return
            include_messages: Whether to include full message history

        Returns:
            List of session dicts (newest first)
        """
        sessions = self._get_sessions()[:limit]

        if not include_messages:
            # Return summary only (without full messages)
            return [
                {
                    "session_id": s.get("session_id"),
                    "title": s.get("title"),
                    "message_count": len(s.get("messages", [])),
                    "kb_name": s.get("kb_name"),
                    "token_stats": s.get("token_stats"),
                    "created_at": s.get("created_at"),
                    "updated_at": s.get("updated_at"),
                    # Include preview of last message
                    "last_message": (
                        s.get("messages", [])[-1].get("content", "")[:100]
                        if s.get("messages")
                        else ""
                    ),
                }
                for s in sessions
            ]

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        sessions = self._get_sessions()
        original_count = len(sessions)

        sessions = [s for s in sessions if s.get("session_id") != session_id]

        if len(sessions) < original_count:
            self._save_sessions(sessions)
            return True

        return False

    def clear_all_sessions(self) -> int:
        """
        Delete all sessions.

        Returns:
            Number of sessions deleted
        """
        sessions = self._get_sessions()
        count = len(sessions)
        self._save_sessions([])
        return count


# Singleton instance for convenience
_solver_session_manager: SolverSessionManager | None = None


def get_solver_session_manager() -> SolverSessionManager:
    """Get or create the global SolverSessionManager instance."""
    global _solver_session_manager
    if _solver_session_manager is None:
        _solver_session_manager = SolverSessionManager()
    return _solver_session_manager


__all__ = ["SolverSessionManager", "get_solver_session_manager"]
