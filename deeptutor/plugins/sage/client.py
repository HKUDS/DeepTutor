"""
SAGE Client — Thread-safe singleton wrapper around ``sage-agent-sdk``.

Adapted from the canonical RAPTOR / Aether wrapper (and used in the
LevelUp + pentagi v2 integrations). Provides a tiny ``recall`` /
``remember`` surface and degrades gracefully when SAGE is disabled,
unreachable, or the SDK package is missing.

Environment variables (all optional)::

    SAGE_ENABLED        "true" / "1" / "yes" enables the integration.
                        Anything else (or unset) makes every call a no-op.
    SAGE_URL            Base URL of the SAGE node (default ``http://localhost:8080``).
    SAGE_AGENT_KEY      Path to an existing agent key file. If unset, the
                        plugin generates one under ``$SAGE_HOME/agents/deeptutor/``.
    SAGE_HOME           Override for the SAGE home directory (default ``~/.sage``).
    SAGE_TIMEOUT        Per-request timeout in seconds (default 10).

The wrapper is intentionally narrow: ``recall`` for pre-capability prompt
enrichment and ``remember`` for ``CAPABILITY_COMPLETE`` observations. Anything
beyond that should live in the SDK, not here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8080"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_AGENT_NAME = "deeptutor"


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _find_agent_key() -> Path | None:
    """Resolve the SAGE agent key via env vars.

    Priority:
      1. ``SAGE_AGENT_KEY`` (explicit path)
      2. ``$SAGE_HOME/agents/*/agent.key`` — first match
    """
    explicit = os.environ.get("SAGE_AGENT_KEY")
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path

    sage_home = Path(os.environ.get("SAGE_HOME", "~/.sage")).expanduser()
    agents_dir = sage_home / "agents"
    if not agents_dir.is_dir():
        return None
    for agent_dir in sorted(agents_dir.iterdir()):
        key_file = agent_dir / "agent.key"
        if key_file.exists():
            return key_file
    return None


class SageClient:
    """Thread-safe singleton client for the SAGE memory layer."""

    _instance: "SageClient | None" = None
    _lock = threading.Lock()

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or os.environ.get("SAGE_URL", _DEFAULT_URL)).rstrip("/")
        self._timeout = float(os.environ.get("SAGE_TIMEOUT", _DEFAULT_TIMEOUT))
        self._enabled = _truthy(os.environ.get("SAGE_ENABLED"))
        self._sdk_client: Any = None
        self._sdk_checked = False
        self._agent_name = _DEFAULT_AGENT_NAME

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "SageClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton — for tests only."""
        with cls._lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _ensure_sdk(self) -> Any:
        """Lazy-import sage-agent-sdk and bind a client + identity."""
        if self._sdk_checked:
            return self._sdk_client
        self._sdk_checked = True

        if not self._enabled:
            return None

        try:
            from sage_sdk import AgentIdentity
            from sage_sdk import SageClient as SDKClient
        except ImportError:
            logger.info(
                "sage-agent-sdk not installed — SAGE plugin disabled. "
                "Install with: pip install sage-agent-sdk"
            )
            return None
        except Exception as exc:
            logger.warning("Unexpected import error for sage-agent-sdk: %s", exc)
            return None

        try:
            key_path = _find_agent_key()
            if key_path is not None:
                identity = AgentIdentity.from_file(str(key_path))
                logger.debug("SAGE identity loaded from %s", key_path)
            else:
                sage_home = Path(os.environ.get("SAGE_HOME", "~/.sage")).expanduser()
                agent_dir = sage_home / "agents" / "deeptutor-instance"
                agent_dir.mkdir(parents=True, exist_ok=True)
                key_file = agent_dir / "agent.key"
                if key_file.exists():
                    identity = AgentIdentity.from_file(str(key_file))
                else:
                    identity = AgentIdentity.generate()
                    identity.to_file(str(key_file))
                logger.debug("SAGE identity generated at %s", key_file)

            self._sdk_client = SDKClient(
                base_url=self._base_url,
                identity=identity,
                timeout=self._timeout,
            )

            try:
                self._sdk_client.register_agent(
                    name=self._agent_name,
                    provider="deeptutor",
                    boot_bio="DeepTutor — agent-native intelligent learning companion",
                )
            except Exception:
                # Already registered or registration optional; ignore.
                pass
        except Exception as exc:
            logger.warning("Failed to initialise SAGE SDK client: %s", exc)
            self._sdk_client = None
        return self._sdk_client

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if SAGE is reachable. Safe from any thread."""
        if not self._enabled:
            return False
        sdk = self._ensure_sdk()
        if sdk is None:
            return False
        try:
            result = sdk.health()
            return bool(result)
        except Exception as exc:
            logger.debug("SAGE health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    def recall(
        self,
        query: str,
        domain: str = "general",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return up to *top_k* committed memories from *domain*.

        Returns an empty list on any failure or when SAGE is disabled —
        callers are expected to treat the result as additional context, not
        as a hard dependency.
        """
        if not self._enabled or not query:
            return []
        sdk = self._ensure_sdk()
        if sdk is None:
            return []
        try:
            result = sdk.list_memories(
                domain=domain,
                status="committed",
                limit=min(max(top_k * 4, top_k), 50),
            )
            raw = getattr(result, "memories", []) or []
            if not raw:
                return []

            # Lightweight client-side keyword ranking — works regardless of
            # the embedding mode the SAGE node is configured with.
            tokens = {tok for tok in query.lower().split() if len(tok) > 2}
            scored: list[tuple[int, Any]] = []
            for mem in raw:
                content = getattr(mem, "content", "") or ""
                lowered = content.lower()
                score = sum(1 for tok in tokens if tok in lowered)
                if score > 0:
                    scored.append((score, mem))

            ranked = sorted(scored, key=lambda x: -x[0])[:top_k]
            if not ranked:
                # Fall back to raw order so the caller still gets *some*
                # context when keyword overlap is zero (e.g. embedding-driven
                # recall would have returned them).
                ranked = [(0, mem) for mem in raw[:top_k]]

            return [
                {
                    "content": getattr(mem, "content", "") or "",
                    "confidence": float(getattr(mem, "confidence_score", 0.0) or 0.0),
                    "domain": getattr(mem, "domain_tag", domain) or domain,
                    "memory_id": getattr(mem, "memory_id", "") or "",
                }
                for _, mem in ranked
            ]
        except Exception as exc:
            logger.warning("SAGE recall failed: %s", exc)
            return []

    def remember(
        self,
        content: str,
        domain: str = "general",
        memory_type: str = "observation",
        confidence: float = 0.80,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Propose a memory to SAGE. Returns the response dict or ``{}``."""
        if not self._enabled or not content:
            return {}
        sdk = self._ensure_sdk()
        if sdk is None:
            return {}
        try:
            tagged = content
            if tags:
                tagged = f"{content} [tags: {', '.join(tags)}]"
            result = sdk.propose(
                content=tagged,
                memory_type=memory_type,
                domain_tag=domain,
                confidence=confidence,
            )
            return {
                "memory_id": getattr(result, "memory_id", ""),
                "tx_hash": getattr(result, "tx_hash", ""),
                "status": "proposed",
            }
        except Exception as exc:
            logger.warning("SAGE remember failed: %s", exc)
            return {}


def get_sage_client() -> SageClient:
    """Module-level shortcut for ``SageClient.get_instance()``."""
    return SageClient.get_instance()
