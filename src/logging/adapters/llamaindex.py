#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LlamaIndex Log Forwarder
========================

Forwards LlamaIndex logs to DeepTutor's unified logging system.
"""

from contextlib import contextmanager
import logging
from typing import Any, Dict, List, Optional, Tuple


class LlamaIndexLogForwarder(logging.Handler):
    """
    Handler that forwards LlamaIndex logger messages to DeepTutor logger.
    """

    def __init__(self, ai_tutor_logger, add_prefix: bool = True):
        """
        Args:
            ai_tutor_logger: DeepTutor Logger instance
            add_prefix: Whether to add prefix to messages
        """
        super().__init__()
        self.ai_tutor_logger = ai_tutor_logger
        self.add_prefix = add_prefix
        # Capture all log levels
        self.setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord):
        """
        Forward log record to DeepTutor logger.
        """
        try:
            message = record.getMessage()

            # Map log levels
            level = record.levelno
            if level >= logging.ERROR:
                self.ai_tutor_logger.error(message)
            elif level >= logging.WARNING:
                self.ai_tutor_logger.warning(message)
            elif level >= logging.INFO:
                self.ai_tutor_logger.info(message)
            else:
                self.ai_tutor_logger.debug(message)

        except Exception:
            self.handleError(record)


@contextmanager
def LlamaIndexLogContext(
    logger_name: Optional[str] = None,
    scene: str = "llamaindex",
    min_level: str = "INFO",
):
    """
    Context manager for LlamaIndex log forwarding.

    Automatically sets up and tears down log forwarding.

    Args:
        logger_name: Explicit logger name (defaults to scene name)
        scene: Scene name for logger identification
        min_level: Minimum log level to forward

    Usage:
        with LlamaIndexLogContext("VectorSearch"):
            # LlamaIndex operations
            index.query(query)
    """
    from ..logger import get_logger

    # Determine logger name
    if logger_name is None:
        logger_name = scene.title().replace("_", "")

    # Get DeepTutor logger
    ai_tutor_logger = get_logger(logger_name)

    # Get LlamaIndex loggers
    llama_loggers = [
        logging.getLogger("llama_index"),
        logging.getLogger("llama_index.core"),
        logging.getLogger("llama_index.vector_stores"),
        logging.getLogger("llama_index.embeddings"),
    ]

    # Parse min level
    min_level_int = getattr(logging, min_level.upper(), logging.INFO)

    # Store original state
    original_states: List[Dict[str, Any]] = []
    forwarders: List[Tuple[logging.Logger, LlamaIndexLogForwarder]] = []

    for llama_logger in llama_loggers:
        original_states.append(
            {
                "logger": llama_logger,
                "handlers": llama_logger.handlers[:],
                "level": llama_logger.level,
            }
        )

        # Temporarily remove console handlers
        console_handlers_to_remove = []
        for handler in llama_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                console_handlers_to_remove.append(handler)

        for handler in console_handlers_to_remove:
            llama_logger.removeHandler(handler)

        # Set level
        if llama_logger.level > logging.DEBUG:
            llama_logger.setLevel(logging.DEBUG)

        # Add forwarder
        forwarder = LlamaIndexLogForwarder(ai_tutor_logger)
        forwarder.setLevel(min_level_int)
        llama_logger.addHandler(forwarder)
        forwarders.append((llama_logger, forwarder))

    try:
        yield
    finally:
        # Clean up forwarders
        for llama_logger, forwarder in forwarders:
            if forwarder in llama_logger.handlers:
                llama_logger.removeHandler(forwarder)
                forwarder.close()

        # Restore original state
        for state in original_states:
            llama_logger = state["logger"]
            # Restore handlers that were removed
            for handler in state["handlers"]:
                if handler not in llama_logger.handlers:
                    llama_logger.addHandler(handler)
