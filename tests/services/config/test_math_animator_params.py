"""The animation code-repair deadline must be reachable from runtime settings.

``MathAnimatorPipeline.run_render`` built ``CodeRetryManager`` without passing a
configured ``repair_timeout_seconds``, so the loop always fell back to the
hardcoded 180s overall deadline. A long reasoning model repairing a book
animation was cancelled mid-edit with no setting anywhere that moved it (#2767).

These tests pin the seam that fixes it: the knob lives in main.yaml under
``capabilities.math_animator.repair_timeout``, round-trips through the settings
page, and is read back through the same coerce path the pipeline uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from deeptutor.services.config import capabilities_settings as module
from deeptutor.services.config.capabilities_settings import get_math_animator_params
from deeptutor.utils.config_manager import ConfigManager


@pytest.fixture(autouse=True)
def _reset_config_manager_singleton():
    ConfigManager.reset_for_tests()
    yield
    ConfigManager.reset_for_tests()


def _settings_root(
    tmp_path: Path, agents_content: dict[str, Any], main_content: dict[str, Any] | None = None
) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "agents.yaml").write_text(yaml.dump(agents_content), encoding="utf-8")
    if main_content is not None:
        (settings_dir / "main.yaml").write_text(yaml.dump(main_content), encoding="utf-8")
    # Seed the singleton so ``ConfigManager()`` inside the module reads tmp, not
    # the real repo root. Must happen before any code constructs ConfigManager().
    ConfigManager(project_root=tmp_path)
    return tmp_path


def test_repair_timeout_default_matches_the_previously_hardcoded_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An install that never touched this keeps exactly the old 180s behaviour."""
    monkeypatch.setattr(module, "PROJECT_ROOT", _settings_root(tmp_path, {"capabilities": {}}))

    assert get_math_animator_params() == {"repair_timeout": 180}
    assert "repair_timeout" not in module.capabilities_settings_dict()["math_animator"]


def test_repair_timeout_is_overridable_from_main_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "PROJECT_ROOT",
        _settings_root(
            tmp_path,
            {"capabilities": {}},
            {"capabilities": {"math_animator": {"repair_timeout": 600}}},
        ),
    )

    assert get_math_animator_params() == {"repair_timeout": 600}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 1), (-5, 1), (999_999, 3600), ("junk", 180), (None, 180)],
)
def test_repair_timeout_is_clamped_to_a_sane_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: Any, expected: int
) -> None:
    monkeypatch.setattr(
        module,
        "PROJECT_ROOT",
        _settings_root(
            tmp_path,
            {"capabilities": {}},
            {"capabilities": {"math_animator": {"repair_timeout": raw}}},
        ),
    )

    assert get_math_animator_params()["repair_timeout"] == expected


def test_configured_repair_timeout_round_trips_through_the_settings_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        module,
        "PROJECT_ROOT",
        _settings_root(
            tmp_path,
            {"capabilities": {}},
            {"capabilities": {"math_animator": {"repair_timeout": 320}}},
        ),
    )

    payload = module.capabilities_settings_dict()
    assert payload["math_animator"]["repair_timeout"] == 320
    assert payload["math_animator"]["temperature"] == 0.2
    assert payload["math_animator"]["max_tokens"] == 16834

    payload["visualize"]["max_tokens"] = 32000
    module.save_capabilities_settings(payload)

    assert get_math_animator_params()["repair_timeout"] == 320
    main_cfg = ConfigManager().load_config()
    assert main_cfg["capabilities"]["math_animator"]["repair_timeout"] == 320


def test_saving_another_capability_does_not_shadow_the_repair_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real Settings page GETs the full DTO and PUTs it back verbatim."""
    monkeypatch.setattr(module, "PROJECT_ROOT", _settings_root(tmp_path, {"capabilities": {}}))

    payload = module.capabilities_settings_dict()
    payload["visualize"]["max_tokens"] = 32000
    module.save_capabilities_settings(payload)

    main_cfg = ConfigManager().load_config()
    assert "math_animator" not in main_cfg.get("capabilities", {})
    assert get_math_animator_params()["repair_timeout"] == 180
