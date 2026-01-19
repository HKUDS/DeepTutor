# -*- coding: utf-8 -*-
"""
LLM Telemetry
=============

Basic telemetry tracking for LLM calls.
"""

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def track_llm_call(provider_name: str):
    """
    Decorator to track LLM calls for telemetry.

    Args:
        provider_name: Name of the provider being called

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            logger.debug(f"LLM call to {provider_name}: {func.__name__}")
            try:
                result = await func(*args, **kwargs)
                logger.debug(f"LLM call to {provider_name} completed successfully")
                return result
            except Exception as e:
                logger.warning(f"LLM call to {provider_name} failed: {e}")
                raise

        return wrapper

    return decorator
