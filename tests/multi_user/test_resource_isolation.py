from __future__ import annotations


def test_book_session_ids_are_scoped_per_user(as_user) -> None:
    from deeptutor.book.storage import BookStorage
    from deeptutor.services.session import get_sqlite_session_store, get_turn_runtime_manager

    shared_book_id = "shared-book-id"

    with as_user("u_victim"):
        victim_book_root = BookStorage().book_root(shared_book_id)
        victim_session_db = get_sqlite_session_store().db_path
        victim_runtime_store_db = get_turn_runtime_manager().store.db_path

    with as_user("u_attacker"):
        attacker_book_root = BookStorage().book_root(shared_book_id)
        attacker_session_db = get_sqlite_session_store().db_path
        attacker_runtime_store_db = get_turn_runtime_manager().store.db_path

    assert victim_book_root != attacker_book_root
    assert victim_session_db != attacker_session_db
    assert victim_runtime_store_db != attacker_runtime_store_db
    assert "u_victim" in str(victim_book_root)
    assert "u_attacker" in str(attacker_book_root)


def test_partner_data_is_admin_anchored_not_user_scoped(as_user) -> None:
    """Partners are process-wide resources anchored at the admin workspace.

    Unlike the per-user resources above, the partner tree must NOT follow the
    request user's scope: partner runtimes execute inside a synthetic partner
    scope whose own workspace lives below ``data/partners``, so resolving the
    base dir through the contextvar would recurse the layout. Access control
    is enforced at the API layer instead (the /api/v1/partners router is
    admin-gated in ``api/main.py``).
    """
    from deeptutor.services.partners.manager import PartnerManager

    manager = PartnerManager()

    with as_user("u_victim"):
        victim_dir = manager._partners_dir
    with as_user("u_attacker"):
        attacker_dir = manager._partners_dir

    assert victim_dir == attacker_dir
    assert str(victim_dir).endswith("data/partners")
    assert "u_victim" not in str(victim_dir)
