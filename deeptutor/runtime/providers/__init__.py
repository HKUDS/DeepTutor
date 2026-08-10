"""External tool providers: the tools a deployment or a user plugs in.

An *external provider* is something that contributes tools DeepTutor did not
ship — an MCP server today, an installed CLI app next. What they share is the
disclosure pipeline, which already exists and is source-agnostic: one manifest
line per tool in the system prompt, full schemas only after the model calls
``load_tools`` (see :mod:`deeptutor.runtime.registry.deferred_tools`). What
they do *not* share is authorisation, so that stays per-kind and explicit in
:mod:`~deeptutor.runtime.providers.authorize`.

Layering — this package sits **below** the tool registry:

* :mod:`allowlist` — allowed-name set with an explicit *unrestricted* state;
* :mod:`scope` — the per-turn policy inputs;
* :mod:`authorize` — one authorisation function per provider kind;
* :mod:`text` — sanitiser for provider-supplied prompt text.

Those four have no dependencies of their own, which is what lets the registry
import them (``deferred_tools`` sanitises through :mod:`text`).

:mod:`view` is the exception: it *composes* the registry, so it depends
upwards. Import it directly (``from deeptutor.runtime.providers.view import
build_tool_view``) — re-exporting it here would put the registry back in this
package's import path and make the two mutually dependent, resolvable only by
luck of import order.
"""

from __future__ import annotations

from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.providers.authorize import authorize_mcp_tools
from deeptutor.runtime.providers.scope import ToolScope
from deeptutor.runtime.providers.text import (
    MANIFEST_DESCRIPTION_MAX_CHARS,
    sanitize_provider_text,
)

__all__ = [
    "MANIFEST_DESCRIPTION_MAX_CHARS",
    "Allowlist",
    "ToolScope",
    "authorize_mcp_tools",
    "sanitize_provider_text",
]
