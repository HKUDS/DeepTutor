#!/usr/bin/env python
"""
Run Code Tool - Code execution tool
Execute Python code in isolated workspace.  Every execution is persisted
under ``run_code_workspace/`` with its source code, output log, and any
generated artifacts (images, data files, etc.).
"""

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

RUN_CODE_WORKSPACE_ENV = "RUN_CODE_WORKSPACE"
RUN_CODE_ALLOWED_ROOTS_ENV = "RUN_CODE_ALLOWED_ROOTS"
DEFAULT_WORKSPACE_NAME = "run_code_workspace"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

from src.logging import get_logger
from src.services.path_service import get_path_service

logger = get_logger("CodeExecutor")

_MAX_CONCURRENT_SUBPROCESSES = int(os.getenv("CODE_EXEC_MAX_CONCURRENT", "3"))
_fork_semaphore: asyncio.Semaphore | None = None


def _get_fork_semaphore() -> asyncio.Semaphore:
    """Lazily create a per-event-loop semaphore limiting concurrent subprocess forks.

    subprocess.run uses fork() which creates a COW clone of the entire parent
    process virtual address space.  When the parent holds several GB of RAG
    data, many concurrent forks can push committed virtual memory to 50-80 GB
    and trigger the OS OOM killer.
    """
    global _fork_semaphore
    if _fork_semaphore is None:
        _fork_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SUBPROCESSES)
    return _fork_semaphore

# Files managed by the executor itself (excluded from user-artifact lists)
_META_FILES = frozenset({"code.py", "output.log", ".gitkeep"})


