"""Shared cache reset after selecting a runtime home.

Service imports remain lazy so CLI/bootstrap can select DEEPTUTOR_HOME first.
"""

from __future__ import annotations

import logging
import sys

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
    # CLI setup can select --home after multi-user paths were imported.
    # Keep the shared reset seam responsible for every cached home boundary.
    if sys.modules.get("deeptutor.multi_user.paths") is not None:
        try:
            from deeptutor.multi_user import paths
            from deeptutor.runtime.home import get_runtime_home

            paths.PROJECT_ROOT = get_runtime_home()
            paths.ADMIN_WORKSPACE_ROOT = paths.PROJECT_ROOT / "data"
            paths.USERS_ROOT = paths.ADMIN_WORKSPACE_ROOT / "users"
            paths.SYSTEM_ROOT = paths.ADMIN_WORKSPACE_ROOT / "system"
            paths.LEGACY_MULTI_USER_ROOT = paths.PROJECT_ROOT / "multi-user"
            paths._path_services.clear()
            paths._legacy_migration_done = False
        except Exception:
            logger.warning(
                "Multi-user path cache reset failed; owner paths may retain the previous runtime home",
                exc_info=True,
            )
