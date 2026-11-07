# -*- coding: utf-8 -*-
"""
Session Management Module
=========================

Provides unified session management for all agent modules.

Usage:
    from src.services.session import BaseSessionManager
    
    class MySessionManager(BaseSessionManager):
        def __init__(self):
            super().__init__("my_module")
        
        def _get_session_id_prefix(self) -> str:
            return "my_"
        
        def _get_default_title(self) -> str:
            return "New My Session"
        
        # ... implement other abstract methods
"""

from .base_session_manager import BaseSessionManager

__all__ = ["BaseSessionManager"]