def _load_config() -> dict[str, Any]:
    """Load run_code configuration from main.yaml and module configs"""
    try:
        from src.services.config import load_config_with_main

        for cfg_name in ("solve_config.yaml", "question_config.yaml"):
            try:
                config = load_config_with_main(cfg_name, PROJECT_ROOT)
                run_code_config = config.get("tools", {}).get("run_code", {})
                if run_code_config:
                    logger.debug(f"Loaded run_code config from {cfg_name} (with main.yaml)")
                    return run_code_config
            except Exception as e:
                logger.debug(f"Failed to load from {cfg_name}: {e}")

    except ImportError:
        logger.debug("config_loader not available, using fallback")

    # Fallback: try loading main.yaml directly
    try:
        import yaml

        main_config_path = PROJECT_ROOT / "config" / "main.yaml"
        if main_config_path.exists():
            with open(main_config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            run_code_config = config.get("tools", {}).get("run_code", {})
            if run_code_config:
                logger.debug("Loaded run_code config from main.yaml")
                return run_code_config
    except Exception as e:
        logger.debug(f"Failed to load from main.yaml: {e}")

    return {}


def _save_output_log(
    execution_dir: Path,
    stdout: str,
    stderr: str,
    exit_code: int,
    elapsed_ms: float,
) -> Path:
    """Persist execution output to ``output.log`` inside *execution_dir*."""
    log_file = execution_dir / "output.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"Exit Code: {exit_code}\n")
        f.write(f"Elapsed: {elapsed_ms:.1f}ms\n")
        f.write(f"{'=' * 50}\n")
        if stdout:
            f.write(f"[STDOUT]\n{stdout}\n")
        if stderr:
            f.write(f"[STDERR]\n{stderr}\n")
    return log_file


class CodeExecutionError(Exception):
    """Code execution error"""


@dataclass
class OperationEntry:
    action: str
    details: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class OperationLogger:
    """Simple operation history logger."""

    def __init__(self, max_entries: int = 200):
        self._history: list[OperationEntry] = []
        self._max_entries = max_entries

    def log(self, action: str, details: dict[str, Any]):
        entry = OperationEntry(action=action, details=details)
        self._history.append(entry)
        if len(self._history) > self._max_entries:
            self._history.pop(0)
        logger.debug(f"Operation logged: {action} | details={details.get('status')}")

    @property
    def history(self) -> list[OperationEntry]:
        return list(self._history)


class WorkspaceManager:
    """Manages the persistent ``run_code_workspace`` directory."""

    def __init__(self):
        config = _load_config()

        env_path = os.getenv(RUN_CODE_WORKSPACE_ENV)
        if env_path:
            self.base_dir = Path(env_path).expanduser().resolve()
        else:
            config_workspace = config.get("workspace")
            if config_workspace:
                workspace_path = Path(config_workspace).expanduser()
                if workspace_path.is_absolute():
                    self.base_dir = workspace_path.resolve()
                else:
                    self.base_dir = (PROJECT_ROOT / workspace_path).resolve()
            else:
                path_service = get_path_service()
                self.base_dir = path_service.get_run_code_workspace_dir().resolve()

        self._initialized = False

    def initialize(self):
        if not self._initialized:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            self._initialized = True
            logger.info(f"Run-code workspace initialized at {self.base_dir}")

    def ensure_initialized(self):
        if not self._initialized:
            self.initialize()

    def create_execution_dir(self, prefix: str = "exec") -> Path:
        """Create a persistent, timestamped execution directory under the workspace."""
        self.ensure_initialized()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        exec_dir = self.base_dir / f"{prefix}_{timestamp}"
        exec_dir.mkdir(parents=True, exist_ok=True)
        return exec_dir

    def collect_artifacts(self, exec_dir: Path | None) -> tuple[list[str], list[str]]:
        """Return user-generated files (excluding code.py / output.log)."""
        artifacts: list[str] = []
        artifact_paths: list[str] = []
        if not exec_dir or not exec_dir.exists():
            return artifacts, artifact_paths

        for file_path in exec_dir.iterdir():
            if file_path.is_file() and file_path.name not in _META_FILES:
                artifacts.append(file_path.name)
                artifact_paths.append(str(file_path.resolve()))
        return artifacts, artifact_paths


class ImportGuard:
    """Parse AST, restrict import modules."""

    @staticmethod
    def validate(code: str, allowed_imports: list[str] | None):
        if not allowed_imports:
            return

        allowed = set(allowed_imports)
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise CodeExecutionError(f"Code syntax error: {exc}") from exc

        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.append(node.module.split(".")[0])

        unauthorized = sorted({name for name in imported if name not in allowed})
        if unauthorized:
            raise CodeExecutionError(
                f"The following modules are not in the allowed list: {', '.join(unauthorized)}"
            )


class CodeExecutionEnvironment:
    """Run Python code inside a persistent execution directory."""

    def run_python(
        self,
        code: str,
        timeout: int,
        execution_dir: Path,
    ) -> tuple[str, str, int, float]:
        """Write *code* to ``execution_dir/code.py``, execute it, and return
        (stdout, stderr, exit_code, elapsed_ms).  The source file is kept on
        disk for later inspection."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        code_file = execution_dir / "code.py"
        code_file.write_text(code, encoding="utf-8")

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(code_file)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(execution_dir),
            env=env,
        )
        elapsed_ms = (time.time() - start_time) * 1000
        return result.stdout, result.stderr, result.returncode, elapsed_ms


WORKSPACE_MANAGER = WorkspaceManager()
OPERATION_LOGGER = OperationLogger()
EXECUTION_ENV = CodeExecutionEnvironment()


async def run_code(
    language: str,
    code: str,
    timeout: int = 10,
    allowed_imports: list[str] | None = None,
    workspace_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Execute code in an isolated, persistent directory under ``run_code_workspace``.

    Each invocation creates a new timestamped directory containing:
    - ``code.py``    – the executed source code
    - ``output.log`` – captured stdout / stderr and exit info
    - any files the code itself generates (images, data, etc.)

    Returns a dict with stdout, stderr, exit_code, elapsed_ms, execution_dir,
    source_file, output_log, artifacts, and artifact_paths.
    """
    if language.lower() != "python":
        raise ValueError(f"Unsupported language: {language}, currently only Python is supported")

    if workspace_dir is not None:
        custom_workspace = Path(workspace_dir).expanduser().resolve()
        custom_workspace.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        execution_dir = custom_workspace / f"exec_{timestamp}"
        execution_dir.mkdir(parents=True, exist_ok=True)
    else:
        WORKSPACE_MANAGER.ensure_initialized()
        execution_dir = WORKSPACE_MANAGER.create_execution_dir()
    stdout, stderr, exit_code, elapsed_ms = "", "", -1, 0.0
    status = "error"

    try:
        ImportGuard.validate(code, allowed_imports)

        loop = asyncio.get_running_loop()

        def _execute():
            return EXECUTION_ENV.run_python(code, timeout, execution_dir)

        async with _get_fork_semaphore():
            stdout, stderr, exit_code, elapsed_ms = await loop.run_in_executor(
                None, _execute
            )
        status = "success"

    except subprocess.TimeoutExpired:
        elapsed_ms = timeout * 1000
        stderr = f"Code execution timeout ({timeout} seconds)"
        status = "timeout"
        logger.warning(f"Code execution timeout after {timeout}s")
        # Ensure source file is written even if timeout happened before write
        src = execution_dir / "code.py"
        if not src.exists():
            src.write_text(code, encoding="utf-8")

    except CodeExecutionError as exc:
        stderr = str(exc)
        status = "validation_error"
        # Source code was invalid; still save it for diagnosis
        src = execution_dir / "code.py"
        if not src.exists():
            src.write_text(code, encoding="utf-8")

    except Exception as exc:  # pylint: disable=broad-except
        stderr = f"Code execution failed: {exc}"
        logger.error(f"Code execution error: {exc}", exc_info=True)
        src = execution_dir / "code.py"
        if not src.exists():
            src.write_text(code, encoding="utf-8")

    # Always persist the output log
    _save_output_log(execution_dir, stdout, stderr, exit_code, elapsed_ms)

    artifacts, artifact_paths = WORKSPACE_MANAGER.collect_artifacts(execution_dir)

    OPERATION_LOGGER.log(
        "execute_python",
        {
            "status": status,
            "language": language,
            "timeout": timeout,
            "execution_dir": str(execution_dir),
            "exit_code": exit_code,
            "elapsed_ms": elapsed_ms,
            "code_size": len(code),
        },
    )

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "elapsed_ms": elapsed_ms,
        "execution_dir": str(execution_dir),
        "source_file": str(execution_dir / "code.py"),
        "output_log": str(execution_dir / "output.log"),
        "artifacts": artifacts,
        "artifact_paths": artifact_paths,
    }


