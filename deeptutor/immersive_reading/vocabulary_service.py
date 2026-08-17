"""Public vocabulary workflow mixin for immersive reading."""

from __future__ import annotations

from .vocabulary_analysis import VocabularyAnalysisMixin
from .vocabulary_operations import VocabularyOperationsMixin


class VocabularyMixin(
    VocabularyOperationsMixin,
    VocabularyAnalysisMixin,
):
    pass


__all__ = ["VocabularyMixin"]
