"""Reading the chat capability settings must not corrupt the shipped defaults.

``_build_chat_block`` seeded its merge buffer by deep-merging
``DEFAULT_CHAT_PARAMS`` into an empty dict with a mutating merge helper. That
aliased the buffer's nested stage dicts to the module-level default objects, so
merging a user's ``capabilities.chat.<stage>`` override then wrote that value
*into* ``DEFAULT_CHAT_PARAMS`` in place. The shipped default was corrupted
process-wide, and a later read without an override bled the previous user's
value (also into the chat hot path via ``loader.get_chat_params``).
"""

from __future__ import annotations

import copy

import pytest

from deeptutor.services.config import capabilities_settings as module
from deeptutor.services.config.loader import DEFAULT_CHAT_PARAMS


@pytest.fixture(autouse=True)
def _restore_chat_defaults() -> None:
    """Isolate each test from the very corruption under test (and each other)."""
    pristine = copy.deepcopy(DEFAULT_CHAT_PARAMS)
    yield
    DEFAULT_CHAT_PARAMS.clear()
    DEFAULT_CHAT_PARAMS.update(pristine)


def test_build_chat_block_does_not_mutate_shipped_defaults() -> None:
    pristine = copy.deepcopy(DEFAULT_CHAT_PARAMS)

    module._build_chat_block({"capabilities": {"chat": {"exploring": {"max_tokens": 9999}}}})

    assert DEFAULT_CHAT_PARAMS == pristine


def test_override_does_not_bleed_into_a_later_default_read() -> None:
    shipped_exploring = copy.deepcopy(DEFAULT_CHAT_PARAMS)["exploring"]["max_tokens"]

    module._build_chat_block({"capabilities": {"chat": {"exploring": {"max_tokens": 9999}}}})
    later = module._build_chat_block({"capabilities": {"chat": {}}})

    assert later["stage_budgets"]["exploring"] == shipped_exploring
