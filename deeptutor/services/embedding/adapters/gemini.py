"""Gemini embeddings via the native batch API with legacy compatibility."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
import math
from typing import Any, Dict
from urllib.parse import parse_qsl, unquote, urlparse

import httpx

from deeptutor.services.config.embedding_endpoint import (
    GEMINI_API_HOST,
    SENSITIVE_ENDPOINT_QUERY_KEYS,
    redact_embedding_endpoint_for_display,
)
from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled

from .base import EmbeddingProviderError, EmbeddingRequest, EmbeddingResponse
from .openai_compatible import OpenAICompatibleEmbeddingAdapter

logger = logging.getLogger(__name__)


class GeminiEmbeddingAdapter(OpenAICompatibleEmbeddingAdapter):
    """Use Gemini's native API while preserving saved OpenAI-compatible setups."""

    SUPPORTS_INPUT_TYPE = True

    # ``multimodal`` states what the model maps into its embedding space, and
    # is the single place that decides it: ``get_model_info`` reports it to
    # Settings, and ``_embed_native`` refuses ``contents`` for a model that
    # says False rather than posting parts the endpoint will reject (#814).
    MODELS_INFO: dict[str, object] = {
        "gemini-embedding-2": {
            "default": 3072,
            "dimensions": [128, 256, 512, 768, 1536, 3072],
            "multimodal": True,
        },
        "gemini-embedding-2-preview": {
            "default": 3072,
            "dimensions": [128, 256, 512, 768, 1536, 3072],
            "multimodal": True,
        },
        "gemini-embedding-001": {
            "default": 3072,
            "dimensions": [128, 256, 512, 768, 1536, 3072],
            "multimodal": False,
        },
    }

    _QUERY_PREFIX = "task: search result | query: "
    _DOCUMENT_PREFIX = "title: none | text: "
    _NATIVE_SUFFIX = ":batchEmbedContents"
    _SENSITIVE_QUERY_KEYS = SENSITIVE_ENDPOINT_QUERY_KEYS

    @staticmethod
    def _model_id(model_name: str | None) -> str:
        normalized = str(model_name or "").strip()
        return normalized.removeprefix("models/")

    @classmethod
    def _is_embedding2(cls, model_name: str | None) -> bool:
        """Return whether a model uses Gemini Embedding 2 prompt instructions."""
        return cls._model_id(model_name).lower().startswith("gemini-embedding-2")

    @classmethod
    def _format_retrieval_texts(
        cls,
        texts: list[str],
        input_type: str | None,
    ) -> list[str]:
        """Return new strings using Gemini 2's asymmetric retrieval format."""
        if input_type == "search_query":
            return [f"{cls._QUERY_PREFIX}{text}" for text in texts]
        if input_type == "search_document":
            return [f"{cls._DOCUMENT_PREFIX}{text}" for text in texts]
        return list(texts)

    @classmethod
    def _native_endpoint_model(cls, endpoint: str | None) -> str | None:
        path = urlparse(str(endpoint or "")).path.rstrip("/")
        if not path.endswith(cls._NATIVE_SUFFIX) or "/models/" not in path:
            return None
        model_segment = path.rsplit("/models/", 1)[1]
        return unquote(model_segment.removesuffix(cls._NATIVE_SUFFIX))

    def _should_send_dimensions(self, model_name: str | None) -> bool:
        """Only send OpenAI-style dimensions when a legacy user opted in."""
        del model_name
        return self.send_dimensions is True

    @staticmethod
    def _task_type(input_type: str | None) -> str | None:
        return {
            "search_query": "RETRIEVAL_QUERY",
            "search_document": "RETRIEVAL_DOCUMENT",
        }.get(input_type)

    @staticmethod
    def _normalize_vectors(vectors: list[list[float]]) -> list[list[float]]:
        """L2-normalize vectors without mutating the provider response."""
        normalized: list[list[float]] = []
        for vector in vectors:
            norm = math.sqrt(sum(value * value for value in vector))
            normalized.append([value / norm for value in vector] if norm else list(vector))
        return normalized

    @classmethod
    def _redacted_url(cls, url: str) -> str:
        del cls
        return redact_embedding_endpoint_for_display(url)

    def _redacted_body(
        self,
        body: str,
        *,
        api_key: str,
        url: str,
        sensitive_texts: list[str],
    ) -> str:
        secrets = [api_key, *sensitive_texts]
        secrets.extend(
            value
            for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True)
            if key.lower() in self._SENSITIVE_QUERY_KEYS
        )
        for key, value in self.extra_headers.items():
            if str(key).lower() not in {"authorization", "x-goog-api-key"}:
                continue
            secret = str(value)
            secrets.extend([secret, secret.encode("unicode_escape").decode("ascii")])
            if secret.lower().startswith("bearer "):
                token = secret[7:].strip()
                secrets.extend([token, token.encode("unicode_escape").decode("ascii")])
        redacted = body
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted[:500]

    @classmethod
    def _model_info(cls, model_name: str | None) -> dict[str, Any] | None:
        """The MODELS_INFO row for a model, falling back across the 2.x line."""
        model_id = cls._model_id(model_name)
        info = cls.MODELS_INFO.get(model_id)
        if info is None and cls._is_embedding2(model_id):
            info = cls.MODELS_INFO["gemini-embedding-2"]
        return info if isinstance(info, dict) else None

    @classmethod
    def _supports_multimodal(cls, model_name: str | None) -> bool:
        info = cls._model_info(model_name)
        return bool(info.get("multimodal", False)) if info else False

    @staticmethod
    def _inline_data(value: str, kind: str) -> dict[str, Any]:
        """Turn one ``data:`` URI into Gemini's ``inlineData`` part.

        Only ``data:`` URIs are accepted. `batchEmbedContents` has no remote-URL
        part — the alternative to inline bytes is a File API upload — so an
        http(s) value could only be honoured by fetching it here, and this
        repository has already settled that question against doing so (see
        ``services/llm/multimodal._resolve_local_attachment_url``: sync network
        IO on an async path, and an SSRF footgun). Callers hand us bytes.
        """
        text = str(value or "").strip()
        if not text.startswith("data:"):
            raise ValueError(
                f"Gemini embeddings need inline bytes for '{kind}' content, but got "
                f"{'an http(s) URL' if text[:4].lower() == 'http' else 'an unsupported value'}. "
                "Pass a data: URI (base64) instead."
            )
        header, _, payload = text.partition(",")
        if not payload:
            raise ValueError(f"Malformed data: URI for '{kind}' content — no base64 payload.")
        mime_type = header[len("data:") :].split(";", 1)[0].strip()
        if not mime_type:
            raise ValueError(f"Malformed data: URI for '{kind}' content — no MIME type.")
        return {"inlineData": {"mimeType": mime_type, "data": payload}}

    @classmethod
    def _content_parts(cls, item: dict[str, Any]) -> list[dict[str, Any]]:
        """Map one ``{"text"|"image"|"video"|"audio": value}`` item to parts."""
        parts: list[dict[str, Any]] = []
        for kind, value in item.items():
            if kind == "text":
                parts.append({"text": str(value or "")})
            elif kind in {"image", "video", "audio", "document"}:
                parts.append(cls._inline_data(str(value or ""), kind))
            else:
                raise ValueError(f"Gemini embeddings do not support content type '{kind}'.")
        return parts

    def _native_multimodal_payload(
        self,
        request: EmbeddingRequest,
        model: str,
    ) -> dict[str, Any]:
        """Build ``batchEmbedContents`` requests from provider-agnostic contents.

        One vector per content item, matching the Cohere adapter's reading of
        the same contract — except that Gemini maps every modality into one
        shared space, so ``enable_fusion`` genuinely works here: it folds every
        item's parts into a single content and returns one vector for the lot.
        """
        model_id = self._model_id(model)
        items = [item for item in (request.contents or []) if isinstance(item, dict)]
        dimension = request.dimensions or self.dimensions

        def _request(parts: list[dict[str, Any]]) -> dict[str, Any]:
            entry: dict[str, Any] = {
                "model": f"models/{model_id}",
                "content": {"parts": parts},
            }
            if dimension and self.send_dimensions is not False:
                entry["outputDimensionality"] = dimension
            return entry

        if request.enable_fusion:
            fused = [part for item in items for part in self._content_parts(item)]
            return {"requests": [_request(fused)] if fused else []}
        return {"requests": [_request(self._content_parts(item)) for item in items]}

    def _native_payload(
        self,
        request: EmbeddingRequest,
        model: str,
    ) -> dict[str, Any]:
        model_id = self._model_id(model)
        texts = (
            self._format_retrieval_texts(request.texts, request.input_type)
            if self._is_embedding2(model_id)
            else list(request.texts)
        )
        dimension = request.dimensions or self.dimensions
        task_type = self._task_type(request.input_type)
        native_requests: list[dict[str, Any]] = []
        for text in texts:
            item: dict[str, Any] = {
                "model": f"models/{model_id}",
                "content": {"parts": [{"text": text}]},
            }
            if dimension and self.send_dimensions is not False:
                item["outputDimensionality"] = dimension
            # Gemini Embedding 2 removed task_type in favour of prompt
            # instructions. The text-only 001 model still supports it.
            if task_type and not self._is_embedding2(model_id):
                item["taskType"] = task_type
            native_requests.append(item)
        return {"requests": native_requests}

    async def _embed_native(
        self,
        request: EmbeddingRequest,
        model: str,
    ) -> EmbeddingResponse:
        endpoint_model = self._native_endpoint_model(self.base_url)
        model_id = self._model_id(model)
        if endpoint_model != model_id:
            raise ValueError(
                f"Gemini endpoint model '{endpoint_model}' does not match selected "
                f"model '{model_id}'. Update the visible embedding Endpoint URL."
            )
        if request.contents and not self._supports_multimodal(model_id):
            raise ValueError(
                f"Gemini model '{model_id}' is text-only and cannot embed multimodal "
                "`contents`. Select gemini-embedding-2, which maps text, images, "
                "video, audio and documents into one space."
            )

        payload = (
            self._native_multimodal_payload(request, model_id)
            if request.contents
            else self._native_payload(request, model_id)
        )
        headers = {"Content-Type": "application/json"}
        api_key = self._auth_api_key()
        explicit_auth = {str(key).lower() for key in self.extra_headers} & {
            "authorization",
            "x-goog-api-key",
        }
        if api_key and not explicit_auth:
            if urlparse(str(self.base_url)).hostname == GEMINI_API_HOST:
                headers["x-goog-api-key"] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        headers.update({str(key): str(value) for key, value in self.extra_headers.items()})
        url = str(self.base_url)
        safe_url = self._redacted_url(url)
        timeout = httpx.Timeout(
            connect=10.0,
            read=max(self.request_timeout, 60),
            write=10.0,
            pool=10.0,
        )

        data: Any = None
        last_error: Exception | None = None
        for attempt in range(1 + self._MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    verify=not disable_ssl_verify_enabled(),
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 429:
                    try:
                        retry_after = float(response.headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0
                    wait = max(
                        retry_after,
                        self._RATE_LIMIT_BACKOFF * (2**attempt),
                    )
                    logger.warning(
                        "Gemini embedding rate limited on attempt %s/%s; retrying in %.1fs",
                        attempt + 1,
                        1 + self._MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    last_error = EmbeddingProviderError(
                        "Gemini embedding provider returned HTTP 429",
                        status=429,
                        model=model_id,
                        url=safe_url,
                        provider="gemini",
                    )
                    continue
                if response.status_code >= 400:
                    raise EmbeddingProviderError(
                        f"Gemini embedding provider returned HTTP {response.status_code}",
                        status=response.status_code,
                        body=self._redacted_body(
                            response.text,
                            api_key=api_key,
                            url=url,
                            sensitive_texts=request.texts,
                        ),
                        model=model_id,
                        url=safe_url,
                        provider="gemini",
                    )
                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise EmbeddingProviderError(
                        f"Gemini embedding provider returned non-JSON response: {exc}",
                        status=response.status_code,
                        body=self._redacted_body(
                            response.text,
                            api_key=api_key,
                            url=url,
                            sensitive_texts=request.texts,
                        ),
                        model=model_id,
                        url=safe_url,
                        provider="gemini",
                    ) from exc
                break
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self._MAX_RETRIES:
                    safe_error = self._redacted_body(
                        str(exc),
                        api_key=api_key,
                        url=url,
                        sensitive_texts=request.texts,
                    )
                    raise EmbeddingProviderError(
                        f"Gemini embedding transport error: {safe_error}",
                        model=model_id,
                        url=safe_url,
                        provider="gemini",
                    ) from None
                wait = self._RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    "Gemini embedding transport error on attempt %s/%s; retrying in %.1fs",
                    attempt + 1,
                    1 + self._MAX_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
        else:
            if last_error is not None:
                raise last_error

        raw_embeddings = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(raw_embeddings, list):
            raise ValueError("Gemini native embedding response is missing the `embeddings` list.")
        embeddings = [item.get("values") or [] for item in raw_embeddings if isinstance(item, dict)]
        if not embeddings or any(
            not isinstance(vector, list) or not vector for vector in embeddings
        ):
            raise ValueError("Gemini native embedding response contains no usable vectors.")
        # Count against what was actually posted, not against `request.texts`:
        # a multimodal turn carries no texts at all, and a fused one collapses
        # many items into a single vector.
        expected = len(payload.get("requests", []))
        if len(embeddings) != expected:
            raise ValueError(
                "Gemini native embedding response count does not match the request: "
                f"expected {expected}, got {len(embeddings)}."
            )

        requested_dimension = request.dimensions or self.dimensions
        if (
            request.normalized
            and model_id == "gemini-embedding-001"
            and requested_dimension
            and requested_dimension != 3072
        ):
            embeddings = self._normalize_vectors(embeddings)

        actual_dimension = len(embeddings[0])
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_id,
            dimensions=actual_dimension,
            usage=(data.get("usageMetadata", {}) if isinstance(data, dict) else {}),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed text through native Gemini or a saved legacy-compatible URL."""
        model = self._model_id(request.model or self.model)
        if self._native_endpoint_model(self.base_url) is not None:
            return await self._embed_native(request, model)

        prepared = request
        if not request.contents and self._is_embedding2(model):
            prepared = replace(
                request,
                model=model,
                texts=self._format_retrieval_texts(request.texts, request.input_type),
            )
        return await super().embed(prepared)

    def get_model_info(self) -> Dict[str, Any]:
        """Return Gemini embedding dimensions exposed to Settings diagnostics."""
        model_name = self._model_id(self.model)
        model_info = self._model_info(model_name)
        if model_info is None:
            return {
                "model": model_name,
                "dimensions": self.dimensions,
                "supported_dimensions": [],
                "supports_variable_dimensions": False,
                "multimodal": False,
                "provider": "gemini",
            }
        return {
            "model": model_name,
            "dimensions": model_info["default"],
            "supported_dimensions": list(model_info["dimensions"]),
            "supports_variable_dimensions": True,
            "multimodal": bool(model_info.get("multimodal", False)),
            "provider": "gemini",
        }
