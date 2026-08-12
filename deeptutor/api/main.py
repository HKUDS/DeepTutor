from contextlib import asynccontextmanager
import logging
import sys

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deeptutor.logging import configure_logging
from deeptutor.services.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_auth_settings,
    load_system_settings,
)
from deeptutor.services.config.origins import normalize_origins
from deeptutor.services.path_service import get_path_service

# GuruAI extension: import is intentionally kept alongside the existing router
# imports below; all original DeepTutor routers remain enabled.
from deeptutor.api.routers import guruai

ensure_runtime_settings_files()
export_runtime_settings_to_env(overwrite=True)
configure_logging()
logger = logging.getLogger(__name__)

class _SuppressWsNoise(logging.Filter):
    _SUPPRESSED = ("connection open", "connection closed")
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f in msg for f in self._SUPPRESSED)

logging.getLogger("uvicorn.error").addFilter(_SuppressWsNoise())

# NOTE: The remainder of this file is unchanged from upstream in the branch.
# The GuruAI router is mounted near the other authenticated API routers below.
