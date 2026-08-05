"""MED-02 adapter configuration: timeouts, MCP tool mapping, runtime secrets.

The durable :class:`~deeptutor.services.media.models.ImageGenerationJob` never
persists secrets (api key, base URL, auth headers — §10.5).  Adapters therefore
receive a resolved :class:`AdapterRuntimeConfig` at execution time; the resolver
reads it from the model catalog and hands it to the worker's executor.  Tests
inject their own resolver so no real endpoint is ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from deeptutor.services.media.models import ImageGenerationJob

#: Adapter kinds understood by the MED-02 executor router.
ADAPTER_OPENAI_IMAGES = "openai_images"
ADAPTER_OPENAI_RESPONSES = "openai_responses"
ADAPTER_MCP = "mcp"

ADAPTER_KINDS = (ADAPTER_OPENAI_IMAGES, ADAPTER_OPENAI_RESPONSES, ADAPTER_MCP)


@dataclass(frozen=True)
class ImageAdapterSettings:
    """Profile-configurable long-timeout and polling knobs (§11.4).

    These deliberately do not inherit browser/chat request timeouts: image
    generation is slow and non-streaming.  The worker stores the effective
    values on each job; ``create_job`` defaults are 20s connect / 30m read /
    60m total deadline.
    """

    connect_timeout_seconds: int = 20
    read_timeout_seconds: int = 1800
    total_deadline_seconds: int = 3600
    #: First poll delay and backoff ceiling for background jobs (§11.4).
    poll_start_seconds: float = 2.0
    poll_backoff_cap_seconds: float = 15.0
    max_redirects: int = 5


@dataclass(frozen=True)
class McpImageToolConfig:
    """Argument mapping for one MCP image tool (§10.4).

    ``prompt_arg`` is required; ``size_arg``/``count_arg`` and ``static_args``
    are optional.  Edit is available only when the tool config explicitly
    declares ``source_arg``/``mask_arg``; otherwise an edit request returns a
    stable ``unsupported_operation`` and is never silently turned into a
    generate.

    ``owner`` selects the manager scope (``""`` = the deployment's shared
    servers).
    """

    server_name: str
    tool_name: str
    prompt_arg: str = "prompt"
    size_arg: str = ""
    count_arg: str = ""
    static_args: dict[str, Any] = field(default_factory=dict)
    source_arg: str = ""
    mask_arg: str = ""
    owner: str = ""

    @property
    def supports_edit(self) -> bool:
        return bool(self.source_arg)


@dataclass(frozen=True)
class AdapterRuntimeConfig:
    """Resolved, secret-bearing configuration handed to one adapter call.

    Never persisted and never logged; lives only for the duration of an
    executor invocation.  ``adapter_kind`` selects the MED-02 adapter.
    """

    adapter_kind: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    auth_style: str = "bearer"
    extra_headers: dict[str, str] = field(default_factory=dict)
    api_version: str = ""
    size: str = ""
    quality: str = ""
    style: str = ""
    response_format: str = ""
    #: Capability flags.  A provider lacking edit/mask/continuation returns a
    #: stable ``unsupported_operation``; it must never silently call generate.
    supports_edit: bool = True
    supports_continuation: bool = False
    supports_background: bool = False
    #: MCP mapping (used when ``adapter_kind == "mcp"``).
    mcp: McpImageToolConfig | None = None


#: Resolver contract: job -> runtime config (injectable for offline tests).
AdapterConfigResolver = Callable[[ImageGenerationJob], AdapterRuntimeConfig]


__all__ = [
    "ADAPTER_KINDS",
    "ADAPTER_MCP",
    "ADAPTER_OPENAI_IMAGES",
    "ADAPTER_OPENAI_RESPONSES",
    "AdapterConfigResolver",
    "AdapterRuntimeConfig",
    "ImageAdapterSettings",
    "McpImageToolConfig",
]
