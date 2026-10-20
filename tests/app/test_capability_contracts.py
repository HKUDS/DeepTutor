"""The public SDK returns JSON-compatible capability availability contracts."""

import importlib.util
import json

import pytest

from deeptutor.app import DeepTutorApp


def test_single_capability_contract_serializes_availability() -> None:
    contract = DeepTutorApp().get_capability_contract("chat")

    assert contract["name"] == "chat"
    assert contract["availability"] == {
        "name": "chat",
        "available": True,
        "install_hint": "",
    }
    assert json.loads(json.dumps(contract))["availability"] == contract["availability"]


@pytest.mark.parametrize("manim_available", [False, True])
def test_capability_list_preserves_optional_install_hint(
    monkeypatch: pytest.MonkeyPatch, manim_available: bool
) -> None:
    original_find_spec = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object | None:
        if name == "manim":
            return object() if manim_available else None
        return original_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    contracts = DeepTutorApp().get_capability_contracts()
    by_name = {contract["name"]: contract for contract in json.loads(json.dumps(contracts))}

    assert by_name["chat"]["availability"]["available"] is True
    availability = by_name["math_animator"]["availability"]
    assert availability["name"] == "math_animator"
    assert availability["available"] is manim_available
    if manim_available:
        assert availability["install_hint"] == ""
    else:
        assert "math-animator" in availability["install_hint"]
