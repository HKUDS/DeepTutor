"""Regression tests for the learner surface map and restrictions preset flip (#1222).

Two failure modes covered:

1. ``_learning_surface_for_path`` used to map only five prefixes, so the
   learner shell's own Knowledge Center (`/api/knowledge-bases/*`) and Mastery
   Path (`/api/mastery-paths/*`) endpoints default-denied to 403.
2. Assigning guardian restrictions to a `standard`-preset account left the
   account in a `standard` preset + `learning_policy` mix: the frontend then
   rendered the full admin shell and every surface request 403'd. The PUT
   restrictions handler now seeds the default policy and flips the preset to
   ``learner``.
"""

from __future__ import annotations

import pytest

from deeptutor.api.routers.auth import _learning_surface_for_path


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        # Pre-existing mappings keep working.
        ("/api/reading/materials", "GET", "reading"),
        ("/api/courses", "GET", "reading"),
        ("/api/chat/sessions", "GET", "chat"),
        ("/api/question/generate", "POST", "chat"),
        ("/api/sessions/abc", "GET", "chat"),
        # Mastery Path: the learner's own per-user progress, all methods.
        ("/api/mastery-paths/topics", "GET", "chat"),
        ("/api/mastery-paths/topics/index", "GET", "chat"),
        ("/api/mastery-paths/progress/book-1", "GET", "chat"),
        ("/api/mastery-paths/progress/book-1", "PATCH", "chat"),
        ("/api/mastery-paths/progress/book-1/redo", "POST", "chat"),
        # Knowledge Center: read-only for learners.
        ("/api/knowledge-bases", "GET", "reading"),
        ("/api/knowledge-bases/kb1/files", "GET", "reading"),
        ("/api/knowledge-bases/kb1/files/a.pdf", "GET", "reading"),
        # KB mutations stay denied — they affect shared/admin resources.
        ("/api/knowledge-bases", "POST", ""),
        ("/api/knowledge-bases/kb1/upload", "POST", ""),
        ("/api/knowledge-bases/kb1/files/a.pdf", "DELETE", ""),
        # Everything else still default-denies.
        ("/api/settings", "GET", ""),
        ("/api/system/status", "GET", ""),
        ("/api/partners", "GET", ""),
        ("/api/memory/overview", "GET", ""),
        ("", "GET", ""),
    ],
)
def test_learning_surface_map(path: str, method: str, expected: str) -> None:
    assert _learning_surface_for_path(path, method) == expected


def test_put_restrictions_flips_standard_preset_to_learner(
    mu_isolated_root, seed_user
):
    """PUT restrictions on a standard-preset account seeds the policy and
    flips the account preset to ``learner`` (#1222 preset/policy mix)."""
    import asyncio
    from types import SimpleNamespace

    from deeptutor.api.routers.multi_user import (
        GuardianRestrictionsPayload,
        put_guardian_restrictions,
    )
    from deeptutor.multi_user.identity import get_user_by_id

    # The first account in an empty store is promoted to admin by save_user;
    # seed a bootstrap account first so the learner keeps role="user".
    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    admin = SimpleNamespace(user_id="u_admin", role="admin")

    payload = GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )

    result = asyncio.run(put_guardian_restrictions(learner_user_id, payload, admin))
    assert result["restrictions"]["age_band"] == "13-15"

    _username, updated = get_user_by_id(learner_user_id)
    assert updated.get("preset") == "learner"
