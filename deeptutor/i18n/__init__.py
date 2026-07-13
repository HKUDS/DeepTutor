"""Localization helpers.

Two complementary pieces live here:

* :mod:`~deeptutor.i18n.metadata_i18n` — static localized display copy for
  built-in capabilities and tools (used by the settings UI / API).
* :mod:`~deeptutor.i18n.status_i18n` — per-feature localized status-string
  lookup wired into the :class:`PromptManager`, used by capability pipelines
  to stream locale-aware progress messages.
"""

from deeptutor.i18n.metadata_i18n import (
    capability_description_i18n,
    localized_description,
    tool_description_i18n,
)
from deeptutor.i18n.status_i18n import StatusI18n

__all__ = [
    "StatusI18n",
    "capability_description_i18n",
    "localized_description",
    "tool_description_i18n",
]
