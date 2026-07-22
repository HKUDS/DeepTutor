from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import threading
from threading import Lock
import time
from typing import Any
from uuid import uuid4

from .context_window_detection import detect_context_window
from .model_catalog import get_model_catalog_service
from .provider_runtime import (
    resolve_embedding_runtime_config,
    resolve_llm_runtime_config,
    resolve_search_runtime_config,
)


def _redact(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _coerce_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TestRun:
    id: str
    service: str
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    cancelled: bool = False

    def emit(self, kind: str, message: str, **extra: Any) -> None:
        payload = {
            "type": kind,
            "message": message,
            "timestamp": time.time(),
            **extra,
        }
        with self.lock:
            self.events.append(payload)

    def snapshot(self, start: int) -> list[dict[str, Any]]:
        with self.lock:
            return self.events[start:]


class ConfigTestRunner:
    _instance: "ConfigTestRunner | None" = None

    def __init__(self) -> None:
        self._runs: dict[str, TestRun] = {}
        self._lock = Lock()

    @classmethod
    def get_instance(cls) -> "ConfigTestRunner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self, service: str, catalog: dict[str, Any] | None = None) -> TestRun:
        run = TestRun(id=f"{service}-{uuid4().hex[:10]}", service=service)
        with self._lock:
            self._runs[run.id] = run
        resolved = catalog or get_model_catalog_service().load()
        thread = threading.Thread(target=self._run_sync, args=(run, resolved), daemon=True)
        thread.start()
        return run

    def get(self, run_id: str) -> TestRun:
        return self._runs[run_id]

    def cancel(self, run_id: str) -> None:
        self.get(run_id).cancelled = True

    def _run_sync(self, run: TestRun, catalog: dict[str, Any]) -> None:
        try:
            service = run.service
            profile = get_model_catalog_service().get_active_profile(catalog, service)
            model = get_model_catalog_service().get_active_model(catalog, service)

            run.emit("info", "Preparing configuration snapshot.")
            if profile:
                run.emit(
                    "config",
                    "Using active profile.",
                    profile={
                        "name": profile.get("name", ""),
                        "base_url": profile.get("base_url", ""),
                        "binding": profile.get("binding") or profile.get("provider"),
                        "api_key": _redact(str(profile.get("api_key", ""))),
                        "api_version": profile.get("api_version", ""),
                    },
                    model=model,
                )

            if service == "llm":
                asyncio.run(self._test_llm(run, catalog))
            elif service == "embedding":
                asyncio.run(self._test_embedding(run, model or {}, catalog))
            elif service == "search":
                self._test_search(run, catalog)
            elif service == "tts":
                asyncio.run(self._test_tts(run, catalog))
            elif service == "stt":
                asyncio.run(self._test_stt(run, catalog))
            elif service == "imagegen":
                asyncio.run(self._test_imagegen(run, catalog))
            elif service == "videogen":
                asyncio.run(self._test_videogen(run, catalog))
            else:
                raise ValueError(f"Unsupported service: {service}")
            if not run.cancelled and run.status == "running":
                run.status = "completed"
                run.emit("completed", f"{service.upper()} test completed successfully.")
        except Exception as exc:
            run.status = "failed"
            run.emit("failed", str(exc))

    def _persist_embedding_dimension(
        self,
        catalog: dict[str, Any],
        model: dict[str, Any],
        actual_dimension: int,
    ) -> dict[str, Any]:
        """Write the probe-detected dim onto the active embedding model entry.

        Called after every successful "Test connection" — the probe is the
        single source of truth, so any prior catalog dim is overwritten.
        Refreshes the embedding client singleton so subsequent embed calls
        use the new dim.
        """
        from deeptutor.services.embedding.client import reset_embedding_client

        service = get_model_catalog_service()
        if model is None:
            return catalog
        model["dimension"] = str(actual_dimension)
        saved = service.save(catalog)
        reset_embedding_client()
        return saved

    @staticmethod
    def _capabilities_from_adapter(adapter: Any, model_name: str) -> dict[str, Any]:
        """Normalize an adapter's static-model knowledge into a uniform shape.

        Adapters disagree on which keys they expose from ``get_model_info()``
        (Cohere/Ollama omit ``supported_dimensions`` even though the data is
        in their ``MODELS_INFO``). This helper folds both sources together
        so the SSE event payload is always the same shape.
        """
        info: dict[str, Any] = {}
        try:
            info = adapter.get_model_info() or {}
        except Exception:
            info = {}
        models_info = getattr(adapter, "MODELS_INFO", {}) or {}
        model_known = bool(model_name and model_name in models_info)

        raw_supported = info.get("supported_dimensions")
        if not isinstance(raw_supported, list):
            entry = models_info.get(model_name) if model_known else None
            if isinstance(entry, dict):
                raw_supported = entry.get("dimensions")
            else:
                raw_supported = None
        supported: list[int] = []
        if isinstance(raw_supported, list):
            for value in raw_supported:
                try:
                    supported.append(int(value))
                except (TypeError, ValueError):
                    continue

        default_raw = info.get("dimensions")
        try:
            default_dim = int(default_raw) if default_raw is not None else 0
        except (TypeError, ValueError):
            default_dim = 0

        return {
            "default_dim": default_dim,
            "supported_dimensions": supported,
            "supports_variable_dimensions": bool(info.get("supports_variable_dimensions")),
            "model_known": model_known,
        }

    async def _test_llm(self, run: TestRun, catalog: dict[str, Any]) -> None:
        from deeptutor.services.llm import clear_llm_config_cache, get_token_limit_kwargs
        from deeptutor.services.llm import complete as llm_complete
        from deeptutor.services.llm.config import LLMConfig

        clear_llm_config_cache()
        run.emit("info", "Loading LLM config from the active catalog selection.")
        resolved = resolve_llm_runtime_config(catalog=catalog)
        llm_config = LLMConfig(
            model=resolved.model,
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            effective_url=resolved.effective_url,
            binding=resolved.binding,
            provider_name=resolved.provider_name,
            provider_mode=resolved.provider_mode,
            api_version=resolved.api_version,
            extra_headers=resolved.extra_headers,
            reasoning_effort=resolved.reasoning_effort,
        )
        run.emit(
            "info", f"Resolved model `{llm_config.model}` with binding `{llm_config.binding}`."
        )
        run.emit("info", f"Request target: {llm_config.base_url}")
        # Reasoning models spend part of the budget on internal thinking;
        # too tight a cap makes them return empty content. Configurable
        # via diagnostics.llm_probe.max_tokens in agents.yaml.
        from .loader import get_agent_params

        probe_params = get_agent_params("llm_probe")
        max_tokens = _coerce_int(probe_params.get("max_tokens"), 1024)
        temperature = _coerce_float(probe_params.get("temperature"), 0.1)
        token_kwargs: dict[str, Any] = get_token_limit_kwargs(
            llm_config.model, max_tokens=max_tokens
        )
        run.emit("info", f"Token options: {json.dumps(token_kwargs)}")
        if llm_config.reasoning_effort:
            run.emit("info", f"Reasoning effort: {llm_config.reasoning_effort}")
        response = await llm_complete(
            model=llm_config.model,
            prompt="Say 'OK' and identify the model you are using.",
            system_prompt="Respond briefly but include your model identity if possible.",
            binding=llm_config.binding,
            api_key=llm_config.api_key or "sk-no-key-required",
            base_url=llm_config.effective_url or llm_config.base_url or "",
            api_version=llm_config.api_version,
            temperature=temperature,
            extra_headers=llm_config.extra_headers,
            reasoning_effort=llm_config.reasoning_effort,
            **token_kwargs,
        )
        snippet = (response or "").strip()
        run.emit("response", "Received LLM response.", snippet=snippet[:400])
        if not snippet:
            raise ValueError("LLM returned an empty response.")
        run.emit(
            "info",
            (
                "Basic LLM completion succeeded. Chat additionally validates "
                "streaming and provider tool compatibility at runtime."
            ),
        )

        run.emit("info", "Detecting model context window.")
        detection = await detect_context_window(
            llm_config,
            on_log=lambda message: run.emit("info", message),
        )
        run.emit(
            "context_window",
            (f"Detected context window {detection.context_window} tokens ({detection.source})."),
            context_window=detection.context_window,
            source=detection.source,
            detail=detection.detail,
            detected_at=detection.detected_at,
        )
        run.emit(
            "info",
            "Context window detection is available in Settings and was not written automatically.",
        )

    async def _test_embedding(
        self, run: TestRun, model: dict[str, Any], catalog: dict[str, Any]
    ) -> None:
        from deeptutor.services.embedding.client import EmbeddingClient
        from deeptutor.services.embedding.config import EmbeddingConfig

        run.emit("info", "Loading embedding config from the active catalog selection.")
        resolved = resolve_embedding_runtime_config(catalog=catalog)
        catalog_dim = _coerce_int(model.get("dimension"), 0, minimum=0)
        # Force the smoke probe to send NO `dimensions=` parameter so we get
        # the model's native max dim back. If we used the configured dim,
        # Matryoshka models (OpenAI text-embedding-3-*, Cohere embed-v4,
        # Jina v3/v4, DashScope qwen3-vl-embedding) would just truncate and
        # return whatever we asked for — making "detected_dim" meaningless.
        config = EmbeddingConfig(
            model=resolved.model,
            api_key=resolved.api_key,
            base_url=resolved.base_url,
            effective_url=resolved.effective_url,
            binding=resolved.binding,
            provider_name=resolved.provider_name,
            provider_mode=resolved.provider_mode,
            api_version=resolved.api_version,
            extra_headers=resolved.extra_headers,
            dim=0,
            send_dimensions=False,
            request_timeout=max(1, resolved.request_timeout),
            batch_size=max(1, resolved.batch_size),
            batch_delay=max(0.0, resolved.batch_delay),
        )
        run.emit(
            "info", f"Resolved embedding model `{config.model}` with binding `{config.binding}`."
        )
        run.emit(
            "info",
            f"Request target (POSTed exactly as shown in Settings): {config.base_url}",
        )
        run.emit(
            "info",
            "Probing native max dimension with a small batch (sending no `dimensions=` param).",
        )
        client = EmbeddingClient(config)
        probe_texts = [
            "DeepTutor embedding smoke test",
            "DeepTutor retrieval batch probe",
        ]
        vectors = await client.embed(probe_texts)
        if len(vectors) != len(probe_texts):
            raise ValueError(
                "Embedding service returned an unexpected number of vectors "
                f"(expected {len(probe_texts)}, got {len(vectors)})."
            )
        if any(not vector for vector in vectors):
            raise ValueError("Embedding service returned an empty vector.")
        detected_dim = len(vectors[0])
        if any(len(vector) != detected_dim for vector in vectors):
            raise ValueError("Embedding service returned inconsistent vector dimensions.")

        capabilities = self._capabilities_from_adapter(client.adapter, config.model)
        supported = capabilities["supported_dimensions"]
        default_dim = capabilities["default_dim"]
        model_known = capabilities["model_known"]

        # Probe is the source of truth: always overwrite the catalog dim with
        # the detected value. Matryoshka users who want a truncated variant
        # can edit the field manually after the test. Source code stays
        # ``"detected"`` so the UI shows "Source: detected from API probe".
        active_dim = detected_dim
        active_source = "detected"
        if catalog_dim and catalog_dim != detected_dim:
            active_message = (
                f"Catalog dim {catalog_dim}d overwritten with API probe value {detected_dim}d."
            )
        else:
            active_message = f"Active dim {detected_dim}d set from API probe."

        run.emit(
            "capabilities",
            (
                f"Probe returned {detected_dim}d. "
                + (
                    f"Static catalog: default {default_dim}d, "
                    f"supported {supported or '(fixed)'}, model recognized."
                    if model_known
                    else "Static catalog: model not recognized — using probe value as the only signal."
                )
            ),
            detected_dim=detected_dim,
            default_dim=default_dim,
            supported_dimensions=supported,
            supports_variable_dimensions=capabilities["supports_variable_dimensions"],
            model_known=model_known,
            active_dim=active_dim,
            active_dim_source=active_source,
        )

        run.emit(
            "response",
            "Embedding vector received.",
            actual_dimension=detected_dim,
            expected_dimension=catalog_dim or None,
        )

        # Refresh the cached ``supported_dimensions`` CSV on the model entry so
        # the settings page can populate the dropdown without re-running the
        # test. Empty list → empty string clears any stale cache. Mutation
        # happens before the persist call so a single save round-trip carries
        # both fields.
        new_supported_csv = ",".join(str(d) for d in supported)
        if (model.get("supported_dimensions") or "") != new_supported_csv:
            model["supported_dimensions"] = new_supported_csv

        run.emit(
            "info",
            active_message,
            active_dim=active_dim,
            active_dim_source=active_source,
        )

        # Always persist: the probe runs end-to-end successfully, so the
        # detected dim is authoritative. ``_persist_embedding_dimension`` also
        # writes the refreshed ``supported_dimensions`` CSV in the same save.
        saved_catalog = self._persist_embedding_dimension(catalog, model, detected_dim)
        run.emit(
            "catalog",
            "Saved detected embedding dimension to model_catalog.json.",
            catalog=saved_catalog,
        )

    def _test_search(self, run: TestRun, catalog: dict[str, Any]) -> None:
        from deeptutor.services.search import web_search

        resolved = resolve_search_runtime_config(catalog=catalog)
        if resolved.provider == "none":
            run.status = "completed"
            run.emit("completed", "Search skipped because no active provider is configured.")
            return
        if resolved.unsupported_provider:
            raise ValueError(
                f"Search provider `{resolved.requested_provider}` is deprecated/unsupported. "
                "Switch to none/brave/tavily/jina/searxng/duckduckgo/perplexity/serper."
            )
        if resolved.missing_credentials:
            raise ValueError(
                f"Search provider `{resolved.requested_provider}` requires api_key. "
                "Set profile.api_key in Settings > Catalog."
            )
        provider = resolved.provider
        run.emit("info", f"Resolved search provider `{provider}`.")
        if resolved.fallback_reason:
            run.emit("warning", resolved.fallback_reason)
        run.emit("info", "Running search query: DeepTutor configuration health check")
        result = web_search("DeepTutor configuration health check", provider=provider)
        run.emit(
            "response",
            "Search result received.",
            answer_preview=str(result.get("answer", ""))[:240],
            citation_count=len(result.get("citations", []) or []),
            search_result_count=len(result.get("search_results", []) or []),
        )
        if not (result.get("answer") or result.get("search_results")):
            raise ValueError("Search provider returned no answer and no search results.")

    async def _test_tts(self, run: TestRun, catalog: dict[str, Any]) -> None:
        import base64

        from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config
        from deeptutor.services.voice import synthesize_speech

        run.emit("info", "Loading TTS config from the active catalog selection.")
        resolved = resolve_tts_runtime_config(catalog=catalog)
        run.emit(
            "info",
            f"Resolved model `{resolved.model}` (provider `{resolved.provider_name}`, "
            f"voice `{resolved.voice or '(default)'}`).",
        )
        run.emit("info", f"Request target: {resolved.base_url}")
        sample = "DeepTutor voice check. 这是一段语音合成测试。"
        run.emit("info", "Synthesizing a short sample clip.")
        audio, content_type = await synthesize_speech(sample, catalog=catalog)
        run.emit(
            "response",
            f"Received {len(audio)} bytes of {content_type}.",
            audio_base64=base64.b64encode(audio).decode("ascii"),
            content_type=content_type,
            bytes=len(audio),
        )

    async def _test_stt(self, run: TestRun, catalog: dict[str, Any]) -> None:
        import io
        import wave

        from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config
        from deeptutor.services.voice import transcribe_audio

        run.emit("info", "Loading STT config from the active catalog selection.")
        resolved = resolve_stt_runtime_config(catalog=catalog)
        run.emit(
            "info",
            f"Resolved model `{resolved.model}` (provider `{resolved.provider_name}`, "
            f"style `{resolved.request_style}`).",
        )
        run.emit("info", f"Request target: {resolved.base_url}")

        # One second of 16 kHz mono silence — a valid WAV that exercises the
        # full upload + auth + model path. Most providers return empty/near-empty
        # text; a clean HTTP 200 confirms the connection is configured correctly.
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)
        run.emit("info", "Uploading a 1s silent probe clip to validate the endpoint.")
        transcript = await transcribe_audio(
            buffer.getvalue(),
            catalog=catalog,
            filename="probe.wav",
            content_type="audio/wav",
        )
        run.emit(
            "response",
            "Transcription endpoint responded successfully.",
            snippet=(transcript or "(empty — expected for a silent clip)")[:200],
        )

    async def _test_imagegen(self, run: TestRun, catalog: dict[str, Any]) -> None:
        import base64

        from deeptutor.services.config.provider_runtime import resolve_imagegen_runtime_config
        from deeptutor.services.imagegen import generate_image

        run.emit("info", "Loading image-generation config from the active catalog selection.")
        resolved = resolve_imagegen_runtime_config(catalog=catalog)
        run.emit(
            "info",
            f"Resolved model `{resolved.model}` (provider `{resolved.provider_name}`, "
            f"size `{resolved.size or '(default)'}`).",
        )
        run.emit("info", f"Request target: {resolved.base_url}")
        run.emit("info", "Generating a single test image (this is a billable call).")
        images = await generate_image(
            "A small minimalist test icon of a blue book on a white background.",
            catalog=catalog,
            n=1,
        )
        if not images:
            raise ValueError("Image provider returned no images.")
        image_bytes, content_type = images[0]
        run.emit(
            "response",
            f"Received {len(image_bytes)} bytes of {content_type}.",
            image_base64=base64.b64encode(image_bytes).decode("ascii"),
            content_type=content_type,
            bytes=len(image_bytes),
        )

    async def _test_videogen(self, run: TestRun, catalog: dict[str, Any]) -> None:
        from deeptutor.services.config.provider_runtime import resolve_videogen_runtime_config
        from deeptutor.services.videogen import probe_video

        run.emit("info", "Loading video-generation config from the active catalog selection.")
        resolved = resolve_videogen_runtime_config(catalog=catalog)
        run.emit(
            "info",
            f"Resolved model `{resolved.model}` (provider `{resolved.provider_name}`, "
            f"adapter `{resolved.adapter}`).",
        )
        run.emit("info", f"Request target: {resolved.base_url}")
        run.emit(
            "info",
            "Submitting a probe task to validate endpoint + auth + model. "
            "The render is not awaited (it is slow and billable).",
        )
        task_id = await probe_video("A short test clip of a calm ocean wave.", catalog=catalog)
        run.emit(
            "response",
            "Video task accepted — connection is valid.",
            task_id=task_id,
        )


def get_config_test_runner() -> ConfigTestRunner:
    return ConfigTestRunner.get_instance()


__all__ = ["ConfigTestRunner", "TestRun", "get_config_test_runner"]
