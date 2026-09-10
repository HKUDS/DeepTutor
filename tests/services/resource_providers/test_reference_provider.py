"""Bundled offline dictionary behavior."""

from __future__ import annotations

import pytest

from deeptutor.services.resource_providers import (
    LookupRequest,
    ReferenceOfflineDictionaryProvider,
)
from deeptutor.services.resource_providers.protocol import LOOKUP_NOT_FOUND, LOOKUP_OK


@pytest.mark.anyio
async def test_known_term_returns_entries() -> None:
    provider = ReferenceOfflineDictionaryProvider()
    result = await provider.lookup(LookupRequest(term="Fourier Transform"))
    assert result.status == LOOKUP_OK
    assert result.provider == "reference-offline-dictionary"
    assert any("傅里叶变换" in entry.translation for entry in result.entries)


@pytest.mark.anyio
async def test_unknown_term_is_explicit_not_found() -> None:
    provider = ReferenceOfflineDictionaryProvider()
    result = await provider.lookup(LookupRequest(term="qqqzzz"))
    assert result.status == LOOKUP_NOT_FOUND
    assert result.entries == ()
