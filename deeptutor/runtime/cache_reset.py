"""Shared cache reset after selecting a runtime home.

Service imports remain lazy so CLI/bootstrap can select DEEPTUTOR_HOME first.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def reset_runtime_singletons() -> None:
    """Refresh home-dependent caches, reporting failures without skipping peers."""
    try:
        from deeptutor.services.path_service import PathService

        PathService.reset_instance()
    except Exception:
        logger.exception(
            "PathService reset failed; the runtime may keep writing to the "
            "previous DEEPTUTOR_HOME instead of the selected one"
        )
    try:
        from deeptutor.services.config.runtime_settings import RuntimeSettingsService

        RuntimeSettingsService._instances.clear()
    except Exception:
        logger.warning(
            "RuntimeSettings cache reset failed; settings cached for the "
            "previous DEEPTUTOR_HOME may be reused",
            exc_info=True,
        )
    try:
        from deeptutor.services.config.model_catalog import ModelCatalogService

        ModelCatalogService._instances.clear()
    except Exception:
        logger.warning(
            "ModelCatalog cache reset failed; model catalog cached for the "
            "previous DEEPTUTOR_HOME may be reused",
            exc_info=True,
        )
