"""Context-builder boundary used by the turn executor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeptutor.services.session.protocol import SessionStoreProtocol


class TurnContextAssembler:
    """Create the history/context assembler behind an injectable seam."""

    if TYPE_CHECKING:
        store: SessionStoreProtocol

    def _create_context_builder(self) -> Any:
        from deeptutor.services.session.context_builder import ContextBuilder

        return ContextBuilder(self.store)
