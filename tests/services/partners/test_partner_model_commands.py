"""Partner /model browse and selection use only visible catalog options."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

from deeptutor.partners.bus.events import InboundMessage
from deeptutor.services.partners import commands as commands_mod
from deeptutor.services.partners.commands import PartnerCommandHandler
from deeptutor.services.partners.manager import PartnerConfig


def _catalog() -> dict:
    return {
        "services": {
            "llm": {
                "active_profile_id": "alpha",
                "active_model_id": "alpha-one",
                "profiles": [
                    {
                        "id": "alpha",
                        "name": "Alpha account",
                        "binding": "openai",
                        "models": [
                            {"id": "alpha-one", "name": "Shared", "model": "alpha/one"},
                            {"id": "alpha-two", "name": "Shared", "model": "alpha/two"},
                        ],
                    },
                    {
                        "id": "beta",
                        "name": "Beta account",
                        "binding": "openai",
                        "models": [
                            {"id": "beta-one", "name": "Distinct", "model": "beta/one"},
                        ],
                    },
                ],
            }
        }
    }


def _message(content: str, *, actor=None, chat_type: str = "p2p") -> InboundMessage:
    return InboundMessage(
        channel="feishu",
        sender_id="owner",
        chat_id="owner" if chat_type == "p2p" else "group",
        content=content,
        metadata={"chat_type": chat_type},
        actor=actor,
    )


def _handler(monkeypatch, *, config: PartnerConfig | None = None, save=None):
    service = SimpleNamespace(load=MagicMock(return_value=_catalog()), refresh_models=MagicMock())
    monkeypatch.setattr(commands_mod, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(commands_mod, "can_manage_partner", lambda _partner_id, _actor: True)
    handler = PartnerCommandHandler(
        partner_id="ada",
        config=config or PartnerConfig(name="Ada"),
        store=MagicMock(),
        save_config=save,
    )
    return handler, service


def test_model_browse_groups_visible_profiles_without_live_refresh(monkeypatch) -> None:
    handler, service = _handler(monkeypatch)
    actor = SimpleNamespace(is_admin=False)
    monkeypatch.setattr(commands_mod, "user_context", lambda _actor: nullcontext())
    monkeypatch.setattr(
        commands_mod,
        "allowed_llm_options",
        lambda: {"options": [{"profile_id": "alpha", "model_id": "alpha-two"}]},
    )

    result = handler.dispatch(_message("/model", actor=actor))

    assert result is not None and result.metadata is not None
    assert [
        (row["profile_id"], row["model_id"]) for row in result.metadata["_feishu_model_options"]
    ] == [("alpha", "alpha-two")]
    assert result.metadata["_feishu_model_providers"] == [
        {
            "profile_id": "alpha",
            "provider_label": "OpenAI",
            "profile_name": "Alpha account",
        }
    ]
    assert "Beta account" not in result.content
    service.load.assert_called_once_with()
    service.refresh_models.assert_not_called()

    group = handler.dispatch(_message("/model", actor=actor, chat_type="group"))
    assert group is not None and group.metadata is None
    unlinked = handler.dispatch(_message("/model"))
    assert unlinked is not None and unlinked.metadata is None


def test_model_browse_keeps_same_provider_profiles_distinct(monkeypatch) -> None:
    handler, _service = _handler(monkeypatch)

    result = handler.dispatch(_message("/model", actor=SimpleNamespace(is_admin=True)))

    assert result is not None and result.metadata is not None
    assert result.metadata["_feishu_model_providers"] == [
        {"profile_id": "alpha", "provider_label": "OpenAI", "profile_name": "Alpha account"},
        {"profile_id": "beta", "provider_label": "OpenAI", "profile_name": "Beta account"},
    ]
    assert "1. OpenAI · Shared (alpha/one) (current)" in result.content
    assert "2. OpenAI · Shared (alpha/two)" in result.content


def test_model_switch_prefers_wire_value_and_accepts_model_id(monkeypatch) -> None:
    saved: list[dict[str, str]] = []
    config = PartnerConfig(name="Ada")
    handler, _service = _handler(
        monkeypatch,
        config=config,
        save=lambda _partner_id, value: saved.append(value.llm_selection.copy()),
    )
    actor = SimpleNamespace(is_admin=True)

    ambiguous = handler.dispatch(_message("/model Shared", actor=actor))
    assert ambiguous is not None and "wire model name" in ambiguous.content
    assert saved == []

    selected = handler.dispatch(_message("/model alpha alpha/two", actor=actor))
    assert selected is not None and selected.metadata == {"_feishu_model_switch_success": True}
    assert "OpenAI · Shared (alpha/two)" in selected.content
    assert config.llm_selection == {"profile_id": "alpha", "model_id": "alpha-two"}

    selected_by_id = handler.dispatch(_message("/model alpha alpha-one", actor=actor))
    assert selected_by_id is not None and selected_by_id.metadata == {
        "_feishu_model_switch_success": True
    }
    assert config.llm_selection == {"profile_id": "alpha", "model_id": "alpha-one"}
    assert saved == [
        {"profile_id": "alpha", "model_id": "alpha-two"},
        {"profile_id": "alpha", "model_id": "alpha-one"},
    ]


def test_picker_can_select_model_id_when_profile_has_duplicate_wire_names(monkeypatch) -> None:
    config = PartnerConfig(name="Ada")
    handler, service = _handler(monkeypatch, config=config)
    catalog = service.load.return_value
    catalog["services"]["llm"]["profiles"][0]["models"][1]["model"] = "alpha/one"
    actor = SimpleNamespace(is_admin=True)

    typed = handler.dispatch(_message("/model alpha alpha/one", actor=actor))
    assert typed is not None and "ambiguous" in typed.content

    picker_message = _message("/model alpha alpha-two", actor=actor)
    picker_message.metadata["_feishu_model_picker_id"] = "server-owned-picker"
    selected = handler.dispatch(picker_message)

    assert selected is not None and selected.metadata == {"_feishu_model_switch_success": True}
    assert config.llm_selection == {"profile_id": "alpha", "model_id": "alpha-two"}
