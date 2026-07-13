"""OpenAI-compatible embedding adapter for OpenAI, Azure, HuggingFace, LM Studio, etc."""

import json
import logging
from typing import Any, Dict

import httpx

from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled

from .base import (
    BaseEmbeddingAdapter,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingResponse,
    looks_like_multimodal_embedding_model,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbeddingAdapter(BaseEmbeddingAdapter):
    NO_KEY_SENTINEL = "sk-no-key-required"

    MODELS_INFO = {
        "text-embedding-3-large": {"default": 3072, "dimensions": [256, 512, 1024, 3072]},
        "text-embedding-3-small": {"default": 1536, "dimensions": [512, 1536]},
        "text-embedding-ada-002": 1536,
    }

    def _auth_api_key(self) -> str:
        """Return a real API key, suppressing local-provider placeholder keys."""
        key = str(self.api_key or "").strip()
        if key == self.NO_KEY_SENTINEL:
            return ""
        return key

    @staticmethod
    def _extract_embeddings_from_response(data: Any) -> list[list[float]]:
        """
        Extract embeddings from different OpenAI-compatible response schemas.

        Supported shapes include:
        - {"data": [{"embedding": [...]}, ...]}
        - {"embeddings": [[...], ...]}
        - {"embedding": [...]}  (Ollama /api/embeddings)
        - {"result": {"data": [{"embedding": [...]}, ...]}}
        - {"output": {"embeddings": [[...], ...]}}
        """
        if not isinstance(data, dict):
            raise ValueError(f"Embedding response is not a JSON object: type={type(data).__name__}")

        # Some providers return HTTP 200 with {"error": ...} payload.
        if "error" in data:
            err = data.get("error")
            if isinstance(err, dict):
                msg = (
                    err.get("message")
                    or err.get("msg")
                    or err.get("detail")
                    or json.dumps(err, ensure_ascii=False)
                )
                code = err.get("code")
                etype = err.get("type")
                raise ValueError(
                    f"Embedding provider returned error payload: "
                    f"message={msg}, code={code}, type={etype}"
                )
            raise ValueError(f"Embedding provider returned error payload: {err}")

        candidates = []
        # Standard OpenAI schema
        if isinstance(data.get("data"), list):
            candidates.append(data["data"])
        # Common proxy schema
        if isinstance(data.get("embeddings"), list):
            candidates.append(data["embeddings"])
        # Ollama /api/embeddings returns singular "embedding" as a flat vector
        if isinstance(data.get("embedding"), list):
            emb = data["embedding"]
            if emb and isinstance(emb[0], (int, float)):
                candidates.append([emb])
            else:
                candidates.append(emb)
        # Nested result/output variants
        result = data.get("result")
        if isinstance(result, dict):
            if isinstance(result.get("data"), list):
                candidates.append(result["data"])
            if isinstance(result.get("embeddings"), list):
                candidates.append(result["embeddings"])
        output = data.get("output")
        if isinstance(output, dict):
            if isinstance(output.get("data"), list):
                candidates.append(output["data"])
            if isinstance(output.get("embeddings"), list):
                candidates.append(output["embeddings"])

        for c in candidates:
            if not c:
                continue
            first = c[0]
            # list of {"embedding":[...]}
            if isinstance(first, dict) and "embedding" in first:
                return [item.get("embedding") or [] for item in c if isinstance(item, dict)]
            # list of vectors [[...], ...]
            if isinstance(first, list):
                return [item for item in c if isinstance(item, list)]

        keys = sorted(list(data.keys()))
        raise ValueError(
            "Cannot parse embeddings from response JSON. "
            f"Top-level keys={keys}, expected one of: data/embedding/embeddings/result/output."
        )

    _MAX_RETRIES = 5
    _RETRY_BACKOFF = 1.0
    _RATE_LIMIT_BACKOFF = 5.0

    def _should_send_dimensions(self, model_name: str | None) -> bool:
        """Decide whether to attach `dimensions` to the request payload.

        Tri-state semantics driven by `self.send_dimensions`:
        * ``True``  -> always send (user explicitly opted in)
        * ``False`` -> never send (user explicitly opted out)
        * ``None``  -> auto: send for known model families that accept the
          OpenAI-style ``dimensions`` parameter — OpenAI ``text-embedding-3*``,
          Qwen3-Embedding, Qwen3-VL-Embedding.
        """
        if self.send_dimensions is True:
            return True
        if self.send_dimensions is False:
            return False
        if not model_name:
            return False
        lname = model_name.lower()
        if lname.startswith("text-embedding-3"):
            return True
        if "qwen3-embedding" in lname or "qwen3-vl-embedding" in lname:
            return True
        return False

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        import asyncio

        headers = {"Content-Type": "application/json"}
        api_key = self._auth_api_key()
        if self.api_version:
            if api_key:
                headers["api-key"] = api_key
        elif api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})

        # Multimodal: pass `contents` through as `input` only for model names
        # that clearly advertise image/vision embedding support. This prevents
        # image indexing from accidentally hitting ordinary text-embedding
        # models just because the provider family has some multimodal models.
        model = request.model or self.model
        if request.contents and not looks_like_multimodal_embedding_model(model):
            raise ValueError(
                f"OpenAI-compatible embedding model '{model}' does not support "
                "multimodal `contents`."
            )
        input_payload: Any = request.contents if request.contents else request.texts

        payload = {
            "input": input_payload,
            "model": model,
            "encoding_format": request.encoding_format or "float",
        }

        # `dimensions` is opt-in. The user's `send_dimensions` flag wins when set
        # explicitly (True/False); otherwise we fall back to a model-family
        # heuristic since only OpenAI's text-embedding-3* family officially
        # supports the param — other providers (e.g. Qwen text-embedding-v4 via
        # litellm gateway) return HTTP 400 if we send it.
        dim_value = request.dimensions or self.dimensions
        if dim_value and self._should_send_dimensions(model):
            payload["dimensions"] = dim_value

        # URL transparency: hit `base_url` verbatim. Azure's `?api-version=...`
        # is a query param (not a path component) so we still append it.
        url = self.base_url
        if self.api_version:
            if "?" not in url:
                url += f"?api-version={self.api_version}"
            else:
                url += f"&api-version={self.api_version}"

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        timeout = httpx.Timeout(
            connect=10.0,
            read=max(self.request_timeout, 60),
            write=10.0,
            pool=10.0,
        )
        last_exc: Exception | None = None
        for attempt in range(1 + self._MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout, verify=not disable_ssl_verify_enabled()
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    # Handle rate limiting (429) with retry
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", 0))
                        wait = max(retry_after, self._RATE_LIMIT_BACKOFF * (2**attempt))
                        logger.warning(
                            f"Rate limited (429) on attempt {attempt + 1}/{1 + self._MAX_RETRIES}, "
                            f"retrying in {wait:.1f}s..."
                        )
                        await asyncio.sleep(wait)
                        last_exc = Exception("HTTP 429 Too Many Requests")
                        continue

                    if response.status_code >= 400:
                        body_text = response.text
                        logger.error(f"HTTP {response.status_code} from {url}: {body_text[:2000]}")
                        raise EmbeddingProviderError(
                            f"Embedding provider returned HTTP {response.status_code}",
                            status=response.status_code,
                            body=body_text,
                            model=model,
                            url=url,
                            provider="openai_compat",
                        )

                    # A 2xx response with non-JSON body usually means the
                    # endpoint/model pairing is wrong or a gateway routed us to
                    # an HTML page. Surface that as structured diagnostics.
                    try:
                        data = response.json()
                    except (json.JSONDecodeError, ValueError) as exc:
                        body_text = response.text
                        content_type = response.headers.get("content-type", "")
                        body_preview = body_text.strip()[:200] or "<empty body>"
                        hint = ""
                        if not body_text.strip():
                            hint = (
                                " The response body was empty — the endpoint may "
                                "not support embeddings or the selected model "
                                "may not be an embedding model."
                            )
                        elif (
                            "text/html" in content_type.lower()
                            or body_preview.lstrip().startswith("<")
                        ):
                            hint = (
                                " The response was HTML, not JSON — the URL is "
                                "likely wrong or the gateway does not expose "
                                "`/v1/embeddings`."
                            )
                        raise EmbeddingProviderError(
                            (
                                f"Embedding provider returned non-JSON response "
                                f"(content-type={content_type!r}): {exc}.{hint}"
                            ),
                            status=response.status_code,
                            body=body_text,
                            model=model,
                            url=url,
                            provider="openai_compat",
                        ) from exc
                break
            except httpx.TransportError as exc:
                # httpx.TransportError covers all transient transport-layer
                # failures: ConnectError, ReadError, WriteError, ConnectTimeout,
                # ReadTimeout, WriteTimeout, PoolTimeout, RemoteProtocolError, etc.
                # Retrying any of these with backoff is safe and obviates the
                # need to keep extending an explicit allow-list.
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    wait = self._RETRY_BACKOFF * (2**attempt)
                    logger.warning(
                        f"Embedding request transport error ({type(exc).__name__}: {exc}) "
                        f"on attempt {attempt + 1}/{1 + self._MAX_RETRIES}, "
                        f"retrying in {wait:.1f}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"Embedding request failed after {1 + self._MAX_RETRIES} attempts "
                        f"({type(exc).__name__}: {exc})"
                    )
                    raise
        else:
            if last_exc:
                raise last_exc

        embeddings = self._extract_embeddings_from_response(data)
        if not embeddings:
            raise ValueError("Embedding response parsed successfully but no vectors were found.")

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions
        model_name = data.get("model") if isinstance(data, dict) else None
        if not model_name:
            model_name = model

        if expected_dims and actual_dims != expected_dims:
            logger.warning(
                f"Dimension mismatch: expected {expected_dims}, got {actual_dims}. "
                f"Model '{model_name}' may not support custom dimensions."
            )

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {model_name}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=data.get("usage", {}) if isinstance(data, dict) else {},
        )

    def get_model_info(self) -> Dict[str, Any]:
        model_info = self.MODELS_INFO.get(self.model, self.dimensions)

        if isinstance(model_info, dict):
            return {
                "model": self.model,
                "dimensions": model_info.get("default", self.dimensions),
                "supported_dimensions": model_info.get("dimensions", []),
                "supports_variable_dimensions": len(model_info.get("dimensions", [])) > 1,
                "multimodal": looks_like_multimodal_embedding_model(self.model),
                "provider": "openai_compatible",
            }
        else:
            return {
                "model": self.model,
                "dimensions": model_info or self.dimensions,
                "supports_variable_dimensions": False,
                "multimodal": looks_like_multimodal_embedding_model(self.model),
                "provider": "openai_compatible",
            }
