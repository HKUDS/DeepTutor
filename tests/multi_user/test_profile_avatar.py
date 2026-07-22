"""Profile avatar — marker persistence, image file storage, upload validation."""

from __future__ import annotations

import pytest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16


def test_set_avatar_persists_through_normalisation(mu_isolated_root, seed_user):
    from deeptutor.multi_user.identity import list_user_info, load_users, set_avatar

    seed_user("alice")
    assert set_avatar("alice", "icon:sparkles:violet")

    # load_users() rewrites records through _canonical_record; the avatar
    # field must survive that round-trip.
    assert load_users()["alice"]["avatar"] == "icon:sparkles:violet"
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["avatar"] == "icon:sparkles:violet"


def test_save_user_preserves_existing_avatar(mu_isolated_root, seed_user):
    from deeptutor.multi_user.identity import load_users, save_user, set_avatar

    seed_user("alice")
    set_avatar("alice", "img:3")

    # Password change (save_user on an existing name) must not drop the avatar.
    save_user("alice", "$2b$12$newhash", role="admin")
    assert load_users()["alice"]["avatar"] == "img:3"


def test_set_avatar_unknown_user_returns_false(mu_isolated_root, seed_user):
    from deeptutor.multi_user.identity import set_avatar

    seed_user("alice")
    assert not set_avatar("nobody", "icon:leaf:teal")


def test_records_without_avatar_default_to_empty(mu_isolated_root, seed_user):
    from deeptutor.multi_user.identity import list_user_info

    seed_user("alice")
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["avatar"] == ""


def test_avatar_file_roundtrip_and_extension_replacement(mu_isolated_root):
    from deeptutor.multi_user.identity import (
        delete_avatar_file,
        get_avatar_file,
        save_avatar_file,
    )

    assert get_avatar_file("u_abc") is None

    saved = save_avatar_file("u_abc", PNG_BYTES, "png")
    assert saved.read_bytes() == PNG_BYTES
    assert get_avatar_file("u_abc") == saved

    # Re-upload with a different format must drop the stale sibling.
    replaced = save_avatar_file("u_abc", WEBP_BYTES, "webp")
    assert get_avatar_file("u_abc") == replaced
    assert not saved.exists()

    delete_avatar_file("u_abc")
    assert get_avatar_file("u_abc") is None


def test_save_avatar_file_rejects_unknown_extension(mu_isolated_root):
    from deeptutor.multi_user.identity import save_avatar_file

    with pytest.raises(ValueError):
        save_avatar_file("u_abc", b"<svg/>", "svg")


def test_sniff_image_detects_supported_formats_only():
    from deeptutor.api.routers.auth import _sniff_image

    assert _sniff_image(PNG_BYTES) == "png"
    assert _sniff_image(JPG_BYTES) == "jpg"
    assert _sniff_image(WEBP_BYTES) == "webp"
    # SVG (stored-XSS vector) and arbitrary bytes must be rejected.
    assert _sniff_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert _sniff_image(b"GIF89a" + b"\x00" * 16) is None
    assert _sniff_image(b"") is None


def test_update_profile_request_validates_marker():
    from deeptutor.api.routers.auth import UpdateProfileRequest

    assert UpdateProfileRequest(avatar="").avatar == ""
    assert UpdateProfileRequest(avatar="icon:sparkles:violet").avatar == "icon:sparkles:violet"

    for bad in ("img:1", "icon:Sparkles:violet", "icon:a:b:c", "../etc/passwd", "icon::"):
        with pytest.raises(ValueError):
            UpdateProfileRequest(avatar=bad)
