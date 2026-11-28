"""Whether this turn discloses optional tools through ``load_tools``.

A loop turn can offer a tool in two ways: mount its schema in ``tools[]``, or
list it in the Extended Tools catalog and let the model ``load_tools`` it when
it actually needs it. Mounting per message ("this message mentions a paper",
"this message says *switch the model*") makes ``tools[]`` differ between two
turns of one conversation, which invalidates the provider's prompt cache from
the first tool on. Deferred tools only ever grow: a loaded schema stays loaded
for the rest of the session.

The loop pipeline decides once per turn whether deferral is available (the
turn is not owned by an exclusive capability, and ``load_tools`` itself is
allowed) and records it here *before* any capability's ``is_active`` is asked.
A capability whose tools would otherwise be mounted by a message heuristic
reads it to stay inactive — and to keep its system block out — on such turns.
Callers that never set it (other pipelines, direct tests) keep the eager
behaviour.
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext

_EXTENSION = "tool_disclosure"
_DEFERRAL_KEY = "deferral_available"


def set_deferral_available(context: UnifiedContext, available: bool) -> None:
    context.extension(_EXTENSION)[_DEFERRAL_KEY] = bool(available)


def deferral_available(context: UnifiedContext) -> bool:
    """``True`` once the pipeline has confirmed optional tools can be deferred."""
    return bool(context.extension(_EXTENSION).get(_DEFERRAL_KEY))


__all__ = ["deferral_available", "set_deferral_available"]
