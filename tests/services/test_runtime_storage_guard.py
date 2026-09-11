from __future__ import annotations

from pathlib import Path

from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.services.config.loader import load_config_with_main
from deeptutor.services.path_service import PathService


def test_runtime_config_paths_are_confined_to_data_user() -> None:
    config = load_config_with_main("main.yaml")
    paths = config.get("paths", {})
    user_root = Path(config["paths"]["user_data_dir"]).resolve()

    assert user_root.name == "user"
    assert Path(paths["solve_output_dir"]).resolve().is_relative_to(user_root)
    assert Path(paths["question_output_dir"]).resolve().is_relative_to(user_root)
    assert Path(paths["research_output_dir"]).resolve().is_relative_to(user_root)
    assert Path(paths["research_reports_dir"]).resolve().is_relative_to(user_root)
    assert Path(paths["user_log_dir"]).resolve() == user_root / "logs"
    assert Path(config["tools"]["exec"]["workspace"]).resolve().is_relative_to(user_root)


def test_citation_manager_defaults_to_research_workspace(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        manager = CitationManager("research_123")

        assert manager.cache_dir == (
            tmp_path / "data" / "user" / "workspace" / "chat" / "deep_research" / "research_123"
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir
