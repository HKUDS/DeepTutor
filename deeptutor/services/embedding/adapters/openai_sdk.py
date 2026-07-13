"""Legacy embedding adapter using AsyncOpenAI.

Public Settings providers use exact endpoint URLs and raw HTTP adapters so the
URL shown in Settings is the URL sent on the wire. This SDK adapter is retained
for old configs/tests that intentionally depend on AsyncOpenAI semantics.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from openai import APIConnectionError, APIError, APIStatusError, AsyncOpenAI

from deeptutor.services.llm.openai_http_client import openai_client_kwargs

from .base import (
    BaseEmbeddingAdapter,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingResponse,
)

logger = logging.getLogger(__name__)


class OpenAISDKEmbeddingAdapter(BaseEmbeddingAdapter):
    """Embedding adapter using the official ``AsyncOpenAI`` client."""

    def _should_send_dimensions(self, model_name: str | None) -> bool:
        """Mirror of the heuristic in :mod:`openai_compatible`.

        Tri-state ``self.send_dimensions``: ``True`` always send, ``False``
        never send, ``None`` auto by model family.
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

    def _build_client(self) -> AsyncOpenAI:
        # OpenRouter / custom gateways often don't validate the key, but the
        # SDK refuses to construct without one. Use a placeholder when empty.
        return AsyncOpenAI(
            api_key=self.api_key or "sk-no-key-required",
            base_url=self.base_url,
            timeout=max(self.request_timeout, 60),
            default_headers=(
                {str(k): str(v) for k, v in self.extra_headers.items()}
                if self.extra_headers
                else None
            ),
            max_retries=2,
            **openai_client_kwargs(timeout=max(self.request_timeout, 60)),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if request.contents:
            raise ValueError(
                "openai_sdk adapter does not support multimodal `contents`. "
                "Pick a multimodal-capable provider (cohere, aliyun)."
            )

        model = request.model or self.model
        kwargs: Dict[str, Any] = {
            "model": model,
            "input": request.texts,
            "encoding_format": request.encoding_format or "float",
        }
        dim_value = request.dimensions or self.dimensions
        if dim_value and self._should_send_dimensions(model):
            kwargs["dimensions"] = dim_value

        client = self._build_client()
        try:
            response = await client.embeddings.create(**kwargs)
        except APIStatusError as exc:
            try:
                body = exc.response.text
            except Exception:
                body = str(exc)
            raise EmbeddingProviderError(
                f"OpenAI SDK request failed: {exc}",
                status=getattr(exc, "status_code", None),
                body=body,
                model=model,
                url=self.base_url,
                provider="openai_sdk",
            ) from exc
        except APIConnectionError as exc:
            raise EmbeddingProviderError(
                f"OpenAI SDK connection error: {exc}",
                model=model,
                url=self.base_url,
                provider="openai_sdk",
            ) from exc
        except APIError as exc:
            raise EmbeddingProviderError(
                f"OpenAI SDK API error: {exc}",
                model=model,
                url=self.base_url,
                provider="openai_sdk",
            ) from exc
        finally:
            try:
                await client.close()
            except Exception:
                pass

        embeddings = [list(item.embedding) for item in response.data]
        if not embeddings:
            raise ValueError("openai_sdk returned an empty data list.")

        actual_dims = len(embeddings[0])
        usage_obj = getattr(response, "usage", None)
        if usage_obj is None:
            usage: Dict[str, Any] = {}
        elif hasattr(usage_obj, "model_dump"):
            usage = usage_obj.model_dump()
        elif isinstance(usage_obj, dict):
            usage = usage_obj
        else:
            usage = {}

        logger.info(
            f"Generated {len(embeddings)} embeddings via openai SDK "
            f"(model={model}, dim={actual_dims}, base_url={self.base_url})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=getattr(response, "model", None) or model,
            dimensions=actual_dims,
            usage=usage,
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "dimensions": self.dimensions,
            "supports_variable_dimensions": False,
            "multimodal": False,
            "provider": "openai_sdk",
        }
