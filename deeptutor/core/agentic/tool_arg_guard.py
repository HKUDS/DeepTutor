"""Pre-dispatch validation of model-authored tool arguments.

Under a large tool surface and a long history, models intermittently emit a
native function call whose ``arguments`` is empty (or partial) even though
the schema marks fields required — reproduced on several OpenAI-compatible
providers (issue #779).

Before this guard those calls were dispatched as-is, so the *tool* was left
to reject them: ``exec`` raised ``ValueError: exec requires a non-empty
command`` and ``write_note`` answered ``Unknown mode ''``. Neither reads as
"you forgot an argument", so the model re-emitted the same malformed call
until the loop budget ran out — one report saw 5 of 7 ``write_note`` calls
in a single turn arrive empty and retried 5–7 times.

The guard converts that into one self-correcting round: the call is never
dispatched, and the ``role=tool`` body names exactly which required
arguments were missing and what shape they take, which is what the next
iteration needs to re-emit a well-formed call.

Deliberately free of dispatcher, registry, and stream concerns: it maps a
:class:`~deeptutor.core.tool_protocol.ToolDefinition` plus the prepared
kwargs to a list of missing arguments and a corrective message, so any call
site that dispatches model-authored tool calls can reuse it and the rules
stay unit-testable on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deeptutor.core.tool_protocol import ToolDefinition


@dataclass(frozen=True)
class RequiredArg:
    """A required parameter, reduced to what the corrective message needs."""

    name: str
    type: str = ""
    enum: tuple[str, ...] = ()

    def describe(self) -> str:
        parts = [self.type or "value"]
        if self.enum:
            parts.append("one of: " + " | ".join(self.enum))
        return f"{self.name} ({', '.join(parts)})"


def _is_supplied(value: Any) -> bool:
    """Whether a kwarg counts as actually provided.

    ``None`` and a blank string are treated as absent because that is how a
    provider serialises "the model left this out" in practice. Empty
    collections are left alone: ``[]`` / ``{}`` can be a deliberate value
    for an array or object parameter, and rejecting them would refuse calls
    that used to work.
    """
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def required_args(definition: ToolDefinition) -> list[RequiredArg]:
    """Required parameters of a tool, excluding any that carry a default.

    A parameter with a default is satisfiable without the model naming it,
    so treating it as required would reject calls the tool can serve.

    Handles both schema flavours: ``raw_parameters`` (verbatim JSON Schema,
    used by MCP adapters) and the :class:`ToolParameter` rows built-ins
    declare.
    """
    raw = definition.raw_parameters
    if raw is not None:
        names = raw.get("required")
        if not isinstance(names, list):
            return []
        properties = raw.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        args: list[RequiredArg] = []
        for name in names:
            if not isinstance(name, str) or not name:
                continue
            prop = properties.get(name)
            prop = prop if isinstance(prop, dict) else {}
            if "default" in prop:
                continue
            enum = prop.get("enum")
            args.append(
                RequiredArg(
                    name=name,
                    type=str(prop.get("type") or ""),
                    enum=tuple(str(v) for v in enum) if isinstance(enum, list) else (),
                )
            )
        return args

    return [
        RequiredArg(
            name=p.name,
            type=p.type,
            enum=tuple(str(v) for v in p.enum) if p.enum else (),
        )
        for p in definition.parameters
        if p.required and p.default is None
    ]


def missing_required_args(
    definition: ToolDefinition,
    args: dict[str, Any],
) -> list[RequiredArg]:
    """Required parameters the call failed to supply.

    ``args`` must be the *prepared* kwargs — i.e. after server-side
    augmentation — so an argument the pipeline injects on the model's behalf
    counts as supplied.
    """
    return [arg for arg in required_args(definition) if not _is_supplied(args.get(arg.name))]


def missing_args_message(tool_name: str, missing: list[RequiredArg]) -> str:
    """Corrective ``role=tool`` body for a call that was never dispatched.

    Names the missing arguments and their accepted shape, and says plainly
    that repeating the same call will fail again — the model's failure mode
    here is retrying verbatim, not misreading the schema.
    """
    named = ", ".join(f"`{arg.name}`" for arg in missing)
    shapes = "; ".join(arg.describe() for arg in missing)
    return (
        f"(tool call not dispatched — `{tool_name}` was called without its required "
        f"argument(s): {named}. Expected: {shapes}. Re-emit the call with those "
        "arguments filled in; an identical call with empty arguments will be "
        "rejected again without running.)"
    )
