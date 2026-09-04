"""Connected Agents backend for a remote Hermes Agent gateway."""

from __future__ import annotations

import os
import re
from typing import Any

import anyio
import httpx

from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig, load_subagent_settings
from deeptutor.services.subagent.hermes_remote_client import (
    HermesRemoteClient,
    HermesRemoteHTTPError,
    HermesRemoteProtocolError,
)
from deeptutor.services.subagent.hermes_remote_events import HermesRemoteEventMapper
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    ConsultResult,
    DetectResult,
    SubagentEvent,
)

CONSULT_ORIGIN_INSTRUCTION = (
    "Caller identity: DeepTutor Connected Agents. Answer the user's question directly; "
    "do not route the question to DeepTutor."
)
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_REMOTE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,511}\Z")
_REQUIRED_CAPABILITIES = frozenset(
    {
        "run_submission",
        "run_events_sse",
        "run_stop",
        "run_approval_response",
        "session_resources",
    }
)


class HermesRemoteBackend(SubagentBackend):
    """Drive the Hermes gateway's authenticated ``/v1/runs`` API."""

    kind = "hermes_remote"
    display_name = "Hermes Agent (remote)"
    cli_command = ""
    local_cli = False
    detectable = True

    def __init__(
        self,
        config: BackendConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._configured = config
        self._transport = transport

    @property
    def config(self) -> BackendConfig:
        """Return injected config, or the persisted remote-backend settings."""
        return self._configured or load_subagent_settings().backend(self.kind)

    def _client(self, config: BackendConfig, key: str) -> HermesRemoteClient:
        return HermesRemoteClient(config.base_url, key, transport=self._transport)

    async def detect(self) -> DetectResult:
        """Probe the gateway capability contract and classify failures."""
        config = self.config
        if not config.base_url:
            return self._detection(False, "not_configured")
        if not self._valid_env_name(config.api_key_env):
            return self._detection(False, "invalid_key_env")
        key = os.environ.get(config.api_key_env, "").strip()
        if not key:
            return self._detection(False, "key_missing")
        try:
            async with self._client(config, key) as client:
                payload = await client.get_json("/v1/capabilities")
        except HermesRemoteHTTPError as exc:
            detail = "unauthorized" if exc.status_code in (401, 403) else "incompatible"
            return self._detection(False, detail)
        except httpx.RequestError:
            return self._detection(False, "unreachable")
        except HermesRemoteProtocolError as exc:
            detail = exc.code if exc.code == "invalid_base_url" else "incompatible"
            return self._detection(False, detail)
        features = payload.get("features")
        if (
            payload.get("object") != "hermes.api_server.capabilities"
            or not isinstance(features, dict)
            or not all(features.get(name) is True for name in _REQUIRED_CAPABILITIES)
        ):
            return self._detection(False, "incompatible")
        version = str(payload.get("model") or "")
        return self._detection(True, "", version=version or "Hermes API")

    def _detection(self, available: bool, detail: str, *, version: str = "") -> DetectResult:
        return DetectResult(
            kind=self.kind,
            display_name=self.display_name,
            available=available,
            version=version,
            detail=detail,
        )

    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,  # noqa: ARG002 - remote gateway owns its cwd
        session_id: str | None = None,
        config: BackendConfig | None = None,
        images: list[str] | None = None,
        partner_id: str | None = None,  # noqa: ARG002 - partner-only
    ) -> ConsultResult:
        """Submit a run, translate its SSE lifecycle, and return its session id."""
        run_config = config or self.config
        result = ConsultResult(session_id=session_id)
        emitted_text = ""
        run_id: str | None = None
        terminal_received = False
        key = (
            os.environ.get(run_config.api_key_env, "").strip()
            if self._valid_env_name(run_config.api_key_env)
            else ""
        )

        async def emit(
            kind: str,
            text: str,
            raw: dict[str, Any],
            meta: dict[str, Any] | None = None,
        ) -> None:
            result.event_count += 1
            await on_event(
                SubagentEvent(
                    kind=kind,
                    text=self._redact(text, key),
                    raw=self._redact_raw(raw, key),
                    meta=meta or {},
                ),
            )

        if not run_config.base_url:
            result.success = False
            result.error = "not_configured"
            await emit(EVENT_ERROR, result.error, {})
            return result
        if not self._valid_env_name(run_config.api_key_env):
            result.success = False
            result.error = "invalid_key_env"
            await emit(EVENT_ERROR, result.error, {})
            return result
        if not key:
            result.success = False
            result.error = "key_missing"
            await emit(EVENT_ERROR, result.error, {})
            return result
        if session_id and not self._valid_remote_id(session_id):
            result.success = False
            result.error = "invalid_session_id"
            await emit(EVENT_ERROR, result.error, {})
            return result

        # The gateway contract has no attachment upload field. Do not leak
        # DeepTutor-local filesystem paths to a remote process.
        prompt = question
        try:
            async with self._client(run_config, key) as client:
                session_gone = False
                history: list[dict[str, str]] | None = None
                if session_id:
                    try:
                        history = await client.get_session_history(session_id)
                    except HermesRemoteHTTPError as exc:
                        if exc.status_code != 404:
                            raise
                        session_gone = True
                active_session_id = None if session_gone else session_id
                instructions = CONSULT_ORIGIN_INSTRUCTION
                if run_config.system_prompt.strip() and (not session_id or session_gone):
                    instructions = f"{run_config.system_prompt.strip()}\n\n{instructions}"
                payload: dict[str, Any] = {"input": prompt, "instructions": instructions}
                if active_session_id:
                    payload["session_id"] = active_session_id
                if history is not None:
                    payload["conversation_history"] = history
                if run_config.model:
                    payload["model"] = run_config.model
                if run_config.effort:
                    payload["model_options"] = {"reasoning_effort": run_config.effort}
                headers = self._session_headers(active_session_id)
                started = await client.post_json("/v1/runs", payload, headers=headers or None)
                run_id = self._run_id(started)
                result.session_id = self._result_session_id(started, active_session_id, run_id)
                mapper = HermesRemoteEventMapper(
                    client,
                    run_id,
                    result,
                    emit,
                    auto_approve=run_config.auto_approve,
                )
                events = client.stream_events(run_id)
                iterator = events.__aiter__()
                while True:
                    try:
                        with anyio.fail_after(max(0.001, run_config.idle_timeout_seconds)):
                            event = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        await self._stop_client(client, run_id)
                        result.success = False
                        result.error = "idle_timeout"
                        await emit(EVENT_ERROR, result.error, {})
                        return result
                    emitted_text = await mapper.handle(event, emitted_text)
                    if event.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
                        terminal_received = True
                        break
        except anyio.get_cancelled_exc_class():
            if run_id:
                await self._stop_after_cancel(run_config, key, run_id)
            raise
        except HermesRemoteHTTPError as exc:
            result.success = False
            result.error = self._http_error(exc.status_code)
            await emit(EVENT_ERROR, result.error, {})
        except HermesRemoteProtocolError as exc:
            result.success = False
            result.error = exc.code
            await emit(EVENT_ERROR, result.error, {})
        except httpx.RequestError:
            result.success = False
            result.error = "unreachable"
            await emit(EVENT_ERROR, result.error, {})

        if result.success and not terminal_received:
            result.success = False
            result.error = "incomplete_stream"
            await emit(EVENT_ERROR, result.error, {})
        elif result.success and not result.final_text:
            result.success = False
            result.error = "empty_response"
            await emit(EVENT_ERROR, result.error, {})
        return result

    @staticmethod
    def _run_id(payload: dict[str, Any]) -> str:
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not HermesRemoteBackend._valid_remote_id(run_id):
            raise HermesRemoteProtocolError("missing_run_id")
        return run_id

    @staticmethod
    def _result_session_id(
        payload: dict[str, Any], requested_session_id: str | None, run_id: str
    ) -> str:
        session_id = payload.get("session_id") or requested_session_id or run_id
        if not isinstance(session_id, str) or not HermesRemoteBackend._valid_remote_id(session_id):
            raise HermesRemoteProtocolError("invalid_session_id")
        return session_id

    @staticmethod
    def _valid_env_name(value: str) -> bool:
        return bool(_ENV_NAME_RE.fullmatch(value))

    @staticmethod
    def _valid_remote_id(value: str) -> bool:
        return bool(_REMOTE_ID_RE.fullmatch(value))

    @staticmethod
    def _session_headers(session_id: str | None) -> dict[str, str]:
        if not session_id:
            return {}
        return {"X-Hermes-Session-Id": session_id, "X-Hermes-Session": session_id}

    async def _stop_after_cancel(self, config: BackendConfig, key: str, run_id: str) -> None:
        with anyio.CancelScope(shield=True):
            with anyio.move_on_after(5.0):
                try:
                    async with self._client(config, key) as client:
                        await client.post_json(f"/v1/runs/{run_id}/stop", {})
                except (HermesRemoteHTTPError, HermesRemoteProtocolError, httpx.RequestError):
                    return

    async def _stop_client(self, client: HermesRemoteClient, run_id: str) -> None:
        try:
            await client.post_json(f"/v1/runs/{run_id}/stop", {})
        except (HermesRemoteHTTPError, HermesRemoteProtocolError, httpx.RequestError):
            return

    @staticmethod
    def _http_error(status_code: int) -> str:
        return f"http_{status_code}"

    @staticmethod
    def _redact(text: str, secret: str) -> str:
        return text.replace(secret, "[REDACTED]") if secret else text

    @classmethod
    def _redact_raw(cls, value: dict[str, Any], secret: str) -> dict[str, Any]:
        return {key: cls._redact_value(item, secret) for key, item in value.items()}

    @classmethod
    def _redact_value(cls, value: Any, secret: str) -> Any:
        if isinstance(value, str):
            return cls._redact(value, secret)
        if isinstance(value, dict):
            return {key: cls._redact_value(item, secret) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_value(item, secret) for item in value]
        return value


__all__ = ["CONSULT_ORIGIN_INSTRUCTION", "HermesRemoteBackend"]
