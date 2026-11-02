"""Text retrieval embeddings using NVIDIA NIM's OpenAI-shaped HTTP API."""

from __future__ import annotations

from typing import Any

from deeptutor.services.embedding.validation import validate_embedding_batch

from .base import EmbeddingRequest, EmbeddingResponse
from .openai_compatible import OpenAICompatibleEmbeddingAdapter


class NvidiaNIMEmbeddingAdapter(OpenAICompatibleEmbeddingAdapter):
    """Opt in to query/passage roles without changing generic custom profiles."""

    SUPPORTS_INPUT_TYPE = True
    PROVIDER_NAME = "nvidia_nim"
    DEFAULT_MODEL = "nvidia/nemotron-3.5-embed-8b"
    MODELS_INFO = {DEFAULT_MODEL: {"default": 4096, "dimensions": []}}

    def _should_send_dimensions(self, model_name: str | None) -> bool:
        """Send a requested dimension unless the profile explicitly opts out."""
        del model_name
        return self.send_dimensions is not False

    def _build_payload(self, request: EmbeddingRequest) -> dict[str, Any]:
        """Translate retrieval roles for text-only NIM requests."""
        if request.contents is not None:
            raise ValueError("NVIDIA NIM text embeddings do not support multimodal contents.")
        roles = {
            None: "passage",  # Unqualified calls include connection checks.
            "search_document": "passage",
            "search_query": "query",
            "passage": "passage",
            "query": "query",
        }
        if request.input_type not in roles:
            raise ValueError(f"Unsupported NVIDIA NIM retrieval role: {request.input_type!r}")
        dimension = request.dimensions or self.dimensions
        model = request.model or self.model
        if model == self.DEFAULT_MODEL and dimension:
            if type(dimension) is not int or not 1 <= dimension <= 4096:
                raise ValueError(
                    "Nemotron 3.5 Embed 8B dimensions must be an integer from 1 to 4096."
                )
        if request.encoding_format not in {None, "float"}:
            raise ValueError("NVIDIA NIM text embeddings require float encoding.")
        payload = super()._build_payload(request)
        payload["input_type"] = roles[request.input_type]
        payload["encoding_format"] = "float"
        if request.truncate is not None:
            payload["truncate"] = "END" if request.truncate else "NONE"
        return payload

    @staticmethod
    def _extract_embeddings_from_response(data: Any) -> list[list[float]]:
        """Restore input order and reject ambiguous provider response indices."""
        if isinstance(data, dict) and "error" in data:
            return OpenAICompatibleEmbeddingAdapter._extract_embeddings_from_response(data)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("NVIDIA NIM response must contain a nonempty data array.")
        by_index = {}
        for row in rows:
            index = row.get("index") if isinstance(row, dict) else None
            if type(index) is not int or index < 0 or index in by_index:
                raise ValueError(
                    "NVIDIA NIM response has missing, invalid or duplicate vector indices."
                )
            by_index[index] = row.get("embedding")
        if set(by_index) != set(range(len(rows))):
            raise ValueError("NVIDIA NIM response has noncontiguous vector indices.")
        return validate_embedding_batch(
            [by_index[index] for index in range(len(rows))],
            expected_count=len(rows),
            binding="nvidia_nim",
            model=str(data.get("model") or ""),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Use the shared transport, then validate text/vector correspondence."""
        if not request.texts:
            self._build_payload(request)
            return EmbeddingResponse([], request.model or self.model, 0, {})
        response = await super().embed(request)
        if len(response.embeddings) != len(request.texts):
            raise ValueError(
                "NVIDIA NIM returned an unexpected number of vectors for the input batch."
            )
        expected_dim = request.dimensions or self.dimensions
        if expected_dim and self.send_dimensions is not False:
            if response.dimensions != expected_dim:
                raise ValueError(
                    f"NVIDIA NIM returned dimension {response.dimensions}; expected {expected_dim}."
                )
        return response

    def get_model_info(self) -> dict[str, Any]:
        """Advertise text support even when the upstream model accepts images."""
        return {
            **super().get_model_info(),
            "provider": self.PROVIDER_NAME,
            "multimodal": False,
            "supports_variable_dimensions": self.model == self.DEFAULT_MODEL,
        }
