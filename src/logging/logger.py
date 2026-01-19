# -*- coding: utf-8 -*-
"""
Core Logger Implementation
==========================

Unified logging with consistent format across all modules.
Format: [LEVEL]   [Module]  Message

Example outputs:
    [INFO]     [Solver]        Ready in 2.3s
    [INFO]     [Research]      Starting deep research...
    [INFO]     [Guide]         Compiling knowledge points
    [INFO]     [Knowledge]     Indexed 150 documents
    [ERROR]    [EmbeddingClient]  Embedding request failed
"""

from datetime import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import sys
from typing import Any, List, Optional, Union

from src.config.constants import PROJECT_ROOT


class LogLevel(Enum):
    """Log levels with standard tags"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    PROGRESS = "PROGRESS"
    COMPLETE = "COMPLETE"


class ConsoleFormatter(logging.Formatter):
    """
    Clean console formatter with colors and standard level tags.
    Format: [LEVEL]   [Module]  Message
    """

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[90m",  # Gray
        "INFO": "\033[37m",  # White
        "SUCCESS": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "PROGRESS": "\033[36m",  # Cyan
        "COMPLETE": "\033[32m",  # Green
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    def __init__(self, service_prefix: Optional[str] = None):
        """
        Initialize console formatter.

        Args:
            service_prefix: Optional service layer prefix (e.g., "Backend", "Frontend")
        """
        super().__init__()
        self.service_prefix = service_prefix
        # Check TTY status once during initialization
        stdout_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        stderr_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        self.use_colors = stdout_tty or stderr_tty

    def format(self, record: logging.LogRecord) -> str:
        # Get display level (may be custom like SUCCESS, PROGRESS)
        display_level = getattr(record, "display_level", record.levelname)

        # Get module name
        module = getattr(record, "module_name", record.name)

        # Build module tag [Module]
        module_tag = f"[{module}]"

        # Build level tag with colon
        level_tag = f"{display_level}:"

        # Use pre-computed TTY status
        if self.use_colors:
            color = self.COLORS.get(display_level, self.COLORS["INFO"])
            dim = self.DIM
            reset = self.RESET
        else:
            color = ""
            dim = ""
            reset = ""

        # Format message
        message = record.getMessage()

        # Build output: [Backend] [Module] INFO: Message (module first, then level)
        if self.service_prefix:
            service_tag = f"[{self.service_prefix}]"
            return f"{dim}{service_tag}{reset} {dim}{module_tag}{reset} {color}{level_tag}{reset} {message}"
        else:
            return f"{dim}{module_tag}{reset} {color}{level_tag}{reset} {message}"


class FileFormatter(logging.Formatter):
    """
    Detailed file formatter for log files.
    Format: TIMESTAMP [LEVEL] [Module] Message
    """

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(levelname)-8s] [%(module_name)-12s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # Ensure module_name exists
        if not hasattr(record, "module_name"):
            record.module_name = record.name
        return super().format(record)


class Logger:
    """
    Unified logger for DeepTutor.

    Features:
    - Consistent format across all modules
    - Color-coded console output
    - File logging to user/logs/
    - WebSocket streaming support
    - Success/progress/complete convenience methods
    - Optional service layer prefix (Backend/Frontend)

    Usage:
        logger = Logger("Solver")
        logger.info("Processing...")
        logger.success("Done!", elapsed=2.3)
        logger.progress("Step 1/5")
    """

    def __init__(
        self,
        name: str,
        level: str = "INFO",
        console_output: bool = True,
        file_output: bool = True,
        log_dir: Optional[Union[str, Path]] = None,
        service_prefix: Optional[str] = None,
    ):
        """
        Initialize logger.

        Args:
            name: Module name (e.g., "Solver", "Research", "Guide")
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            console_output: Whether to output to console
            file_output: Whether to output to file
            log_dir: Log directory (default: ../user/logs/)
            service_prefix: Optional service layer prefix (e.g., "Backend", "Frontend")
        """
        self.name = name
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.service_prefix = service_prefix

        # Create underlying Python logger
        self.logger = logging.getLogger(f"deeptutor.{name}")
        self.logger.setLevel(logging.DEBUG)  # Capture all, filter at handlers
        self.logger.handlers.clear()
        self.logger.propagate = False  # Prevent duplicate logs from root logger
        # Setup log directory
        log_dir_path: Path
        if log_dir is None:
            log_dir_path = PROJECT_ROOT / "data" / "user" / "logs"
        else:
            log_dir_path = Path(log_dir) if isinstance(log_dir, str) else log_dir
            # If relative path, resolve it relative to project root
            if not log_dir_path.is_absolute():
                log_dir_path = PROJECT_ROOT / log_dir_path

        log_dir_path.mkdir(parents=True, exist_ok=True)
        self.log_dir = log_dir_path

        # Console handler
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            console_handler.setFormatter(ConsoleFormatter(service_prefix=service_prefix))
            self.logger.addHandler(console_handler)

        # File handler
        if file_output:
            timestamp = datetime.now().strftime("%Y%m%d")
            log_file = log_dir_path / f"deeptutor_{timestamp}.log"

            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            file_handler.setFormatter(FileFormatter())
            self.logger.addHandler(file_handler)

            self._log_file = log_file

        # For backwards compatibility with task-specific logging
        self._task_handlers: List[logging.Handler] = []

        # Display manager for TUI (optional, used by solve_agents)
        self.display_manager = None

    def add_task_log_handler(
        self, task_log_file: str, capture_stdout: bool = False, capture_stderr: bool = False
    ):
        """
        Add a task-specific log file handler.
        For backwards compatibility with old SolveAgentLogger.

        Args:
            task_log_file: Path to the task log file
            capture_stdout: Ignored (kept for API compatibility)
            capture_stderr: Ignored (kept for API compatibility)
        """
        task_path = Path(task_log_file)
        task_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(task_log_file, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(FileFormatter())
        self.logger.addHandler(handler)
        self._task_handlers.append(handler)

    def remove_task_log_handlers(self):
        """Remove all task-specific log handlers."""
        for handler in self._task_handlers:
            self.logger.removeHandler(handler)
            handler.close()
        self._task_handlers.clear()

    def log_stage_progress(self, stage: str, status: str, detail: Optional[str] = None):
        """Backwards compatibility alias for stage()"""
        self.stage(stage, status, detail)

    def section(self, title: str, char: str = "=", length: int = 60):
        """Print a section header"""
        self.info(char * length)
        self.info(title)
        self.info(char * length)

    def _log(
        self,
        level: int,
        message: str,
        display_level: Optional[str] = None,
        **kwargs,
    ):
        """Internal logging method with extra attributes."""
        extra = {
            "module_name": self.name,
            "display_level": display_level or logging.getLevelName(level),
        }
        # Extract standard logging parameters from kwargs
        log_kwargs = {
            "extra": extra,
            "exc_info": kwargs.get("exc_info", False),
            "stack_info": kwargs.get("stack_info", False),
            "stacklevel": kwargs.get("stacklevel", 1),
        }
        self.logger.log(level, message, **log_kwargs)

    # Standard logging methods
    def debug(self, message: str, **kwargs):
        """Debug level log [DEBUG]"""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        """Info level log [INFO]"""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Warning level log [WARNING]"""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        """Error level log [ERROR]"""
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs):
        """Critical level log [CRITICAL]"""
        self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs):
        """Log exception with traceback"""
        self.logger.exception(message, extra={"module_name": self.name, "display_level": "ERROR"})

    # Convenience methods
    def success(self, message: str, elapsed: Optional[float] = None, **kwargs):
        """Success log [SUCCESS]"""
        if elapsed is not None:
            message = f"{message} in {elapsed:.1f}s"
        self._log(logging.INFO, message, display_level="SUCCESS", **kwargs)

    def progress(self, message: str, **kwargs):
        """Progress log [PROGRESS]"""
        self._log(logging.INFO, message, display_level="PROGRESS", **kwargs)

    def complete(self, message: str, **kwargs):
        """Completion log [COMPLETE]"""
        self._log(logging.INFO, message, display_level="COMPLETE", **kwargs)

    def stage(self, stage_name: str, status: str = "start", detail: Optional[str] = None):
        """
        Log stage progress.

        Args:
            stage_name: Name of the stage (e.g., "Analysis", "Synthesis")
            status: One of "start", "running", "complete", "skip", "error"
            detail: Optional detail message
        """
        # Map status to display level
        status_to_level = {
            "start": "PROGRESS",
            "running": "INFO",
            "complete": "SUCCESS",
            "skip": "INFO",
            "error": "ERROR",
            "warning": "WARNING",
        }
        display_level = status_to_level.get(status, "INFO")

        message = f"{stage_name}"
        if status == "complete":
            message += " completed"
        elif status == "start":
            message += " started"
        elif status == "running":
            message += " running"
        elif status == "skip":
            message += " skipped"
        elif status == "error":
            message += " failed"

        if detail:
            message += f" | {detail}"

        level = logging.ERROR if status == "error" else logging.INFO
        self._log(level, message, display_level=display_level)

    def tool_call(
        self, tool_name: str, status: str = "success", elapsed_ms: Optional[float] = None, **kwargs
    ):
        """
        Log tool call.

        Args:
            tool_name: Name of the tool
            status: "success", "error", or "running"
            elapsed_ms: Execution time in milliseconds
        """
        display_level = (
            "SUCCESS" if status == "success" else ("ERROR" if status == "error" else "INFO")
        )

        message = f"Tool: {tool_name}"
        if elapsed_ms is not None:
            message += f" ({elapsed_ms:.0f}ms)"
        if status == "error":
            message += " [FAILED]"

        self._log(
            logging.INFO if status != "error" else logging.ERROR,
            message,
            display_level=display_level,
        )

    def llm_call(
        self,
        model: str,
        agent: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        elapsed: Optional[float] = None,
        **kwargs,
    ):
        """
        Log LLM API call.

        Args:
            model: Model name
            agent: Agent making the call
            tokens_in: Input tokens
            tokens_out: Output tokens
            elapsed: Call duration in seconds
        """
        parts = [f"LLM: {model}"]
        if agent:
            parts.append(f"agent={agent}")
        if tokens_in is not None:
            parts.append(f"in={tokens_in}")
        if tokens_out is not None:
            parts.append(f"out={tokens_out}")
        if elapsed is not None:
            parts.append(f"{elapsed:.2f}s")

        message = " | ".join(parts)
        self._log(logging.DEBUG, message)

    def separator(self, char: str = "─", length: int = 50):
        """Print a separator line"""
        self.info(char * length)

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: Any = None,
        tool_output: Any = None,
        status: str = "success",
        elapsed_ms: Optional[float] = None,
        **kwargs,
    ):
        """
        Log a tool call with input/output details.
        Backwards compatible with old SolveAgentLogger.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input (logged to file only)
            tool_output: Tool output (logged to file only)
            status: "success", "error", or "running"
            elapsed_ms: Execution time in milliseconds
        """
        display_level = (
            "SUCCESS" if status == "success" else ("ERROR" if status == "error" else "INFO")
        )

        # Console message (brief)
        message = f"Tool: {tool_name}"
        if elapsed_ms is not None:
            message += f" ({elapsed_ms:.0f}ms)"
        if status == "error":
            message += " [FAILED]"

        self._log(
            logging.INFO if status != "error" else logging.ERROR,
            message,
            display_level=display_level,
        )

        # Debug log with full details (file only)
        if tool_input is not None:
            try:
                input_str = (
                    json.dumps(tool_input, ensure_ascii=False, indent=2)
                    if isinstance(tool_input, (dict, list))
                    else str(tool_input)
                )
                self.debug(f"Tool Input: {input_str[:500]}...")
            except:
                pass
        if tool_output is not None:
            try:
                output_str = (
                    json.dumps(tool_output, ensure_ascii=False, indent=2)
                    if isinstance(tool_output, (dict, list))
                    else str(tool_output)
                )
                self.debug(f"Tool Output: {output_str[:500]}...")
            except:
                pass

    def log_llm_input(
        self,
        agent_name: str,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[dict[str, Any]] = None,
    ):
        """Log LLM input (debug level, file only)"""
        self.debug(
            f"LLM Input [{agent_name}:{stage}] system={len(system_prompt)}chars, user={len(user_prompt)}chars"
        )

    def log_llm_output(
        self, agent_name: str, stage: str, response: str, metadata: Optional[dict[str, Any]] = None
    ):
        """Log LLM output (debug level, file only)"""
        self.debug(f"LLM Output [{agent_name}:{stage}] response={len(response)}chars")

    def log_llm_call(
        self,
        model: str,
        stage: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        agent_name: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost: Optional[float] = None,
        level: str = "INFO",
    ):
        """
        Log complete LLM call with formatted output.

        Args:
            model: Model name
            stage: Stage name (e.g., "generate_question", "validate")
            system_prompt: System prompt content
            user_prompt: User prompt content
            response: LLM response content
            agent_name: Agent name (optional)
            input_tokens: Input token count (optional)
            output_tokens: Output token count (optional)
            cost: Estimated cost (optional)
            level: Log level ("DEBUG" for full details, "INFO" for summary)
        """
        # Build header
        header_parts = ["LLM-CALL"]
        if agent_name:
            header_parts.append(f"Agent: {agent_name}")
        header_parts.append(f"Stage: {stage}")
        header_parts.append(f"Model: {model}")
        header = " | ".join(header_parts)

        # Log at appropriate level
        log_level = logging.DEBUG if level == "DEBUG" else logging.INFO

        if level == "DEBUG":
            # Full detailed output
            self._log(log_level, header)
            self._log(log_level, "--- Input ---")
            self._log(
                log_level,
                (
                    f"System: {system_prompt[:200]}..."
                    if len(system_prompt) > 200
                    else f"System: {system_prompt}"
                ),
            )
            self._log(
                log_level,
                (
                    f"User: {user_prompt[:500]}..."
                    if len(user_prompt) > 500
                    else f"User: {user_prompt}"
                ),
            )
            self._log(log_level, "--- Output ---")
            self._log(log_level, f"{response[:1000]}..." if len(response) > 1000 else response)

            # Token and cost info
            token_info_parts = []
            if input_tokens is not None:
                token_info_parts.append(f"in={input_tokens}")
            if output_tokens is not None:
                token_info_parts.append(f"out={output_tokens}")
            if input_tokens is not None and output_tokens is not None:
                token_info_parts.append(f"total={input_tokens + output_tokens}")
            if cost is not None:
                token_info_parts.append(f"cost=${cost:.6f}")

            if token_info_parts:
                self._log(log_level, f"Tokens: {' '.join(token_info_parts)}")
        else:
            # Summary output
            token_info = ""
            if input_tokens is not None and output_tokens is not None:
                token_info = f" | Tokens: in={input_tokens}, out={output_tokens}, total={input_tokens + output_tokens}"
            if cost is not None:
                token_info += f" | Cost: ${cost:.6f}"

            message = f"{header}{token_info}"
            self._log(log_level, message)

    def update_token_stats(self, summary: dict[str, Any]):
        """Update token statistics (for display manager compatibility)"""
        # Log token stats at debug level
        if summary:
            total_tokens = summary.get("total_tokens", 0)
            self.debug(f"Token Stats: {total_tokens} tokens")

    def shutdown(self):
        """
        Shut down this logger by cleaning up **all** attached handlers.

        This method iterates over a copy of ``self.logger.handlers``, calls
        ``close()`` on each handler to release any underlying resources
        (such as open file streams or other I/O handles), and then removes
        the handler from the underlying ``logging.Logger`` instance.

        Note:
            This closes and removes every handler currently attached to this
            logger instance (including any task-specific handlers), not just a
            subset of handlers. Callers that previously relied on only
            task-specific handlers being removed should be aware that this
            method now performs a full cleanup of all handlers.
        """
        # Close all handlers
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)


