import os
import resource

class SubprocessGuard:
    """
    Implements safety checks and resource limits for python code execution in subprocesses.
    Addresses security concerns in the Smart Solver (#185).
    """
    @staticmethod
    def set_resource_limits(cpu_seconds=5, memory_mb=256):
        # Limit CPU time
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        # Limit address space (memory)
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

    @staticmethod
    def restrict_environment():
        # Strip sensitive env vars before execution
        for key in list(os.environ.keys()):
            if any(secret in key.upper() for secret in ["KEY", "TOKEN", "PASSWORD"]):
                del os.environ[key]
