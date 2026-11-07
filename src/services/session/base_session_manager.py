#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BaseSessionManager - Unified session management base class.

This module provides a base class for managing persistent sessions
across different agent modules (solve, chat, etc.).

Features:
- Consistent JSON storage format
- Session CRUD operations
- Message management within sessions
- Automatic session ordering (newest first)
- Configurable session limits
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.services.path_service import get_path_service


class BaseSessionManager(ABC):
    """
    Abstract base class for session management.
    
    Provides common functionality for storing and retrieving sessions,
    with customization points for module-specific behavior.
    
    Subclasses must implement:
    - _get_session_id_prefix(): Return the session ID prefix (e.g., "solve_", "chat_")
    - _get_default_title(): Return the default title for new sessions
    - _create_session_data(): Create module-specific session data structure
    - _get_session_summary(): Create module-specific session summary for listing
    """
    
    MAX_SESSIONS = 100  # Maximum number of sessions to keep
    
    def __init__(self, module_name: str):
        """
        Initialize the session manager.
        
        Args:
            module_name: The module name (e.g., "solve", "chat")
                        Used to determine the session file path.
        """
        self.module_name = module_name
        self.path_service = get_path_service()
        self.sessions_file = self.path_service.get_session_file(module_name)
        self._ensure_file()
    
    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================
    
    @abstractmethod
    def _get_session_id_prefix(self) -> str:
        """
        Return the prefix for session IDs.
        
        Example: "solve_" -> session IDs like "solve_1234567890_abc123"
        """
        pass
    
    @abstractmethod
    def _get_default_title(self) -> str:
        """
        Return the default title for new sessions.
        
        Example: "New Solver Session" or "New Chat"
        """
        pass
    
    @abstractmethod
    def _create_session_data(self, **kwargs) -> dict[str, Any]:
        """
        Create the initial session data structure.
        
        Args:
            **kwargs: Module-specific parameters
        
        Returns:
            Dict containing module-specific session fields
            (should NOT include session_id, title, messages, created_at, updated_at
             as those are added by create_session())
        """
        pass
    
    @abstractmethod
    def _get_session_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        """
        Create a summary of a session for listing.
        
        Args:
            session: The full session data
        
        Returns:
            Dict containing summary fields for list display
            (should include session_id, title, message_count, created_at, updated_at,
             last_message, plus any module-specific fields)
        """
        pass
    
    # =========================================================================
    # File Operations
    # =========================================================================
    
    def _ensure_file(self) -> None:
        """Ensure the sessions file exists with correct format."""
        # Ensure directory exists
        self.sessions_file.parent.mkdir(parents=True, exist_ok=True)
        
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
    
    def _save_data(self, data: dict[str, Any]) -> None:
        """Save sessions data to file."""
        with open(self.sessions_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _get_sessions(self) -> list[dict[str, Any]]:
        """Get list of all sessions."""
        data = self._load_data()
        return data.get("sessions", [])
    
    def _save_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Save sessions list."""
        data = self._load_data()
        data["sessions"] = sessions
        self._save_data(data)
    
    # =========================================================================
    # Session CRUD Operations
    # =========================================================================
    
    def create_session(
        self,
        title: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Create a new session.
        
        Args:
            title: Session title (uses default if None)
            **kwargs: Module-specific parameters passed to _create_session_data()
        
        Returns:
            New session dict with session_id
        """
        prefix = self._get_session_id_prefix()
        session_id = f"{prefix}{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        now = time.time()
        
        # Use provided title or default
        if title is None:
            title = self._get_default_title()
        
        # Create base session structure
        session = {
            "session_id": session_id,
            "title": title[:100] if title else self._get_default_title(),  # Limit title length
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        
        # Add module-specific data
        module_data = self._create_session_data(**kwargs)
        session.update(module_data)
        
        # Add to sessions list
        sessions = self._get_sessions()
        sessions.insert(0, session)  # Add to front (newest first)
        
        # Limit total sessions
        if len(sessions) > self.MAX_SESSIONS:
            sessions = sessions[:self.MAX_SESSIONS]
        
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
        **kwargs,
    ) -> dict[str, Any] | None:
        """
        Update a session with new data.
        
        Args:
            session_id: Session identifier
            messages: New messages list (replaces existing)
            title: New title (optional)
            **kwargs: Module-specific fields to update
        
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
                
                # Update module-specific fields
                for key, value in kwargs.items():
                    if value is not None:
                        session[key] = value
                
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
        **metadata,
    ) -> dict[str, Any] | None:
        """
        Add a single message to a session.
        
        Args:
            session_id: Session identifier
            role: Message role ('user' or 'assistant')
            content: Message content
            **metadata: Additional message metadata (e.g., sources, output_dir)
        
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
        
        # Add any additional metadata
        for key, value in metadata.items():
            if value is not None:
                message[key] = value
        
        messages = session.get("messages", [])
        messages.append(message)
        
        # Update title from first user message if still default
        title = None
        if session.get("title") == self._get_default_title() and role == "user":
            title = content[:50] + ("..." if len(content) > 50 else "")
        
        return self.update_session(session_id, messages=messages, title=title)
    
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
            return [self._get_session_summary(s) for s in sessions]
        
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
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_session_count(self) -> int:
        """Get the total number of sessions."""
        return len(self._get_sessions())
    
    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        return self.get_session(session_id) is not None


__all__ = ["BaseSessionManager"]
