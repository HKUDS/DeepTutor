"""Runtime policy for provider stream liveness."""

from deeptutor.services.config.runtime_settings import get_runtime_settings_service


def get_stream_idle_timeout_seconds() -> int:
    """Read the effective, normalized timeout for the next provider call."""
    return get_runtime_settings_service().load_system()["llm_stream_idle_timeout_seconds"]
