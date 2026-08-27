"""Linking a chat-channel account to a DeepTutor account.

The point of a link is that a channel message stops being anonymous: it lands
in the sender's own thread pool instead of the partner's shared one, and the
partner answers out of that person's workspace.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.partners.bus.events import InboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.services.partners import links
from deeptutor.services.partners.interaction import session_store_for
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.runtime import PartnerRunner
from tests.services.partners.scripts import finish


@pytest.fixture
def alice(partners_root):
    """A real, **non-admin** account — identity is re-read on every turn.

    The admin is saved first on purpose. The first account in a store is
    force-promoted to admin regardless of the role asked for, and an admin's
    scope *is* the shared pool — so an alice who happened to be first would
    make "her private history" and "the shared pool" the same directory, and
    every assertion that they differ would pass or fail on account order.
    """
    from deeptutor.multi_user import identity
    from deeptutor.services.partners.interaction import actor_for_account

    identity.save_user("root", "hash", "admin")
    record = identity.save_user("alice", "hash", "user")
    assert record["role"] == "user", "alice must not be the store's first account"
    return actor_for_account(record["id"])


# ── code lifecycle ────────────────────────────────────────────


def test_redeeming_a_code_links_the_sender(partners_root):
    issued = links.issue_link_code("ada", "u_alice")

    claimed = links.redeem_link_code("ada", issued.code, channel="qq", sender_id="90210")

    assert claimed == "u_alice"
    assert links.linked_user_id("ada", "qq", "90210") == "u_alice"


def test_codes_are_single_use(partners_root):
    issued = links.issue_link_code("ada", "u_alice")
    links.redeem_link_code("ada", issued.code, channel="qq", sender_id="90210")

    again = links.redeem_link_code("ada", issued.code, channel="qq", sender_id="55555")

    assert again is None
    assert links.linked_user_id("ada", "qq", "55555") is None


def test_codes_are_case_insensitive_and_trimmed(partners_root):
    issued = links.issue_link_code("ada", "u_alice")

    claimed = links.redeem_link_code(
        "ada", f"  {issued.code.lower()} ", channel="qq", sender_id="90210"
    )

    assert claimed == "u_alice"


def test_issuing_again_invalidates_the_previous_code(partners_root):
    stale = links.issue_link_code("ada", "u_alice")
    links.issue_link_code("ada", "u_alice")

    assert links.redeem_link_code("ada", stale.code, channel="qq", sender_id="1") is None


def test_expired_codes_are_refused(partners_root, monkeypatch):
    issued = links.issue_link_code("ada", "u_alice")
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(links, "_now", lambda: later)

    assert links.redeem_link_code("ada", issued.code, channel="qq", sender_id="1") is None


def test_unknown_and_empty_codes_are_refused(partners_root):
    assert links.redeem_link_code("ada", "ZZZZZZ", channel="qq", sender_id="1") is None
    assert links.redeem_link_code("ada", "", channel="qq", sender_id="1") is None


def test_links_are_scoped_to_one_partner(partners_root):
    issued = links.issue_link_code("ada", "u_alice")
    links.redeem_link_code("ada", issued.code, channel="qq", sender_id="90210")

    assert links.linked_user_id("bo", "qq", "90210") is None


# ── managing your own links ───────────────────────────────────


def test_a_user_only_sees_and_removes_their_own_links(partners_root):
    for user, sender in (("u_alice", "1"), ("u_bob", "2")):
        code = links.issue_link_code("ada", user).code
        links.redeem_link_code("ada", code, channel="qq", sender_id=sender)

    listed = links.list_links("ada", "u_alice")
    assert [item["key"] for item in listed] == ["qq:1"]

    assert links.remove_link("ada", "u_alice", "qq:2") is False  # not hers to unlink
    assert links.linked_user_id("ada", "qq", "2") == "u_bob"

    assert links.remove_link("ada", "u_alice", "qq:1") is True
    assert links.linked_user_id("ada", "qq", "1") is None


def test_a_corrupt_store_reads_as_empty_rather_than_raising(partners_root):
    path = links._path("ada")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    assert links.linked_user_id("ada", "qq", "1") is None
    issued = links.issue_link_code("ada", "u_alice")
    assert links.redeem_link_code("ada", issued.code, channel="qq", sender_id="1") == "u_alice"


# ── what a link changes for a turn ────────────────────────────


def _dm(content: str = "hello", *, sender: str = "90210") -> InboundMessage:
    return InboundMessage(
        channel="qq", sender_id=sender, chat_id=f"private:{sender}", content=content
    )


def _group(content: str = "hello", *, sender: str = "90210") -> InboundMessage:
    return InboundMessage(
        channel="qq",
        sender_id=sender,
        chat_id="group:777",
        content=content,
        metadata={"is_group": True},
    )


@pytest.mark.asyncio
async def test_a_linked_sender_gets_their_own_private_history(
    partners_root, fake_orchestrator, alice
):
    from deeptutor.services.partners.manager import PartnerConfig

    fake_orchestrator.script = finish("ok")
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    code = links.issue_link_code("ada", alice.id).code
    links.redeem_link_code("ada", code, channel="qq", sender_id="90210")

    await runner.process_message(_dm("what did we say?"))

    assert [m["content"] for m in session_store_for("ada", alice).messages("qq:private:90210")] == [
        "what did we say?",
        "ok",
    ]
    # Nothing lands in the shared pool the admin reads.
    assert session_store_for("ada", None).messages("qq:private:90210") == []


@pytest.mark.asyncio
async def test_an_unlinked_sender_stays_in_the_shared_pool(partners_root, fake_orchestrator):
    from deeptutor.services.partners.manager import PartnerConfig

    fake_orchestrator.script = finish("ok")
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())

    await runner.process_message(_dm("hi"))

    assert [m["content"] for m in session_store_for("ada", None).messages("qq:private:90210")] == [
        "hi",
        "ok",
    ]


@pytest.mark.asyncio
async def test_group_traffic_stays_shared_even_from_a_linked_sender(
    partners_root, fake_orchestrator, alice
):
    from deeptutor.services.partners.manager import PartnerConfig

    fake_orchestrator.script = finish("ok")
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    code = links.issue_link_code("ada", alice.id).code
    links.redeem_link_code("ada", code, channel="qq", sender_id="90210")

    await runner.process_message(_group("morning everyone"))

    # A group thread is one shared conversation; splitting it per speaker would
    # leave the partner replying out of a history the room cannot see.
    assert session_store_for("ada", alice).list_sessions() == []
    assert session_store_for("ada", None).messages("qq:group:777")


@pytest.mark.asyncio
async def test_link_command_binds_the_sender_mid_conversation(partners_root, fake_orchestrator):
    from deeptutor.multi_user import identity

    identity.save_user("alice", "hash", "user")
    user_id = identity.get_user("alice")["id"]
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    code = links.issue_link_code("ada", user_id).code

    reply = await runner.process_message(_dm(f"/link {code}"))

    assert "alice" in reply
    assert links.linked_user_id("ada", "qq", "90210") == user_id


@pytest.mark.asyncio
async def test_link_command_refuses_a_group_chat(partners_root, fake_orchestrator):
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    code = links.issue_link_code("ada", "u_alice").code

    reply = await runner.process_message(_group(f"/link {code}"))

    assert "direct message" in reply
    assert links.linked_user_id("ada", "qq", "90210") is None


@pytest.mark.asyncio
async def test_a_deleted_account_does_not_speak_for_anyone(partners_root, fake_orchestrator):
    from deeptutor.services.partners.manager import PartnerConfig

    fake_orchestrator.script = finish("ok")
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    code = links.issue_link_code("ada", "u_ghost").code
    links.redeem_link_code("ada", code, channel="qq", sender_id="90210")

    await runner.process_message(_dm("hi"))

    # The link survives but resolves to nobody, so the turn falls back to shared.
    assert session_store_for("ada", None).messages("qq:private:90210")
