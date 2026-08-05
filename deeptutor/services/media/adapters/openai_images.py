"""OpenAI Images API adapter (MED-02).

Implements ``POST /images/generations`` and ``POST /images/edits`` (or the SDK
equivalent) including ``gpt-image-2``.  Output is parsed from ``b64_json`` or a
temporary ``url``; every URL is materialized through the safe downloader before
anything reaches the content-addressed store (§10.2, §12.1).

Edit loads its source/mask bytes from persisted, user-owned artifacts, enforces
mask dimensions equal to the target source, and raises a stable
``unsupported_operation`` when the configured provider cannot edit — it never
silently falls back to a generate.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from deeptutor.services.generation_http import build_auth_headers, join_api_path
from deeptutor.services.media.adapter_config import (
    ADAPTER_OPENAI_IMAGES,
    AdapterRuntimeConfig,
)
from deeptutor.services.media.adapters.base import (
    AdapterResult,
    ImageGenerationRequest,
    UnsupportedOperationError,
    is_ambiguous_transport_failure,
    raise_for_status,
    request_from_job,
)
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.media_validation import validate_edit_inputs
from deeptutor.services.media.models import (
    AmbiguousSubmitError,
    BackgroundSubmit,
    ImageGenerationJob,
    MediaConfigError,
    MediaError,
    MediaInput,
)
from deeptutor.services.media.safe_download import SafeDownloader

logger = logging.getLogger(__name__)

GENERATIONS_PATH = "images/generations"
EDITS_PATH = "images/edits"


class OpenAIImagesAdapter:
    """Synchronous Image API adapter (generate + edit, `gpt-image-2` friendly)."""

    def __init__(
        self,
        *,
        config: AdapterRuntimeConfig,
        store: Any,
        client: httpx.AsyncClient | None = None,
        downloader: SafeDownloader | None = None,
        limits: MediaLimits | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._limits = limits or store.limits
        self._client = client
        self._downloader = downloader
        self._owns_client = client is None
        self._owns_downloader = downloader is None

    @property
    def kind(self) -> str:
        return ADAPTER_OPENAI_IMAGES

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        if self._owns_downloader and self._downloader is not None:
            await self._downloader.aclose()

    # ── executor contract ────────────────────────────────────────────────────

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit:
        if not self._config.model:
            # A non-MCP Images job must resolve to a real provider model; the
            # durable catalog entry id must never be sent upstream and an empty
            # value must fail closed before any provider call (§11.3/§16.3).
            raise MediaConfigError(f"image profile {job.profile!r} resolves to no provider model")
        request = request_from_job(job)
        if request.operation.value == "edit":
            if not self._config.supports_edit:
                raise UnsupportedOperationError("edit")
            return (await self._edit(job, request)).media
        return (await self._generate(job, request)).media

    async def poll(self, job: ImageGenerationJob) -> Any:
        # The Images API is synchronous; a POLLING job can never be routed here.
        raise UnsupportedOperationError("poll")

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        # The Images API exposes no remote cancellation.
        return False

    # ── implementation ───────────────────────────────────────────────────────

    def _timeout(self, job: ImageGenerationJob) -> httpx.Timeout:
        return httpx.Timeout(job.read_timeout_seconds, connect=job.connect_timeout_seconds)

    def _headers(self) -> dict[str, str]:
        """Auth + safe extra headers only — never a forced ``Content-Type``.

        Generation requests pass ``json=payload`` so httpx sets
        ``application/json``; edit requests pass ``files=`` so httpx generates
        the ``multipart/form-data`` boundary itself (§10.2).  Forcing
        ``application/json`` on a ``files=`` request would produce an invalid
        multipart body.
        """
        return {
            **build_auth_headers(self._config.auth_style, self._config.api_key),
            **(self._config.extra_headers or {}),
        }

    async def _client_for(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0, trust_env=False)
        return self._client

    async def _downloader_for(self) -> SafeDownloader:
        if self._downloader is None:
            self._downloader = SafeDownloader(limits=self._limits, read_timeout=1800.0)
        return self._downloader

    def _body(self, request: ImageGenerationRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            # The resolved provider model, never the durable catalog entry id
            # (an empty resolved model already failed closed in ``run``).
            "model": self._config.model,
            "prompt": request.prompt,
            "n": max(1, request.count),
        }
        if request.size:
            body["size"] = request.size
        if request.quality:
            body["quality"] = request.quality
        if self._config.style:
            body["style"] = self._config.style
        if self._config.response_format:
            body["response_format"] = self._config.response_format
        for key, value in (request.provider_options or {}).items():
            body.setdefault(key, value)
        return body

    def _classify_post_failure(self, action: str, exc: Exception) -> MediaError:
        """Classify a POST transport failure (§11.5).

        Read/write-phase failures after the request may have been accepted are
        ambiguous — the provider may bill and process the job — so the worker
        transitions the job to ``unknown``.  Definite pre-connect/unaccepted
        failures (DNS, connection refused, connect timeout) remain failures.
        """
        if is_ambiguous_transport_failure(exc):
            return AmbiguousSubmitError(
                f"{action} may have been accepted, but the outcome is unknown "
                "and cannot be reconciled locally."
            )
        return MediaError(f"{action} request error: {type(exc).__name__}")

    async def _generate(
        self, job: ImageGenerationJob, request: ImageGenerationRequest
    ) -> AdapterResult:
        url = join_api_path(self._config.base_url, GENERATIONS_PATH)
        payload = self._body(request)
        client = await self._client_for()
        try:
            response = await client.post(
                url, headers=self._headers(), json=payload, timeout=self._timeout(job)
            )
        except httpx.HTTPError as exc:
            raise self._classify_post_failure("Image generation", exc) from exc
        raise_for_status(response, "Image generation")
        data = response.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            raise MediaError("Image provider returned no images.")
        response_id = str(data.get("id") or "")
        media = [
            await self._materialize(job, item, remote_response_id=response_id)
            for item in items
            if isinstance(item, dict)
        ]
        if not media:
            raise MediaError("Image provider returned no images.")
        return AdapterResult(
            media=media,
            remote_response_id=response_id,
        )

    async def _edit(
        self, job: ImageGenerationJob, request: ImageGenerationRequest
    ) -> AdapterResult:
        url = join_api_path(self._config.base_url, EDITS_PATH)
        sources, mask = validate_edit_inputs(self._store, job, limits=self._limits)
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, source in enumerate(sources):
            files.append(
                (
                    "image",
                    (f"source_{index}.png", source.data, source.mime_type),
                )
            )
        data: dict[str, Any] = {
            # The resolved provider model, never the durable catalog entry id
            # (an empty resolved model already failed closed in ``run``).
            "model": self._config.model,
            "prompt": request.prompt,
            "n": max(1, request.count),
        }
        if request.size:
            data["size"] = request.size
        if mask is not None:
            files.append(("mask", ("mask.png", mask.data, mask.mime_type)))
        client = await self._client_for()
        try:
            response = await client.post(
                url,
                headers=self._headers(),
                files=files,
                data=data,
                timeout=self._timeout(job),
            )
        except httpx.HTTPError as exc:
            raise self._classify_post_failure("Image edit", exc) from exc
        raise_for_status(response, "Image edit")
        body = response.json()
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            raise MediaError("Image provider returned no edited images.")
        response_id = str(body.get("id") or "")
        media = [
            await self._materialize(job, item, remote_response_id=response_id)
            for item in items
            if isinstance(item, dict)
        ]
        if not media:
            raise MediaError("Image provider returned no edited images.")
        return AdapterResult(
            media=media,
            remote_response_id=response_id,
        )

    async def _materialize(
        self,
        job: ImageGenerationJob,
        item: dict[str, Any],
        *,
        remote_response_id: str = "",
    ) -> MediaInput:
        """Decode base64 or safe-download a temporary URL (§10.2).

        ``remote_response_id`` is the provider's own response id and is carried
        onto each :class:`MediaInput` so the persisted artifact can record it
        as provenance (§10.5).
        """
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64:
            try:
                data = base64.b64decode(b64)
            except Exception as exc:
                raise MediaError("Image provider returned malformed base64.") from exc
            return MediaInput(
                data=data,
                mime_type="image/png",
                remote_response_id=remote_response_id,
                remote_asset_id=str(item.get("asset_id") or ""),
                revised_prompt=str(item.get("revised_prompt") or ""),
            )
        src = item.get("url")
        if isinstance(src, str) and src:
            downloader = await self._downloader_for()
            result = await downloader.download(src)
            return MediaInput(
                data=result.data,
                mime_type=result.mime_type,
                remote_response_id=remote_response_id,
                remote_asset_id=str(item.get("asset_id") or ""),
                revised_prompt=str(item.get("revised_prompt") or ""),
            )
        raise MediaError("Image item had neither `b64_json` nor `url`.")


__all__ = ["EDITS_PATH", "GENERATIONS_PATH", "OpenAIImagesAdapter"]
