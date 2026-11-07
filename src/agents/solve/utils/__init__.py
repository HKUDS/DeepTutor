"""
Utility module for the solve agent.
"""

from pathlib import Path
import sys

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.logging import Logger, LogLevel, get_logger, reset_logger

# Backwards compatibility alias used by API layer
SolveAgentLogger = Logger

# Token tracker
from .token_tracker import TokenTracker, calculate_cost, get_model_pricing

__all__ = [
    # Logging
    "Logger",
    "get_logger",
    "reset_logger",
    "LogLevel",
    "SolveAgentLogger",
    # Token tracker
    "TokenTracker",
    "calculate_cost",
    "get_model_pricing",
]
