"""OpenAI Responses ``image_generation`` tool adapter (MED-02).

Submits a background Responses request (§10.3, §11.5), persists the provider's
``response`` identity, then *retrieves* the result by that id.  After a remote
id exists, disconnect/restart may only retrieve/reconcile/cancel — never
re-submit.  Edits are supported through a same-user/same-profile continuation
job: the previous response id is resolved server-side from the persisted job
record, so a client can never inject an arbitrary remote id.  A Responses
profile that is asked to edit without a continuation raises a stable
``unsupported_operation`` and never silently generates.

The official wire contract (coordinator-verified on 2026-08-04) is:

* ``tools`` image entry is ``{"type": "image_generation", ...image options...}``
  with **no** ``name`` field, and the built-in tool is forced with
  ``tool_choice={"type": "image_generation"}``.
* A completed ``image_generation_call`` output item is
  ``{"id": "ig_...", "type": "image_generation_call", "status": "completed",
  "revised_prompt": "...", "result": "<base64 string>"}`` — ``result`` is a
  base64 string, not an array of nested image objects.

OpenAI-compatible endpoints that return ``result`` as a list of
``{"image_url": ..., "asset_id": ..., "revised_prompt": ...}`` objects (URL or
``data:`` URI) remain intentionally supported as an extension, but the official
shape is authoritative.

A submit POST that returns *any* response id returns a :class:`BackgroundSubmit`
— including an already-completed response — so the remote identity is durable on
the job *before* any image decode/download/validation can fail (§11.5).  The
polling path then retrieves by id and materializes the images.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from deeptutor.services.llm.provider_core.unified.responses import (
    RESPONSES_PATH,
    responses_cancel_path,
    responses_retrieve_path,
)
from deeptutor.services.llm.provider_core.unified.transport import (
    HttpTransport,
    LLMTransport,
    TransportError,
)
from deeptutor.services.media.adapter_config import (
    ADAPTER_OPENAI_RESPONSES,
    AdapterRuntimeConfig,
)
from deeptutor.services.media.adapters.base import (
    ImageGenerationRequest,
    UnsupportedOperationError,
    is_ambiguous_transport_failure,
    request_from_job,
)
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    AmbiguousSubmitError,
    ArtifactOperation,
    BackgroundSubmit,
    ImageGenerationJob,
    MediaConfigError,
    MediaError,
    MediaInput,
    PollOutcome,
    TransientPollError,
)
from deeptutor.services.media.safe_download import SafeDownloader, validate_media_bytes
from deeptutor.services.media.store import MediaStore

logger = logging.getLogger(__name__)


class _MediaHttpTransport(HttpTransport):
    """HttpTransport honoring the job's connect/read timeouts (§11.4)."""

    def __init__(self, base_url: str, *, connect: int, read: int) -> None:
        super().__init__(base_url, timeout=read)
        self._connect = connect

    async def _client_for(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=self._connect),
                verify=self.verify,
                follow_redirects=False,
            )
        return self._client