# Global logger registry - key is tuple of (name, level, console_output, file_output, log_dir, service_prefix)
_loggers: dict[tuple[str, str, bool, bool, Optional[str], Optional[str]], "Logger"] = {}

# Global default service prefix (can be set at application startup)
_default_service_prefix: Optional[str] = None


def set_default_service_prefix(prefix: Optional[str]):
    """
    Set the default service prefix for all new loggers.

    Call this at application startup to set a global prefix like "Backend" or "Frontend".

    Args:
        prefix: Service prefix (e.g., "Backend", "Frontend") or None to disable
    """
    global _default_service_prefix
    _default_service_prefix = prefix


def get_logger(
    name: str = "Main",
    level: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = True,
    log_dir: Optional[str] = None,
    service_prefix: Optional[str] = None,
) -> Logger:
    """
    Get or create a logger instance.

    Args:
        name: Module name
        level: Log level (if None, uses global level from config/main.yaml)
        console_output: Enable console output
        file_output: Enable file output
        log_dir: Log directory (if None, will try to load from config/main.yaml)
        service_prefix: Optional service prefix (if None, uses default set by set_default_service_prefix)

    Returns:
        Logger instance
    """
    global _loggers, _default_service_prefix

    # Use default service prefix if not explicitly provided
    effective_service_prefix = (
        service_prefix if service_prefix is not None else _default_service_prefix
    )

    # Load config for log_dir and level
    effective_level = level
    if log_dir is None or effective_level is None:
        try:
            from src.services.config import get_path_from_config, load_config_with_main

            config = load_config_with_main("solve_config.yaml", PROJECT_ROOT)

            # Get log_dir from config
            if log_dir is None:
                log_dir = get_path_from_config(config, "user_log_dir") or config.get(
                    "paths", {}
                ).get("user_log_dir")
                if log_dir:
                    log_dir_path = Path(log_dir)
                    if not log_dir_path.is_absolute():
                        log_dir_str = str(log_dir_path).lstrip("./")
                        log_dir = str(PROJECT_ROOT / log_dir_str)
                    else:
                        log_dir = str(log_dir_path)

            # Get level from config (unified global level)
            if effective_level is None:
                from .config import get_global_log_level

                effective_level = get_global_log_level()
        except Exception:
            pass

    # Use DEBUG as ultimate fallback
    if effective_level is None:
        effective_level = "DEBUG"

    log_dir_key = str(log_dir) if log_dir is not None else None
    cache_key = (
        name,
        effective_level,
        console_output,
        file_output,
        log_dir_key,
        effective_service_prefix,
    )

    if cache_key not in _loggers:
        _loggers[cache_key] = Logger(
            name=name,
            level=effective_level,
            console_output=console_output,
            file_output=file_output,
            log_dir=log_dir,
            service_prefix=effective_service_prefix,
        )

    return _loggers[cache_key]


def reset_logger(name: Optional[str] = None):
    """
    Reset logger(s).

    Args:
        name: Logger name to reset, or None to reset all
    """
    global _loggers

    if name is None:
        keys_to_remove = list(_loggers.keys())
    else:
        # Remove all loggers with the given name, supporting both tuple and string keys
        keys_to_remove = [
            key
            for key in _loggers.keys()
            if (isinstance(key, tuple) and len(key) > 0 and key[0] == name) or key == name
        ]

    for key in keys_to_remove:
        _loggers.pop(key, None)


def reload_loggers():
    """
    Reload configuration for all cached loggers.

    This method clears the logger cache, forcing recreation with current config
    on next get_logger() calls.
    """
    global _loggers
    _loggers.clear()
