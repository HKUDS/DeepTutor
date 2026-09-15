"""Reference offline dictionary provider.

Ships a tiny seeded English/Chinese entry set so the provider contract has a
working, dependency-free implementation out of the box. Real catalogs can be
registered by third-party providers through the same interface.
"""

from __future__ import annotations

from .manifest import PROVIDER_TYPE_DICTIONARY, ProviderManifest
from .protocol import LOOKUP_NOT_FOUND, LOOKUP_OK, LookupEntry, LookupRequest, LookupResult

_ENTRIES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "transform": (
        ("v.", "transform", "改变；转换；变换"),
        ("n.", "transform", "变换式"),
    ),
    "fourier": (("n.", "Fourier", "傅里叶（人名）"),),
    "fourier transform": (("n.", "Fourier transform", "傅里叶变换"),),
    "tokenize": (("v.", "tokenize", "分词；标记化"),),
}


class ReferenceOfflineDictionaryProvider:
    """Dependency-free en/zh dictionary used for tests and as a reference."""

    def __init__(self) -> None:
        self._manifest = ProviderManifest(
            name="reference-offline-dictionary",
            provider_type=PROVIDER_TYPE_DICTIONARY,
            version="1.0.0",
            languages=("en", "zh"),
            offline=True,
            permissions=(),
            description="Bundled offline English/Chinese dictionary reference",
        )

    @property
    def manifest(self) -> ProviderManifest:
        return self._manifest

    async def lookup(self, request: LookupRequest) -> LookupResult:
        term = request.term.strip().lower()
        rows = _ENTRIES.get(term)
        if not rows:
            return LookupResult(
                status=LOOKUP_NOT_FOUND,
                provider=self._manifest.name,
                message="Term not in the bundled dictionary",
            )
        entries = tuple(
            LookupEntry(headword=term, definition=kind, translation=gloss)
            for kind, _word, gloss in rows
        )
        return LookupResult(status=LOOKUP_OK, provider=self._manifest.name, entries=entries)
