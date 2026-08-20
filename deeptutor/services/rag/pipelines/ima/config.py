"""Connection config for the Tencent IMA engine.

IMA credentials (``client_id`` + ``api_key``, issued at
https://ima.qq.com/agent-interface) identify an *account*, and a knowledge base
id identifies one of that account's libraries. The credentials therefore resolve
at two levels:

* **account level** — ``settings/ima.json`` (managed by
  ``RuntimeSettingsService``), edited under Knowledge → the IMA engine page.
  One pair is shared by every ``ima`` KB, the way PageIndex's key is;
* **per KB** — the same two fields on the KB's ``kb_config.json`` entry. Present
  on knowledge bases connected before the engine page existed, and still the way
  to point one KB at a *different* IMA account.

The per-KB pair wins when it is complete, so an existing binding keeps working
untouched and rotating the account key updates every KB that relies on it.

This module is the single seam that reads that binding into a typed config; it
holds no global state and imports no HTTP client (the client lives in
``client.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# IMA exposes exactly one retrieval call (``search_knowledge``) with no mode
# knob, so a KB bound to this engine has no per-KB search mode to pick. The
# empty tuple keeps the shared provider-mode plumbing happy while telling the
# UI there is nothing to offer.
SUPPORTED_MODES: tuple[str, ...] = ()
DEFAULT_MODE = ""


class ImaNotConfiguredError(RuntimeError):
    """Raised when a KB is missing the credentials or the knowledge base id."""


@dataclass(frozen=True)
class ImaCredentials:
    """One IMA account's credential pair."""

    client_id: str = ""
    api_key: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.client_id and self.api_key)


@dataclass(frozen=True)
class ImaConfig:
    """A KB's resolved connection to one Tencent IMA knowledge base."""

    client_id: str
    api_key: str
    knowledge_base_id: str


def get_account_credentials() -> ImaCredentials:
    """Load the account-level credential pair, or an empty one.

    Never raises: an unreadable settings file only means "not configured", which
    the callers already handle.
    """
    try:
        from deeptutor.services.config import get_runtime_settings_service

        settings = get_runtime_settings_service().load_ima()
    except Exception:
        return ImaCredentials()
    return ImaCredentials(
        client_id=str(settings.get("client_id") or "").strip(),
        api_key=str(settings.get("api_key") or "").strip(),
    )


def is_ima_configured() -> bool:
    """Whether account-level credentials are set (flags the engine as ready)."""
    return get_account_credentials().complete


def config_from_entry(
    entry: dict[str, Any],
    *,
    fallback: Optional[ImaCredentials] = None,
) -> ImaConfig:
    """Build an :class:`ImaConfig` from a ``kb_config.json`` KB entry.

    The entry's own credentials win; *fallback* (normally the account-level
    pair) fills in what it omits. Raises :class:`ImaNotConfiguredError` when any
    of the three required fields is still missing, so retrieval fails with a
    clear message instead of an opaque HTTP error from IMA.
    """
    client_id = str(entry.get("client_id") or "").strip()
    api_key = str(entry.get("api_key") or "").strip()
    knowledge_base_id = str(entry.get("knowledge_base_id") or "").strip()
    if fallback is not None:
        client_id = client_id or fallback.client_id
        api_key = api_key or fallback.api_key
    missing = [
        label
        for label, value in (
            ("client ID", client_id),
            ("API key", api_key),
            ("knowledge base ID", knowledge_base_id),
        )
        if not value
    ]
    if missing:
        raise ImaNotConfiguredError(
            "This knowledge base is not fully connected to Tencent IMA "
            f"(missing {', '.join(missing)}). Add the IMA credentials on the "
            "engine page under Knowledge, or re-create the knowledge base with "
            "complete credentials."
        )
    return ImaConfig(
        client_id=client_id,
        api_key=api_key,
        knowledge_base_id=knowledge_base_id,
    )


def resolve_kb_config(entry: dict[str, Any]) -> ImaConfig:
    """``config_from_entry`` with the account-level credentials as fallback."""
    return config_from_entry(entry, fallback=get_account_credentials())


__all__ = [
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "ImaNotConfiguredError",
    "ImaCredentials",
    "ImaConfig",
    "config_from_entry",
    "get_account_credentials",
    "is_ima_configured",
    "resolve_kb_config",
]
