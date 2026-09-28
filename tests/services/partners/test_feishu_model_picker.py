"""Feishu /model cards use the same validated Partner command as typed selection."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FeishuChannel
from deeptutor.services.partners import commands as commands_mod
from deeptutor.services.partners.commands import PartnerCommandHandler
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.runtime import PartnerRunner


def _catalog(count: int = 8) -> dict:
    return {
        "services": {
            "llm": {
                "active_profile_id": "profile",
                "active_model_id": "model-0",
                "profiles": [
                    {
                        "id": "profile",
                        "name": "Test profile",
                        "binding": "openai",
                        "models": [
                            {"id": f"model-{index}", "name": f"Model {index}", "model": f"m{index}"}
                            for index in range(count)
                        ],
                    }
                ],
            }
        }
    }


def _message(content: str, *, chat_type: str = "p2p", actor=None) -> InboundMessage:
    return InboundMessage(
        channel="feishu",
        sender_id="ou_owner",
        chat_id="ou_owner" if chat_type == "p2p" else "oc_group",
        content=content,
        metadata={"chat_type": chat_type},
        actor=actor,
    )


def _handler(monkeypatch, config=None, *, save=None) -> PartnerCommandHandler:
    monkeypatch.setattr(
        commands_mod,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=lambda: _catalog()),
    )
    return PartnerCommandHandler(
        partner_id="ada",
        config=config or PartnerConfig(name="Ada"),
        store=MagicMock(),
        save_config=save,
    )


def _channel() -> FeishuChannel:
    channel = FeishuChannel(
        {"enabled": True, "appId": "app", "appSecret": "secret", "allowFrom": ["ou_owner"]},
        MessageBus(),
    )
    channel._client = SimpleNamespace(
        im=SimpleNamespace(v1=SimpleNamespace(message=SimpleNamespace(patch=MagicMock())))
    )
    return channel


def _callback(value: dict, *, sender: str = "ou_owner", message_id: str = "om_picker"):
    return SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(value=value),
            operator=SimpleNamespace(open_id=sender),
            context=SimpleNamespace(open_message_id=message_id, open_chat_id="oc_private"),
        )
    )


def test_model_command_lists_choices_and_keeps_group_text_only(monkeypatch) -> None:
    handler = _handler(monkeypatch)
    private = handler.dispatch(_message("/model", actor=SimpleNamespace(is_admin=True)))
    assert private is not None
    assert "1. OpenAI · Model 0 (current)" in private.content
    assert len(private.metadata["_feishu_model_options"]) == 8

    group = handler.dispatch(_message("/model", chat_type="group"))
    assert group is not None and group.metadata is None
    assert "linked direct message" in group.content

    unlinked = handler.dispatch(_message("/model"))
    assert unlinked is not None and "Link this chat" in unlinked.content
    assert unlinked.metadata is None


def test_model_switch_requires_linked_manager_and_persists_valid_pair(monkeypatch) -> None:
    saved = []
    config = PartnerConfig(name="Ada", model="legacy-model")
    handler = _handler(
        monkeypatch, config, save=lambda partner_id, cfg: saved.append((partner_id, cfg))
    )
    monkeypatch.setattr(
        commands_mod, "can_manage_partner", lambda partner_id, actor: actor.is_admin
    )

    denied = handler.dispatch(_message("/model 2"))
    assert denied is not None and "Link this chat" in denied.content
    assert config.llm_selection is None and saved == []

    actor = SimpleNamespace(is_admin=True)
    switched = handler.dispatch(_message("/model 2", actor=actor))
    assert switched is not None and switched.metadata["_feishu_model_switch_success"]
    assert "legacy-model → OpenAI · Model 1" in switched.content
    assert config.llm_selection == {"profile_id": "profile", "model_id": "model-1"}
    assert config.model is None
    assert saved == [("ada", config)]

    invalid = handler.dispatch(_message("/model missing model-999", actor=actor))
    assert invalid is not None and "Unknown model" in invalid.content
    assert len(saved) == 1


def test_selecting_catalog_default_clears_legacy_model_override(monkeypatch) -> None:
    saved = []
    config = PartnerConfig(name="Ada", model="legacy-model")
    handler = _handler(monkeypatch, config, save=lambda partner_id, cfg: saved.append(partner_id))
    monkeypatch.setattr(commands_mod, "can_manage_partner", lambda partner_id, actor: True)

    result = handler.dispatch(_message("/model 1", actor=SimpleNamespace(is_admin=True)))
    assert result is not None and result.metadata["_feishu_model_switch_success"]
    assert config.llm_selection == {"profile_id": "profile", "model_id": "model-0"}
    assert config.model is None
    assert saved == ["ada"]


@pytest.mark.asyncio
async def test_runner_carries_picker_result_to_feishu_delivery(monkeypatch, partners_root) -> None:
    monkeypatch.setattr(
        commands_mod,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=lambda: _catalog()),
    )
    runner = PartnerRunner("ada", PartnerConfig(name="Ada"), MessageBus())
    outbound_metadata: dict = {}
    listing = await runner.process_message(
        _message("/model", actor=SimpleNamespace(is_admin=True)),
        delivery_meta=outbound_metadata,
    )
    assert "Available models" in listing
    assert len(outbound_metadata["_feishu_model_options"]) == 8

    callback_metadata: dict = {}
    denied = await runner.process_message(
        _message("/model profile model-1"), delivery_meta=callback_metadata
    )
    assert "Link this chat" in denied
    assert "_feishu_model_switch_success" not in callback_metadata

    callback = _message("/model profile model-1", actor=SimpleNamespace(is_admin=True))
    callback.metadata.update(
        {"_feishu_model_picker_message_id": "om_picker", "_feishu_model_picker_id": "picker"}
    )
    await runner._handle_inbound(callback)
    outbound = await runner.bus.consume_outbound()
    assert outbound.metadata["_feishu_model_picker_message_id"] == "om_picker"
    assert outbound.metadata["_feishu_model_picker_id"] == "picker"
    assert outbound.metadata["_feishu_model_switch_success"] is True


@pytest.mark.asyncio
async def test_private_picker_pages_in_place_and_queues_selection() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._loop = asyncio.get_running_loop()
    channel._send_message_sync = MagicMock(return_value=True)
    options = [
        {
            "profile_id": "profile",
            "model_id": f"model-{index}",
            "provider_label": "OpenAI",
            "profile_name": "Primary",
            "model_name": f"Model {index}",
            "model": f"m{index}",
        }
        for index in range(8)
    ] + [
        {
            "profile_id": "second",
            "model_id": "model-b",
            "provider_label": "OpenAI",
            "profile_name": "Backup",
            "model_name": "Model 7",
            "model": "backup-wire",
        }
    ]
    options[6]["model_name"] = "Model 7"  # duplicate display name within one profile
    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_owner",
            content="Available models",
            metadata={
                "_feishu_model_options": options,
                "_feishu_model_providers": [
                    {"profile_id": "profile", "profile_name": "Primary"},
                    {"profile_id": "second", "profile_name": "Backup"},
                ],
                "_feishu_model_current": {"profile_id": "profile", "model_id": "model-0"},
            },
        )
    )
    send_args = channel._send_message_sync.call_args.args
    assert send_args[:3] == ("open_id", "ou_owner", "interactive")
    first = json.loads(send_args[3])
    first_actions = [e for e in first["elements"] if e["tag"] == "action"]
    assert len(first_actions) == 2  # one button per provider, with no model count
    assert first_actions[0]["actions"][0]["text"]["content"] == "✓ Primary"
    assert first_actions[1]["actions"][0]["text"]["content"] == "Backup"
    picker_id = first_actions[0]["actions"][0]["value"]["picker_id"]
    assert len(picker_id) == 16
    assert "model_id" not in first_actions[0]["actions"][0]["value"]

    provider_response = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "pick_provider", "index": 0})
    )
    assert provider_response.card.type == "raw"
    provider_card = provider_response.card.data
    assert "Primary · Choose a model" in provider_card["elements"][0]["text"]["content"]
    assert len([e for e in provider_card["elements"] if e["tag"] == "action"]) == 7

    page_response = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "page", "provider_index": 0, "page": 1})
    )
    assert page_response.card.type == "raw"
    assert "Page 2 of 2" in page_response.card.data["elements"][0]["text"]["content"]
    assert len([e for e in page_response.card.data["elements"] if e["tag"] == "action"]) == 3
    assert "Model 7 (m6)" in page_response.card.data["elements"][1]["actions"][0]["text"]["content"]
    assert "Model 7 (m7)" in page_response.card.data["elements"][2]["actions"][0]["text"]["content"]
    assert channel.bus.inbound.empty()
    channel._send_message_sync.assert_called_once()  # page callback sends no message

    wrong_user = channel._on_card_action_sync(
        _callback(
            {"picker_id": picker_id, "action": "select", "provider_index": 0, "index": 7},
            sender="ou_other",
        )
    )
    assert wrong_user.toast.type == "error"
    assert channel.bus.inbound.empty()

    switching = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "select", "provider_index": 0, "index": 7})
    )
    assert "⏳ Switching model" in switching.card.data["elements"][0]["text"]["content"]
    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1)
    assert inbound.content == "/model profile model-7"
    assert inbound.chat_id == "ou_owner"  # callback context has oc_, send target is ou_
    assert inbound.metadata["_feishu_model_picker_message_id"] == "om_picker"
    assert inbound.metadata["_feishu_model_picker_id"] == picker_id

    channel._client.im.v1.message.patch.return_value = SimpleNamespace(success=lambda: True)
    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_owner",
            content="✅ Switched model: OpenAI · Model 0 → OpenAI · Model 7.",
            metadata={
                "_feishu_model_picker_message_id": "om_picker",
                "_feishu_model_picker_id": picker_id,
                "_feishu_model_switch_success": True,
            },
        )
    )
    patched = json.loads(channel._client.im.v1.message.patch.call_args.args[0].request_body.content)
    assert "✅ Switched model" in patched["elements"][0]["text"]["content"]
    assert "Page 2 of 2" in patched["elements"][1]["text"]["content"]
    assert channel._model_pickers[picker_id].pending is False
    assert channel._model_pickers[picker_id].current == {
        "profile_id": "profile",
        "model_id": "model-7",
    }

    back = channel._on_card_action_sync(_callback({"picker_id": picker_id, "action": "providers"}))
    assert back.card.data["elements"][0]["text"]["content"] == "Choose a provider"
    scoped = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "pick_provider", "index": 1})
    )
    scoped_actions = [e for e in scoped.card.data["elements"] if e["tag"] == "action"]
    assert len(scoped_actions) == 2  # one model plus back button
    assert "Model 7" in scoped_actions[0]["actions"][0]["text"]["content"]
    second = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "select", "provider_index": 1, "index": 8})
    )
    assert second.card.type == "raw"  # the first switch released the guard
    second_inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1)
    assert second_inbound.content == "/model second model-b"

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_owner",
            content="Could not switch model: catalog changed.",
            metadata={
                "_feishu_model_picker_message_id": "om_picker",
                "_feishu_model_picker_id": picker_id,
            },
        )
    )
    failed_card = json.loads(
        channel._client.im.v1.message.patch.call_args.args[0].request_body.content
    )
    assert "⚠️ Could not switch model" in failed_card["elements"][0]["text"]["content"]
    assert channel._model_pickers[picker_id].pending is False
    assert channel._model_pickers[picker_id].current["profile_id"] == "profile"
    retry = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "select", "provider_index": 1, "index": 8})
    )
    assert retry.card.type == "raw"
    assert (await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1)).content == (
        "/model second model-b"
    )


@pytest.mark.asyncio
async def test_picker_releases_guard_if_callback_cannot_queue_command() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._loop = asyncio.get_running_loop()
    channel._send_message_sync = MagicMock(return_value=True)
    channel._handle_message = AsyncMock(side_effect=RuntimeError("queue unavailable"))
    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_owner",
            content="Available models",
            metadata={
                "_feishu_model_options": [
                    {
                        "profile_id": "profile",
                        "model_id": "model-1",
                        "model_name": "Model 1",
                        "model": "m1",
                    }
                ]
            },
        )
    )
    card = json.loads(channel._send_message_sync.call_args.args[3])
    picker_id = card["elements"][1]["actions"][0]["value"]["picker_id"]
    response = channel._on_card_action_sync(
        _callback({"picker_id": picker_id, "action": "select", "provider_index": 0, "index": 0})
    )
    assert response.card.type == "raw"

    async def guard_released() -> bool:
        for _ in range(20):
            if not channel._model_pickers[picker_id].pending:
                return True
            await asyncio.sleep(0.01)
        return False

    assert await guard_released()


@pytest.mark.asyncio
async def test_picker_releases_guard_when_queue_future_already_failed(monkeypatch) -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._loop = asyncio.get_running_loop()
    channel._send_message_sync = MagicMock(return_value=True)
    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_owner",
            content="Available models",
            metadata={
                "_feishu_model_options": [
                    {
                        "profile_id": "profile",
                        "model_id": "model-1",
                        "model_name": "Model 1",
                        "model": "wire-name",
                    }
                ]
            },
        )
    )
    card = json.loads(channel._send_message_sync.call_args.args[3])
    picker_id = card["elements"][1]["actions"][0]["value"]["picker_id"]

    def already_failed(coro, _loop):
        coro.close()
        future = Future()
        future.set_exception(RuntimeError("queue failed"))
        return future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", already_failed)
    responses = []
    worker = threading.Thread(
        target=lambda: responses.append(
            channel._on_card_action_sync(
                _callback(
                    {"picker_id": picker_id, "action": "select", "provider_index": 0, "index": 0}
                )
            )
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive(), "a completed queue future must not deadlock the callback"
    assert responses[0].card.type == "raw"
    assert channel._model_pickers[picker_id].pending is False


@pytest.mark.asyncio
async def test_model_switch_patches_clicked_card_then_uses_text_fallback_on_failure() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._client.im.v1.message.patch.return_value = SimpleNamespace(success=lambda: True)
    channel._send_message_sync = MagicMock(return_value=True)
    outbound = OutboundMessage(
        channel="feishu",
        chat_id="ou_owner",
        content="✅ Switched model: Old → New.",
        metadata={
            "_feishu_model_picker_message_id": "om_picker",
            "_feishu_model_switch_success": True,
        },
    )
    await channel.send(outbound)
    request = channel._client.im.v1.message.patch.call_args.args[0]
    assert request.paths["message_id"] == "om_picker"
    assert "✅ Switched model: Old → New." in request.request_body.content
    channel._send_message_sync.assert_not_called()

    channel._client.im.v1.message.patch.return_value = SimpleNamespace(
        success=lambda: False, code=500, msg="failed"
    )
    await channel.send(outbound)
    fallback = channel._send_message_sync.call_args.args
    assert fallback[:3] == ("open_id", "ou_owner", "text")
    assert "✅ Switched model: Old → New." in json.loads(fallback[3])["text"]
