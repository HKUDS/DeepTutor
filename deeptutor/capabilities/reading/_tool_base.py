"""Shared plumbing for the reading tools.

Split out of :mod:`deeptutor.capabilities.reading.tools` so that module (and the
figure tool beside it) stay under the repository's file-size limit. The names
here are re-exported by ``tools`` unchanged, so existing importers keep working.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolResult
from deeptutor.tools.prompting import load_prompt_hints

logger = logging.getLogger(__name__)

# Private, server-injected kwarg carrying the open material.
MATERIAL_KWARG = "_material_id"
WORKSPACE_KWARG = "_reading_workspace_id"
BINDING_KWARG = "_reading_binding"


class _ReadingToolBase(BaseTool):
    """Shared plumbing: resolve the injected material and the store."""

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    @staticmethod
    def _material_id(kwargs: dict[str, Any]) -> str:
        binding = kwargs.get(BINDING_KWARG)
        bound_id = binding.get("material_id") if isinstance(binding, dict) else ""
        material_id = str(bound_id or kwargs.get(MATERIAL_KWARG) or "").strip()
        if not material_id:
            raise _NoMaterial()
        from deeptutor.multi_user.learning_access import assert_learning_material

        assert_learning_material(material_id)
        return material_id

    @staticmethod
    def _store():
        # Imported inside the call: ``reading.store`` reaches the path service,
        # which reaches the runtime and the tool registry — importing it at
        # module scope would close that cycle through the builtin registry.
        from deeptutor.reading import ReadingStore

        return ReadingStore()

    @staticmethod
    def _catalog():
        from deeptutor.reading import ReadingCatalogStore

        return ReadingCatalogStore()

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(content=message, success=False)


class _NoMaterial(RuntimeError):
    """Raised when the turn has no open material (should be unreachable)."""


def _guard(func):
    """Turn engine errors into readable tool failures instead of turn deaths."""

    async def wrapper(self: _ReadingToolBase, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import ReadingError

        try:
            return await func(self, **kwargs)
        except _NoMaterial:
            return self._failure(
                "No reading material is open. Ask the user to open a document in the reader."
            )
        except PermissionError as exc:
            return self._failure(str(exc))
        except ReadingError as exc:
            return self._failure(str(exc))
        except Exception:  # pragma: no cover - defensive
            logger.warning("reading tool %s failed", getattr(self, "name", "?"), exc_info=True)
            return self._failure("The reader could not complete that request.")

    return wrapper