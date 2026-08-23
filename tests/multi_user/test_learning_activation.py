from __future__ import annotations

import json

from deeptutor.multi_user.activation import activate, issue_activation
from deeptutor.services.auth import authenticate, hash_password


def test_activation_is_hashed_single_use_and_changes_password(
    mu_isolated_root, monkeypatch, seed_user
):
    from deeptutor.multi_user import activation

    target = mu_isolated_root / "data" / "system" / "auth" / "learning_activations.json"
    monkeypatch.setattr(activation, "ACTIVATIONS_FILE", target)
    seed_user("admin", role="admin")
    seed_user("learner-one", password="temporary-password")

    code = issue_activation("learner-one")
    stored = target.read_text(encoding="utf-8")
    assert code not in stored
    assert activate("learner-one", code, hash_password("new-password"))
    assert not activate("learner-one", code, hash_password("another-password"))
    assert authenticate("learner-one", "new-password") is not None
    assert json.loads(stored)["learner-one"]["used_at"] == 0.0
