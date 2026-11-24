"""Base environment shared by plugin installers and workers."""

import os

_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "PATHEXT",
)


def plugin_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
