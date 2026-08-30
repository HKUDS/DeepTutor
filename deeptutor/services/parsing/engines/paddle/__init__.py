"""PaddleOCR (飞桨) document-parsing engine (cloud API)."""

from .cloud import parse_cloud, verify_credentials
from .config import PaddleConfig, PaddleError, resolve_paddle_config
from .engine import PaddleParser

__all__ = [
    "PaddleConfig",
    "PaddleError",
    "PaddleParser",
    "parse_cloud",
    "resolve_paddle_config",
    "verify_credentials",
]
