from pathlib import Path

from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


def _user(root: Path, user_id: str) -> CurrentUser:
    user_root = root / "users" / user_id
    return CurrentUser(
        id=user_id,
        username=user_id,
        role="user",
        scope=UserScope(kind="user", user_id=user_id, root=user_root),
    )


def test_reading_learning_records_stay_in_each_users_workspace(tmp_path: Path) -> None:
    stores = {}
    for user_id in ("u_alice", "u_bob"):
        token = set_current_user(_user(tmp_path, user_id))
        try:
            store = LearningStore()
            stores[user_id] = store
            store.record_reading_position(
                "rm_shared", locator=2 if user_id == "u_alice" else 1, percentage=0.5
            )
            store.record_reading_activity(
                "rm_shared",
                extension_id="sample",
                action="open",
                locator=1,
                result_type="card",
            )
        finally:
            reset_current_user(token)

        records = store.list_reading_records()
        assert records.progress[0].material_id == "rm_shared"
        assert records.progress[0].furthest_locator == (2 if user_id == "u_alice" else 1)
        assert records.activities[0].activity_id

    assert stores["u_alice"].db_path != stores["u_bob"].db_path
    assert stores["u_alice"].list_reading_records().progress[0].furthest_locator == 2
    assert stores["u_bob"].list_reading_records().progress[0].furthest_locator == 1
