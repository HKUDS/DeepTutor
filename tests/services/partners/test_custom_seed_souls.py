"""Legacy template refresh must retain edited text on familiar seed IDs."""

import pytest

from deeptutor.services.partners.manager import PartnerManager


@pytest.mark.parametrize("soul_id", ["companion", "math-tutor", "default-tutorbot"])
def test_listing_preserves_custom_soul_that_mentions_tutorbot(partners_root, soul_id):
    manager = PartnerManager()
    entry = {
        "id": soul_id,
        "name": "My tutor",
        "content": "# My lesson plan\nCompare TutorBot with my custom exercises.\n",
    }
    if manager.get_soul(soul_id) is None:
        manager.create_soul(soul_id, entry["name"], entry["content"])
    else:
        manager.update_soul(soul_id, entry["name"], entry["content"])
    before = manager._souls_file.read_bytes()
    assert manager.get_soul(soul_id) == entry
    assert manager._souls_file.read_bytes() == before
