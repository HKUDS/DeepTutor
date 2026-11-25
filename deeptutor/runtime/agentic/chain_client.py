"""OpenAI-shaped client over an ordered provider chain (issue #2693 P1).

The agent loop streams through an OpenAI-compatible facade, and a streaming
failure surfaces during iteration — after the loop has already decided it can
retry because nothing was emitted. So this wrapper does not try to fail over
inside ``create``: it exposes :meth:`advance`, which the loop calls in its
existing "failed before output, retrying" branch. That keeps the switch on the
one path that already knows no output escaped, and needs no change to how a
stream is consumed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Sequence

from deeptutor.runtime.agentic.client import LLMClientConfig, build_openai_client
from deeptutor.services.llm import failover


def _client_config(candidate: failover.Candidate, *, template: LLMClientConfig) -> LLMClientConfig:
    """Per-candidate client config, inheriting the turn's transport settings."""
    config = candidate.config
    return LLMClientConfig(
        binding=getattr(config, "provider_name", None) or template.binding,
        model=getattr(config, "model", None) or template.model,
        api_key=getattr(config, "api_key", None) or template.api_key,
        base_url=getattr(config, "base_url", None) or template.base_url,
        api_version=getattr(config, "api_version", None) or template.api_version,
        extra_headers=getattr(config, "extra_headers", None) or template.extra_headers,
        reasoning_effort=(getattr(config, "reasoning_effort", None) or template.reasoning_effort),
        wire_api=getattr(config, "wire_api", None) or template.wire_api,
        api_format=getattr(config, "api_format", None) or template.api_format,
    )


class ChainClient:
    """OpenAI facade that can move to the next healthy candidate on demand."""

    def __init__(
        self,
        candidates: Sequence[failover.Candidate],
        clients: Sequence[Any],
        *,
        owner_id: str,
    ) -> None:
        self._candidates = list(candidates)
        self._clients = list(clients)
        self._owner_id = owner_id
        self._index = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def current(self) -> failover.Candidate:
        return self._candidates[self._index]

    @property
    def remaining(self) -> int:
        return len(self._candidates) - self._index - 1

    async def _create(self, **kwargs: Any) -> Any:
        # The request carries the primary's model name; after a switch the
        # candidate's own model must be used, or the backup would be asked for a
        # model it does not serve.
        model = getattr(self.current.config, "model", "") or kwargs.get("model")
        if model:
            kwargs["model"] = model
        if self._index > 0 and isinstance(kwargs.get("messages"), list):
            # Another provider's private replay state must not reach this one.
            kwargs["messages"] = failover.drop_foreign_message_state(kwargs["messages"])
        response = await self._clients[self._index].chat.completions.create(**kwargs)
        # Reaching a provider successfully clears its failure ladder, so the
        # cooldown does not escalate after a recovered blip.
        self.record_success()
        return response

    def advance(self) -> failover.Candidate | None:
        """Switch to the next candidate that is not cooling down."""
        for index in range(self._index + 1, len(self._candidates)):
            candidate = self._candidates[index]
            if failover.REGISTRY.is_available(self._owner_id, candidate):
                self._index = index
                return candidate
        return None

    def record_failure(self, exc: Exception) -> str:
        return failover.REGISTRY.record_failure(self._owner_id, self.current, exc)

    def record_success(self) -> None:
        failover.REGISTRY.record_success(self._owner_id, self.current)

    async def close(self) -> None:
        for client in self._clients:
            close = getattr(client, "close", None) or getattr(client, "aclose", None)
            if callable(close):
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass


def build_chain_client(
    template: LLMClientConfig,
    *,
    owner_id: str | None = None,
    candidates: Iterable[failover.Candidate] | None = None,
) -> Any:
    """Build a ChainClient when a chain is configured, else the plain client."""
    resolved_owner = owner_id or failover.current_owner()
    chain = list(
        candidates if candidates is not None else failover.resolve_candidates(resolved_owner)
    )
    healthy = [item for item in chain if failover.REGISTRY.is_available(resolved_owner, item)]
    if not healthy:
        # Everything is cooling down: give the primary one more chance rather
        # than turning the turn into a "no candidate" error.
        return build_openai_client(template)
    if len(healthy) == 1:
        # A single usable candidate may well be the backup (primary cooling), so
        # the client must be built for that candidate, not for the template.
        return build_openai_client(_client_config(healthy[0], template=template))
    clients = [build_openai_client(_client_config(item, template=template)) for item in healthy]
    return ChainClient(healthy, clients, owner_id=resolved_owner)


__all__ = ["ChainClient", "build_chain_client"]