def build_image_generation_body(
    request: ImageGenerationRequest,
    *,
    previous_response_id: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Build the Responses request body for the built-in ``image_generation``
    tool.

    ``model`` is the *resolved provider model* from the model catalog — never
    the durable job's catalog entry id, which must not be sent to the provider.
    A non-MCP Responses body without a resolved model fails closed (§11.3/§16.3).
    ``previous_response_id`` is server-resolved from a persisted continuation
    job — never client-supplied (§10.3).
    """
    if not model:
        raise MediaConfigError("Responses image generation requires a resolved provider model.")
    tool: dict[str, Any] = {"type": "image_generation"}
    if request.size:
        tool["size"] = request.size
    if request.quality:
        tool["quality"] = request.quality
    body: dict[str, Any] = {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": request.prompt}],
            }
        ],
        "tools": [tool],
        # The built-in image tool is forced by its type, not by a function name.
        "tool_choice": {"type": "image_generation"},
        "store": False,
        "background": True,
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    return body


def parse_image_generation_response(
    raw: dict[str, Any],
) -> tuple[str, str, list[dict[str, Any]]]:
    """Return ``(response_id, status, image_items)`` from a Responses payload.

    ``image_items`` are normalized descriptors of every
    ``image_generation_call`` output item:

    * official shape — ``{"base64": <str>, "asset_id": <call id>,
      "revised_prompt": <str>}`` where ``result`` is a base64 string;
    * compatible extension — ``{"src": <url-or-data-uri>, "asset_id": <str>,
      "revised_prompt": <str>}`` for each ``result`` list entry.
    """
    response_id = str(raw.get("id") or "")
    status = str(raw.get("status") or "")
    images: list[dict[str, Any]] = []
    for item in raw.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image_generation_call":
            continue
        item_id = str(item.get("id") or "")
        item_revised = str(item.get("revised_prompt") or "")
        result = item.get("result")
        if isinstance(result, str):
            # Official shape: `result` is a base64-encoded image.
            images.append(
                {
                    "base64": result,
                    "asset_id": item_id,
                    "revised_prompt": item_revised,
                }
            )
        elif isinstance(result, list):
            # OpenAI-compatible extension: `result` is a list of image objects.
            for image in result:
                if not isinstance(image, dict):
                    continue
                images.append(
                    {
                        "src": image.get("image_url"),
                        "asset_id": str(image.get("asset_id") or item_id),
                        "revised_prompt": str(image.get("revised_prompt") or item_revised),
                    }
                )
    return response_id, status, images


class OpenAIResponsesImageAdapter:
    """Background Responses image-generation adapter (submit/retrieve/cancel)."""

    def __init__(
        self,
        *,
        config: AdapterRuntimeConfig,
        store: MediaStore,
        transport: LLMTransport | None = None,
        downloader: SafeDownloader | None = None,
        limits: MediaLimits | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._limits = limits or store.limits
        self._transport = transport
        self._owns_transport = transport is None
        self._downloader = downloader
        self._owns_downloader = downloader is None

    @property
    def kind(self) -> str:
        return ADAPTER_OPENAI_RESPONSES

    async def aclose(self) -> None:
        if self._owns_transport and self._transport is not None:
            await self._transport.aclose()
        if self._owns_downloader and self._downloader is not None:
            await self._downloader.aclose()

    # ── executor contract ────────────────────────────────────────────────────

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit:
        request = request_from_job(job)
        previous_response_id = ""
        if request.operation == ArtifactOperation.EDIT:
            if not request.continuation_job_id:
                # A Responses edit is only possible through a previous response
                # (multi-turn lineage); a bare source-artifact edit must not be
                # silently turned into a generate (§10.3).
                raise UnsupportedOperationError(
                    "edit", detail="Responses edits require a continuation job"
                )
            if not self._config.supports_continuation:
                raise UnsupportedOperationError("edit")
            previous_response_id = self._resolve_continuation(job)
        elif not self._config.supports_background:
            raise UnsupportedOperationError("background image generation")

        resolved_model = self._config.model
        if not resolved_model:
            # A non-MCP Responses job must resolve to a real provider model;
            # the durable catalog entry id must never be sent upstream and an
            # empty value must fail closed before any provider call (§11.3).
            raise MediaConfigError(f"image profile {job.profile!r} resolves to no provider model")
        transport = await self._transport_for(job)
        body = build_image_generation_body(
            request,
            previous_response_id=previous_response_id,
            model=resolved_model,
        )
        try:
            raw = await transport.request_json("POST", RESPONSES_PATH, body, self._headers())
        except (TransportError, httpx.HTTPError) as exc:
            raise self._classify_submit_failure(exc) from exc

        response_id, _status, _images = parse_image_generation_response(raw)
        if not response_id:
            raise MediaError("Responses image submit returned no response id.")

        # The remote identity must be durable before materialization (§11.5).
        # Return a BackgroundSubmit for every acknowledged POST — including an
        # already-completed response — so the worker persists the id and the
        # polling path retrieves by id.  A decode/download/validation failure
        # therefore can never lose the ability to reconcile the remote job.
        return BackgroundSubmit(remote_response_id=response_id, poll_after=2.0)

    async def poll(self, job: ImageGenerationJob) -> PollOutcome:
        response_id = job.remote_response_id
        if not response_id:
            raise MediaError("Cannot poll a Responses job without a response id.")
        transport = await self._transport_for(job)
        try:
            raw = await transport.request_json(
                "GET", responses_retrieve_path(response_id), None, self._headers()
            )
        except (TransportError, httpx.HTTPError) as exc:
            # A transient retrieve/read failure must not fail the job while the
            # remote job may still be running (§11.5): keep polling with bounded
            # backoff until the deadline, never resubmit.
            raise TransientPollError(
                f"Responses image retrieve failed: {self._short_error(exc)}"
            ) from exc
        _response_id, status, images = parse_image_generation_response(raw)
        if status == "completed":
            return PollOutcome(media=await self._images_to_media(job, response_id, images))
        if status in ("in_progress", "queued", ""):
            return PollOutcome(poll_after=2.0)
        if status in ("cancelled", "failed", "incomplete"):
            # Provider-confirmed terminal outcome; the worker persists a stable
            # sanitized code (§11.5).
            raise MediaError(f"Responses image job ended {status!r}.")
        raise MediaError(f"Responses image job has unknown status {status!r}.")

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        response_id = job.remote_response_id
        if not response_id:
            return False
        transport = await self._transport_for(job)
        try:
            raw = await transport.request_json(
                "POST", responses_cancel_path(response_id), {}, self._headers()
            )
        except (TransportError, httpx.HTTPError) as exc:
            logger.warning("Responses cancel failed: %s", self._short_error(exc))
            return False
        _response_id, status, _images = parse_image_generation_response(raw)
        return status == "cancelled"

    # ── helpers ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
            **(self._config.extra_headers or {}),
        }

    def _classify_submit_failure(self, exc: Exception) -> MediaError:
        """Classify a submit-POST transport failure (§11.5).

        Read/write-phase failures after the request may have been accepted are
        ambiguous — the provider may bill and process the job — so the worker
        transitions the job to ``unknown``.  Definite pre-connect/unaccepted
        failures remain ordinary failures.
        """
        if is_ambiguous_transport_failure(exc):
            return AmbiguousSubmitError(
                "Responses image submit may have been accepted, but the outcome "
                "is unknown and cannot be reconciled locally."
            )
        return MediaError(f"Responses image submit failed: {self._short_error(exc)}")

    async def _transport_for(self, job: ImageGenerationJob) -> LLMTransport:
        if self._transport is None:
            self._transport = _MediaHttpTransport(
                self._config.base_url,
                connect=job.connect_timeout_seconds,
                read=job.read_timeout_seconds,
            )
        return self._transport

    async def _downloader_for(self) -> SafeDownloader:
        if self._downloader is None:
            self._downloader = SafeDownloader(limits=self._limits, read_timeout=1800.0)
        return self._downloader

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """One-line error text with the transport detail (already sanitized by
        the worker before persistence; never the raw response body)."""
        return type(exc).__name__

    def _resolve_continuation(self, job: ImageGenerationJob) -> str:
        """Resolve ``previous_response_id`` from the persisted continuation job
        (§10.3).  Ownership/profile were already enforced at submission; this
        only reads the provider's own remote identity."""
        prior = self._store.load_job(job.continuation_job_id)
        if prior is None:
            raise MediaError("Continuation job no longer exists.")
        if not prior.remote_response_id:
            raise MediaError("Continuation job has no remote response id.")
        return prior.remote_response_id

    async def _images_to_media(
        self,
        job: ImageGenerationJob,
        response_id: str,
        images: list[dict[str, Any]],
    ) -> list[MediaInput]:
        if not images:
            raise MediaError("Responses image job completed with no images.")
        media: list[MediaInput] = []
        downloader = await self._downloader_for()
        for image in images:
            if "base64" in image:
                # Official shape: `result` is a base64 string.  Decode and
                # validate into MediaInput (§12.1).
                encoded = image["base64"]
                try:
                    data = base64.b64decode(encoded)
                except Exception as exc:
                    raise MediaError("Responses image returned malformed base64.") from exc
                sniffed, _width, _height = validate_media_bytes(data, limits=self._limits)
                media.append(
                    MediaInput(
                        data=data,
                        mime_type=sniffed,
                        remote_response_id=response_id,
                        remote_asset_id=str(image.get("asset_id") or ""),
                        revised_prompt=str(image.get("revised_prompt") or ""),
                    )
                )
                continue
            src = image.get("src")
            if isinstance(src, str) and src.startswith("data:image/"):
                _, _, encoded = src.partition(",")
                try:
                    data = base64.b64decode(encoded)
                except Exception as exc:
                    raise MediaError("Responses image returned malformed base64.") from exc
                header = src[5:].split(";", 1)[0].strip() or "image/png"
                media.append(
                    MediaInput(
                        data=data,
                        mime_type=header,
                        remote_response_id=response_id,
                        remote_asset_id=str(image.get("asset_id") or ""),
                        revised_prompt=str(image.get("revised_prompt") or ""),
                    )
                )
            elif isinstance(src, str) and src:
                result = await downloader.download(src)
                media.append(
                    MediaInput(
                        data=result.data,
                        mime_type=result.mime_type,
                        remote_response_id=response_id,
                        remote_asset_id=str(image.get("asset_id") or ""),
                        revised_prompt=str(image.get("revised_prompt") or ""),
                    )
                )
            else:
                raise MediaError("Responses image item had no usable image source.")
        return media


def build_responses_transport(base_url: str, *, connect: int, read: int) -> LLMTransport:
    """Production transport with the job's long timeouts (§11.4)."""
    return _MediaHttpTransport(base_url, connect=connect, read=read)


__all__ = [
    "OpenAIResponsesImageAdapter",
    "build_image_generation_body",
    "build_responses_transport",
    "parse_image_generation_response",
]
