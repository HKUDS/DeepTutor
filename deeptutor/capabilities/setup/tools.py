"""The four tools through which DeepTutor configures itself.

They are deliberately generic: each one walks
:mod:`deeptutor.services.config.settings_spec` rather than knowing anything
about a particular setting, so a new knob becomes reachable by adding a spec
row and touching nothing here.

``inspect_setup``
    Read the install: current values, what else each row offers, what is
    missing, and which long-running jobs could be started.

``apply_setting``
    Commit one row, after the checks in :mod:`deeptutor.capabilities.setup.apply`.

``request_credential``
    The one thing the agent is *not* allowed to do itself. Anything that needs
    an API key hands off to the settings page, so credentials never enter the
    model's context, the conversation history, or the session transcript.

``run_setup_job``
    Install an engine or fetch its weights, following the log live.

Asking the user a question is not among them: ``ask_user`` already does that,
already renders a card with clickable options, and already pauses the turn
until the answer arrives. The spec rows return their options in exactly that
card's ``{label, description}`` shape, so a proposal is a plain ``ask_user``
call rather than a bespoke second mechanism.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

SETUP_TOOL_NAMES: tuple[str, ...] = (
    "inspect_setup",
    "apply_setting",
    "request_credential",
    "run_setup_job",
)

# Services whose configuration involves a secret. Each maps to the settings
# route that already owns its provider form.
_CREDENTIAL_ROUTES: dict[str, tuple[str, str]] = {
    "llm": ("/settings/llm", "chat model provider"),
    "embedding": ("/settings/embedding", "embedding model provider"),
    "search": ("/settings/search", "web search provider"),
    "parsing": ("/settings/document-parsing", "document parsing engine"),
}


def _ok(payload: Any, **metadata: Any) -> ToolResult:
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=True,
        metadata=dict(metadata),
    )


def _err(message: str, **metadata: Any) -> ToolResult:
    return ToolResult(content=message, success=False, metadata=dict(metadata))


class InspectSetupTool(BaseTool):
    """Report what the install is configured to do, and what it cannot."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="inspect_setup",
            description=(
                "Read DeepTutor's own configuration: every setting you can "
                "change, its current value, the other values it accepts, what "
                "changing it would cost, plus anything missing from this "
                "install and any install/download jobs available. Call this "
                "FIRST — before offering the user any configuration change — "
                "so what you offer matches what this machine actually has."
            ),
            parameters=[
                ToolParameter(
                    name="area",
                    type="string",
                    description=(
                        "Optional filter: 'interface' (language, theme), "
                        "'models' (chat / embedding / search), 'parsing' "
                        "(document engine). Omit for everything."
                    ),
                    required=False,
                    enum=["interface", "models", "parsing"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.capabilities.setup.access import can_write
        from deeptutor.capabilities.setup.binding import setup_gaps
        from deeptutor.capabilities.setup.jobs import available_jobs
        from deeptutor.services.config.settings_spec import specs_for_area

        area = str(kwargs.get("area") or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for spec in specs_for_area(area):
            decision = can_write(spec.scope)
            try:
                current = spec.read()
                choices = spec.choices()
            except Exception as exc:  # noqa: BLE001 - one bad row must not hide the rest
                rows.append({"key": spec.key, "label": spec.label, "error": str(exc)[:200]})
                continue
            rows.append(
                {
                    "key": spec.key,
                    "label": spec.label,
                    "area": spec.area,
                    "summary": spec.summary,
                    "scope": spec.scope,
                    "effect": spec.effect,
                    "effect_detail": spec.effect_detail,
                    "writable": decision.allowed,
                    "not_writable_because": decision.reason,
                    "current": current,
                    "current_label": next(
                        (c.label for c in choices if c.value == current),
                        "" if current else "not set",
                    ),
                    "options": [
                        {
                            "value": c.value,
                            "label": c.label,
                            "description": c.description,
                            "available": c.available,
                        }
                        for c in choices
                    ],
                }
            )

        # Installing an engine or fetching weights changes the machine for
        # every account, so it carries the same gate as a global setting. The
        # verdict rides on each job: without it the model reads a job list it
        # cannot run and offers the user something that will be refused.
        jobs_decision = can_write("global")
        jobs = [
            {
                **job,
                "runnable": jobs_decision.allowed,
                "not_runnable_because": jobs_decision.reason,
            }
            for job in available_jobs()
        ]

        payload = {
            "settings": rows,
            "gaps": [gap.to_dict() for gap in setup_gaps()],
            "jobs_available": jobs,
        }
        return _ok(payload, setup_inspect=payload)


class ApplySettingTool(BaseTool):
    """Commit one setting after validating and probing it."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="apply_setting",
            description=(
                "Change one DeepTutor setting. The value must be one of the "
                "options inspect_setup reported for that key. Settings that "
                "can break the assistant (the chat and embedding models) are "
                "connection-tested before anything is saved, and are left "
                "untouched when the test fails. Confirm with the user via "
                "ask_user before calling this, then report the returned "
                "'effect' — some changes need a restart or a knowledge-base "
                "rebuild. To undo, call again with the returned 'previous'."
            ),
            parameters=[
                ToolParameter(
                    name="key",
                    type="string",
                    description="Setting key exactly as reported by inspect_setup.",
                ),
                ToolParameter(
                    name="value",
                    type="string",
                    description="One of that setting's option values (not its label).",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.capabilities.setup.apply import apply_setting

        key = str(kwargs.get("key") or "").strip()
        value = str(kwargs.get("value") or "").strip()
        if not key or not value:
            return _err("apply_setting needs both 'key' and 'value'.")

        outcome = await apply_setting(key, value)
        payload = outcome.to_dict()
        if not outcome.ok:
            return ToolResult(
                content=json.dumps(payload, ensure_ascii=False),
                success=False,
                metadata={"setup_apply": payload},
            )
        # ``setup_applied`` tells the frontend which slice of its cached
        # settings just went stale; the UI re-reads that slice instead of
        # showing a value the backend no longer holds.
        return _ok(payload, setup_apply=payload, setup_applied={"key": outcome.key})


class RequestCredentialTool(BaseTool):
    """Hand a credential-entering step back to the user's own settings page."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="request_credential",
            description=(
                "Use when a change needs an API key, token or password. You "
                "must NEVER ask the user to type a secret into the chat and "
                "must never handle one yourself: this shows the user a card "
                "that opens the right settings page, where the value is "
                "entered directly into DeepTutor. Call it, tell the user what "
                "to do there, and continue once they say they are done."
            ),
            parameters=[
                ToolParameter(
                    name="service",
                    type="string",
                    description="Which provider needs credentials.",
                    enum=["llm", "embedding", "search", "parsing"],
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description=(
                        "One line explaining to the user why this is needed, in their language."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        service = str(kwargs.get("service") or "").strip().lower()
        route = _CREDENTIAL_ROUTES.get(service)
        if route is None:
            return _err(
                f"Unknown service '{service}'. Expected one of: "
                f"{', '.join(sorted(_CREDENTIAL_ROUTES))}."
            )
        path, label = route
        payload = {
            "service": service,
            "label": label,
            "settings_path": path,
            "reason": str(kwargs.get("reason") or "").strip(),
        }
        return _ok(
            {
                **payload,
                "status": "handed_off",
                "note": (
                    "The user was shown a card linking to the settings page. Secrets are "
                    "never entered through chat."
                ),
            },
            setup_credential=payload,
        )


class RunSetupJobTool(BaseTool):
    """Install a parsing engine or download its model weights."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="run_setup_job",
            description=(
                "Install a document-parsing engine, or download the model "
                "weights it needs. Only engines inspect_setup listed under "
                "'jobs_available' can be run. These take minutes and model "
                "weights can be several gigabytes — ask the user with "
                "ask_user before starting, and say how large it is. Progress "
                "streams to the user while it runs."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="What to run.",
                    enum=["install_engine", "download_models"],
                ),
                ToolParameter(
                    name="engine",
                    type="string",
                    description="Engine id exactly as reported by inspect_setup.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.capabilities.setup.access import can_write
        from deeptutor.capabilities.setup.jobs import run_job

        # Installing software and writing multi-gigabyte weights changes the
        # machine for every account on it, so it sits behind the same gate as
        # the other deployment-wide changes.
        decision = can_write("global")
        if not decision.allowed:
            return _err(decision.reason)

        action = str(kwargs.get("action") or "").strip()
        engine = str(kwargs.get("engine") or "").strip()
        if not action or not engine:
            return _err("run_setup_job needs both 'action' and 'engine'.")

        event_sink = kwargs.get("event_sink")

        async def _on_line(line: str) -> None:
            if event_sink is None:
                return
            await event_sink("tool_log", line, {"setup_job": {"action": action, "engine": engine}})

        outcome = await run_job(action, engine, on_line=_on_line)
        payload = outcome.to_dict()
        if not outcome.ok:
            return ToolResult(
                content=json.dumps(payload, ensure_ascii=False),
                success=False,
                metadata={"setup_job": payload},
            )
        # An install changes which engines are selectable, so the settings UI
        # must re-read the parsing slice even though no setting was written.
        return _ok(payload, setup_job=payload, setup_applied={"key": "document_parsing.engine"})


SETUP_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    InspectSetupTool,
    ApplySettingTool,
    RequestCredentialTool,
    RunSetupJobTool,
)

__all__ = ["SETUP_TOOL_NAMES", "SETUP_TOOL_TYPES"]
