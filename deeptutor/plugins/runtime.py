"""Typed runtime adapters for managed plugin worker packages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)
from deeptutor.plugins.manifest import PluginManifestData
from deeptutor.plugins.registry import PluginInstallation, PluginRegistry

logger = logging.getLogger(__name__)


class PluginRuntimeError(RuntimeError):
    """Raised when an enabled worker violates the plugin runtime contract."""


_WORKER_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_PERMISSION_KEYS = {"reading", "learning_events", "network", "models", "storage", "ui"}
_HTTP_STATUS_VALUES = frozenset({200, 201, 202, 204, 400, 404, 409, 422, 500})
_HTTP_HEADER_VALUES = re.compile(r"^(?:no-store|no-cache|max-age=[0-9]{1,8})$")


@dataclass(frozen=True, slots=True)
class PluginHttpResponse:
    status: int
    body: Any = None
    headers: Mapping[str, str] | None = None


class _WorkerClient:
    def __init__(
        self,
        *,
        python_path: Path,
        venv_path: Path,
        module: str,
        permissions: dict[str, tuple[str, ...]],
    ) -> None:
        if _WORKER_MODULE.fullmatch(module) is None:
            raise PluginRuntimeError(f"invalid worker module {module!r}")
        self.python_path = python_path
        self.venv_path = venv_path
        self.module = module
        self.permissions = permissions

    def request(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = {"operation": operation, **(payload or {})}
        try:
            completed = subprocess.run(  # noqa: S603 - argv is fixed and module is validated
                [str(self.python_path), "-m", self.module],
                input=json.dumps(request, ensure_ascii=False, default=str),
                capture_output=True,
                text=True,
                env=_clean_env(),
                cwd=self.venv_path,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PluginRuntimeError(f"plugin worker failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
            raise PluginRuntimeError(f"plugin worker exited {completed.returncode}: {detail}")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PluginRuntimeError("plugin worker returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise PluginRuntimeError("plugin worker response must be an object")
        if response.get("error") is not None:
            detail = str(response["error"])[-2000:]
            raise PluginRuntimeError(f"plugin worker error: {detail}")
        self.validate_permissions(response.get("permissions"))
        return response

    def validate_permissions(self, raw: Any) -> None:
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise PluginRuntimeError("worker permissions must be an object")
        for scope, values in raw.items():
            if scope not in _PERMISSION_KEYS or not isinstance(values, list):
                raise PluginRuntimeError(f"worker declares invalid permission scope {scope!r}")
            if not all(isinstance(value, str) for value in values):
                raise PluginRuntimeError(f"worker declares invalid {scope} permissions")
            allowed = set(self.permissions.get(scope, ()))
            if not set(values).issubset(allowed):
                raise PluginRuntimeError(f"worker declares unapproved {scope} permissions")


class PluginWorkerTool(BaseTool):
    def __init__(
        self,
        *,
        manifest: PluginManifestData,
        installation: PluginInstallation,
        extension_id: str,
    ) -> None:
        extension = _extension(manifest, "tool", extension_id)
        self._client = _WorkerClient(
            python_path=installation.python_path,
            venv_path=installation.venv_path,
            module=extension.entry_point,
            permissions=dict(manifest.permissions.scopes),
        )
        described = self._client.request("describe_tool")
        definition = described.get("definition")
        if not isinstance(definition, dict) or definition.get("name") != extension_id:
            raise PluginRuntimeError(f"worker tool declaration does not match {extension_id!r}")
        self._definition = _tool_definition(definition)

    def get_definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: Any) -> ToolResult:
        response = self._client.request("execute_tool", {"arguments": kwargs})
        result = response.get("result")
        if not isinstance(result, dict):
            raise PluginRuntimeError("execute_tool response requires a result object")
        return ToolResult(
            content=str(result.get("content", "")),
            sources=list(result.get("sources", [])),
            metadata=dict(result.get("metadata", {})),
            success=bool(result.get("success", True)),
        )


class PluginWorkerHttpRoute:
    def __init__(
        self,
        *,
        manifest: PluginManifestData,
        installation: PluginInstallation,
        extension_id: str,
    ) -> None:
        extension = _extension(manifest, "http_route", extension_id)
        self.extension = extension
        self._client = _WorkerClient(
            python_path=installation.python_path,
            venv_path=installation.venv_path,
            module=extension.entry_point,
            permissions=dict(manifest.permissions.scopes),
        )

    def handle(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, tuple[str, ...] | list[str]],
        body: Any = None,
    ) -> PluginHttpResponse:
        if method not in self.extension.methods:
            raise PluginRuntimeError(f"HTTP method {method!r} is not declared")
        if path != self.extension.path:
            raise PluginRuntimeError("HTTP route path does not match its manifest")
        response = self._client.request(
            "handle_http",
            {
                "http": {
                    "method": method,
                    "path": path,
                    "query": {name: list(values) for name, values in query.items()},
                    "body": body,
                    "auth": self.extension.auth,
                }
            },
        )
        return _http_response(response.get("http"))


class PluginWorkerCapability(TurnCapability):
    def __init__(
        self,
        *,
        manifest: PluginManifestData,
        installation: PluginInstallation,
        extension_id: str,
    ) -> None:
        extension = _extension(manifest, "capability", extension_id)
        self._client = _WorkerClient(
            python_path=installation.python_path,
            venv_path=installation.venv_path,
            module=extension.entry_point,
            permissions=dict(manifest.permissions.scopes),
        )
        described = self._client.request("describe_capability")
        raw = described.get("capability")
        if not isinstance(raw, dict) or raw.get("name") != extension_id:
            raise PluginRuntimeError(
                f"worker capability declaration does not match {extension_id!r}"
            )
        self.manifest = CapabilityManifest(
            name=str(raw.get("name")),
            description=str(raw.get("description", "")),
            stages=[str(item) for item in raw.get("stages", [])],
            tools_used=[str(item) for item in raw.get("tools_used", [])],
            cli_aliases=[str(item) for item in raw.get("cli_aliases", [])],
            request_schema=dict(raw.get("request_schema", {})),
            config_defaults=dict(raw.get("config_defaults", {})),
        )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        response = self._client.request(
            "run_capability",
            {
                "context": {
                    "session_id": context.session_id,
                    "user_message": context.user_message,
                    "conversation_history": context.conversation_history,
                    "enabled_tools": context.enabled_tools,
                    "active_capability": context.active_capability,
                    "knowledge_bases": context.knowledge_bases,
                    "attachments": [asdict(item) for item in context.attachments],
                    "config_overrides": context.config_overrides,
                    "language": context.language,
                    "metadata": context.metadata,
                }
            },
        )
        events = response.get("events", [])
        if not isinstance(events, list):
            raise PluginRuntimeError("run_capability events must be an array")
        for raw in events:
            await stream.emit(_stream_event(raw, source=self.manifest.name))


def load_enabled_workers(
    registry: PluginRegistry | None = None,
) -> tuple[BaseTool | TurnCapability, ...]:
    """Build tool/capability adapters only for approved managed installations."""
    records = (registry or PluginRegistry()).list_plugins(include_catalog=False)
    extensions: list[BaseTool | TurnCapability] = []
    for record in records:
        if record.status != "enabled" or record.manifest is None or record.installation is None:
            continue
        for extension in record.manifest.extensions:
            try:
                if extension.type == "tool":
                    extensions.append(
                        PluginWorkerTool(
                            manifest=record.manifest,
                            installation=record.installation,
                            extension_id=extension.id,
                        )
                    )
                elif extension.type == "capability":
                    extensions.append(
                        PluginWorkerCapability(
                            manifest=record.manifest,
                            installation=record.installation,
                            extension_id=extension.id,
                        )
                    )
            except PluginRuntimeError as exc:
                logger.warning(
                    "Managed %s %r failed its worker contract; skipping",
                    extension.type,
                    extension.id,
                    exc_info=exc,
                )
    return tuple(extensions)


def load_enabled_tools(registry: PluginRegistry | None = None) -> tuple[BaseTool, ...]:
    return tuple(item for item in load_enabled_workers(registry) if isinstance(item, BaseTool))


def load_enabled_capabilities(
    registry: PluginRegistry | None = None,
) -> tuple[TurnCapability, ...]:
    return tuple(
        item for item in load_enabled_workers(registry) if isinstance(item, TurnCapability)
    )


def entry_point_allowed(
    registry: PluginRegistry,
    *,
    extension_type: str,
    entry_point: str,
) -> bool:
    """Gate only packages that declare this extension in a root manifest.

    Existing built-in and pre-v1 extension points keep working during the
    migration window. Once a package ships a root manifest, its exact
    extension, compatibility, approval digest, and local enablement state must
    all match before the entry point can load.
    """
    for record in registry.list_plugins(include_catalog=False):
        if record.manifest is None:
            continue
        declared = any(
            extension.type == extension_type and extension.entry_point == entry_point
            for extension in record.manifest.extensions
        )
        if declared:
            return record.status == "enabled"
    return True


def _extension(manifest: PluginManifestData, extension_type: str, extension_id: str):
    for extension in manifest.extensions:
        if extension.type == extension_type and extension.id == extension_id:
            return extension
    raise PluginRuntimeError(f"manifest does not declare {extension_type} {extension_id!r}")


def _tool_definition(raw: dict[str, Any]) -> ToolDefinition:
    parameters = []
    for item in raw.get("parameters", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise PluginRuntimeError("tool parameter requires a name")
        parameters.append(
            ToolParameter(
                name=item["name"],
                type=str(item.get("type", "string")),
                description=str(item.get("description", "")),
                required=bool(item.get("required", True)),
                default=item.get("default"),
                enum=item.get("enum"),
                items=item.get("items") if isinstance(item.get("items"), dict) else None,
            )
        )
    return ToolDefinition(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        parameters=parameters,
    )


def _stream_event(raw: Any, *, source: str) -> StreamEvent:
    if not isinstance(raw, dict):
        raise PluginRuntimeError("worker stream events must be objects")
    try:
        event_type = StreamEventType(str(raw.get("type")))
    except ValueError as exc:
        raise PluginRuntimeError(f"unknown worker stream event {raw.get('type')!r}") from exc
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PluginRuntimeError("worker stream metadata must be an object")
    return StreamEvent(
        type=event_type,
        source=source,
        stage=str(raw.get("stage", "")),
        content=str(raw.get("content", "")),
        metadata=metadata,
    )


def _clean_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
    return {key: os.environ[key] for key in keep if key in os.environ}


def _http_response(raw: Any) -> PluginHttpResponse:
    if not isinstance(raw, dict):
        raise PluginRuntimeError("handle_http response requires an http object")
    status = raw.get("status", 200)
    if not isinstance(status, int) or isinstance(status, bool) or status not in _HTTP_STATUS_VALUES:
        raise PluginRuntimeError("handle_http status is not allowed")
    body = raw.get("body")
    if status == 204 and body is not None:
        raise PluginRuntimeError("handle_http 204 response cannot include a body")
    raw_headers = raw.get("headers", {})
    if not isinstance(raw_headers, dict):
        raise PluginRuntimeError("handle_http headers must be an object")
    headers: dict[str, str] = {}
    for name, value in raw_headers.items():
        canonical = str(name).lower()
        if canonical != "cache-control":
            raise PluginRuntimeError(f"handle_http response header {name!r} is not allowed")
        if not isinstance(value, str) or _HTTP_HEADER_VALUES.fullmatch(value) is None:
            raise PluginRuntimeError("handle_http Cache-Control value is not allowed")
        headers["Cache-Control"] = value
    return PluginHttpResponse(status=status, body=body, headers=headers)


__all__ = [
    "PluginRuntimeError",
    "PluginWorkerCapability",
    "PluginWorkerHttpRoute",
    "PluginWorkerTool",
    "PluginHttpResponse",
    "entry_point_allowed",
    "load_enabled_capabilities",
    "load_enabled_tools",
]
