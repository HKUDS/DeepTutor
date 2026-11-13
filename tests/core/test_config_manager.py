import os
from pathlib import Path

import pytest
import yaml

from deeptutor.services.memory.settings import load_memory_settings
from deeptutor.utils.config_manager import ConfigManager


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_config_manager_singleton():
    ConfigManager.reset_for_tests()
    yield
    ConfigManager.reset_for_tests()


def test_atomic_save_and_deep_merge(tmp_path: Path):
    project = tmp_path
    cfg_path = project / "data" / "user" / "settings" / "main.yaml"
    base_cfg = {
        "llm": {"model": "Pro/Flash", "provider": "openai"},
        "paths": {
            "user_data_dir": "./data/user",
            "knowledge_bases_dir": "./data/knowledge_bases",
            "user_log_dir": "./data/user/logs",
        },
    }
    write_yaml(cfg_path, base_cfg)

    cm = ConfigManager(project_root=project)

    loaded = cm.load_config(force_reload=True)
    assert loaded["llm"]["model"] == "Pro/Flash"

    # Deep merge update
    assert cm.save_config({"llm": {"model": "Other"}, "features": {"enable_solve": True}})

    updated = cm.load_config(force_reload=True)
    assert updated["llm"]["model"] == "Other"
    assert updated["llm"]["provider"] == "openai"
    assert updated["features"]["enable_solve"] is True


def test_env_info_reads_project_model_catalog(tmp_path: Path):
    project = tmp_path

    # Minimal valid config for schema
    settings_dir = project / "data" / "user" / "settings"
    cfg_path = settings_dir / "main.yaml"
    base_cfg = {
        "llm": {"model": "Pro/Flash", "provider": "openai"},
        "paths": {
            "user_data_dir": "./data/user",
            "knowledge_bases_dir": "./data/knowledge_bases",
            "user_log_dir": "./data/user/logs",
        },
    }
    write_yaml(cfg_path, base_cfg)
    (settings_dir / "model_catalog.json").write_text(
        """
{
  "version": 1,
  "services": {
    "llm": {
      "active_profile_id": "llm-p",
      "active_model_id": "llm-m",
      "profiles": [
        {
          "id": "llm-p",
          "name": "LLM",
          "binding": "openai",
          "base_url": "https://example.test/v1",
          "api_key": "sk-test",
          "api_version": "",
          "extra_headers": {},
          "models": [{"id": "llm-m", "name": "Base", "model": "Base"}]
        }
      ]
    },
    "embedding": {"active_profile_id": null, "active_model_id": null, "profiles": []},
    "search": {"active_profile_id": null, "profiles": []}
  }
}
""",
        encoding="utf-8",
    )

    cm = ConfigManager(project_root=project)
    env = cm.get_env_info()
    assert env["model"] == "Base"


@pytest.mark.parametrize(
    ("mtime", "force_reload", "expected_budget"),
    [(1000, False, 40), (3000, False, 40), (2000, False, 20), (2000, True, 40)],
)
def test_reload_tracks_timestamp_changes_and_force(tmp_path, mtime, force_reload, expected_budget):
    manager = ConfigManager(project_root=tmp_path)
    write_yaml(manager.config_path, {"memory": {"update": {"l2_budget": 20}}})
    os.utime(manager.config_path, (2000, 2000))
    assert load_memory_settings().update.l2_budget == 20

    write_yaml(manager.config_path, {"memory": {"update": {"l2_budget": 40}}})
    os.utime(manager.config_path, (mtime, mtime))

    loaded = manager.load_config(force_reload=force_reload)
    assert loaded["memory"]["update"]["l2_budget"] == expected_budget
    assert load_memory_settings().update.l2_budget == expected_budget


def test_removing_config_clears_cached_values(tmp_path):
    manager = ConfigManager(project_root=tmp_path)
    write_yaml(manager.config_path, {"enabled": True})
    assert manager.load_config() == {"enabled": True}

    manager.config_path.unlink()

    assert manager.load_config() == {}
