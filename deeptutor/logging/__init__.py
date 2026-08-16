"""DeepTutor Logging 2.0: stdlib core plus structured process-log events."""

from .config import LoggingConfig, get_default_log_dir, get_global_log_level, load_logging_config
from .configure import configure_logging
from .context import LOG_CONTEXT_FIELDS, bind_log_context, current_log_context
from .process_stream import PROCESS_LOG_PRIVATE_ATTR, ProcessLogEvent, capture_process_logs
from .stats import MODEL_PRICING, LLMCall, LLMStats, estimate_tokens, get_pricing

__all__ = [
    "LOG_CONTEXT_FIELDS",
    "LoggingConfig",
    "configure_logging",
    "bind_log_context",
    "current_log_context",
    "PROCESS_LOG_PRIVATE_ATTR",
    "capture_process_logs",
    "ProcessLogEvent",
    "LLMStats",
    "LLMCall",
    "MODEL_PRICING",
    "estimate_tokens",
    "get_pricing",
    "load_logging_config",
    "get_default_log_dir",
    "get_global_log_level",
]
