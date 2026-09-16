"""A notice about a failure must say what failed.

#1356 was reported as "knowledge retrieval hides embedding connectivity
failures". The adapter had always raised a `ConnectionError` naming the
endpoint and the remedy, and the dispatcher had always caught it — the text
was discarded one layer above, where a template said "An unknown error
occurred while executing rag." and had no placeholder to put the cause in.

That is the whole failure mode: the code passes a cause the template cannot
accept, and nothing complains. This test is the thing that complains. A key
listed here is one the runtime formats with `error=`, so every locale that
defines it has to have somewhere to put it.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

# Notice keys the runtime formats with a cause. Adding a key here without
# adding `{error}` to its templates fails; adding the placeholder without
# passing the cause is caught by the call-site tests next to each capability.
CAUSE_BEARING_NOTICES = (
    "tool_error",
    "loop_error_finish",
    "tool_summarizer_failed",
)

_PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "deeptutor" / "agents"


def _notice_definitions(key: str) -> list[tuple[pathlib.Path, str]]:
    found: list[tuple[pathlib.Path, str]] = []
    for path in _PROMPTS.rglob("prompts/*/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # pragma: no cover - a broken bundle is its own test
            continue
        notices = data.get("notices")
        if isinstance(notices, dict) and isinstance(notices.get(key), str):
            found.append((path, notices[key]))
    return found


@pytest.mark.parametrize("key", CAUSE_BEARING_NOTICES)
def test_every_locale_of_a_failure_notice_can_hold_its_cause(key: str) -> None:
    definitions = _notice_definitions(key)
    assert definitions, (
        f"notices.{key} is defined in no prompt bundle — either it was renamed "
        "and this list is stale, or the notice was dropped and the runtime "
        "still formats it"
    )
    missing = [str(path) for path, text in definitions if "{error}" not in text]
    assert not missing, (
        f"notices.{key} has no {{error}} placeholder in: {missing}. "
        "The runtime passes the cause; a template without a slot for it "
        "silently drops what the user needs to act on (#1356)."
    )


def test_a_failure_notice_is_translated_everywhere_it_is_defined() -> None:
    """A cause that only reaches English readers is half a fix.

    #1356's convergence touched six files for one key precisely because en and
    zh have to move together; a key present in one locale and absent from the
    other falls back to English mid-sentence.
    """
    for key in CAUSE_BEARING_NOTICES:
        locales = {path.parent.name for path, _text in _notice_definitions(key)}
        assert {"en", "zh"} <= locales, (
            f"notices.{key} is missing from locales {{'en', 'zh'}} - {locales}"
        )