def run_code_sync(
    language: str,
    code: str,
    timeout: int = 10,
) -> dict[str, Any]:
    """Synchronous version of code execution (for non-async environments)."""
    return asyncio.run(run_code(language, code, timeout))


if __name__ == "__main__":
    import textwrap

    async def _demo():
        print("==== 1. Test normal output ====")
        sample1 = "print('Hello from run_code workspace!')"
        result1 = await run_code("python", sample1, timeout=5)
        print("stdout:", result1["stdout"])
        print("stderr:", result1["stderr"])
        print("execution_dir:", result1["execution_dir"])
        print("source_file:", result1["source_file"])
        print("output_log:", result1["output_log"])
        print("artifacts:", result1["artifacts"])
        print("exit_code:", result1["exit_code"])
        print("-" * 40)

        print("==== 2. Test exception case ====")
        sample2 = "raise ValueError('Test error from run_code!')"
        result2 = await run_code("python", sample2, timeout=5)
        print("stdout:", result2["stdout"])
        print("stderr:", result2["stderr"])
        print("execution_dir:", result2["execution_dir"])
        print("exit_code:", result2["exit_code"])
        print("-" * 40)

        print("==== 3. Test code timeout ====")
        sample3 = textwrap.dedent("""\
            import time
            time.sleep(10)
            print("Timeout should occur before this prints.")
        """)
        result3 = await run_code("python", sample3, timeout=2)
        print("stdout:", result3["stdout"])
        print("stderr:", result3["stderr"])
        print("execution_dir:", result3["execution_dir"])
        print("exit_code:", result3["exit_code"])
        print("-" * 40)

        print("==== 4. Test plotting functionality (matplotlib) ====")
        sample4 = textwrap.dedent("""\
            import matplotlib.pyplot as plt
            plt.figure()
            plt.plot([1, 2, 3], [4, 2, 5])
            plt.title('Simple Plot')
            plt.savefig('test_plot.png')
            print('Plot created!')
        """)
        result4 = await run_code("python", sample4, timeout=5)
        print("stdout:", result4["stdout"])
        print("stderr:", result4["stderr"])
        print("execution_dir:", result4["execution_dir"])
        print("artifacts:", result4["artifacts"])
        print("artifact_paths:", result4["artifact_paths"])
        print("exit_code:", result4["exit_code"])
        print("-" * 40)

        print("==== 5. Test file read/write ====")
        sample5 = textwrap.dedent("""\
            with open('test_file.txt', 'w', encoding='utf-8') as f:
                f.write('Fake data for test!\\nAnother line.')
            with open('test_file.txt', 'r', encoding='utf-8') as f:
                content = f.read()
            print('File content:', content)
        """)
        result5 = await run_code("python", sample5, timeout=5)
        print("stdout:", result5["stdout"])
        print("stderr:", result5["stderr"])
        print("execution_dir:", result5["execution_dir"])
        print("artifacts:", result5["artifacts"])
        print("exit_code:", result5["exit_code"])
        print("-" * 40)

    asyncio.run(_demo())
