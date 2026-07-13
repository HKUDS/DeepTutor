from __future__ import annotations

from pathlib import Path

from deeptutor.services.path_service import PathService


def test_public_output_filter_allows_only_whitelisted_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "deep_solve"
            / "solve_1"
            / "artifacts"
            / "plot.png"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text("png", encoding="utf-8")

        denied = service._user_data_dir / "settings" / "model_catalog.json"
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("{}", encoding="utf-8")

        assert (
            service.is_public_output_path("workspace/chat/deep_solve/solve_1/artifacts/plot.png")
            is True
        )
        assert service.is_public_output_path("settings/model_catalog.json") is False
        assert service.is_public_output_path("../outside.txt") is False
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_public_output_filter_allows_math_animator_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "math_animator"
            / "turn_1"
            / "artifacts"
            / "animation.mp4"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text("video", encoding="utf-8")

        denied = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "math_animator"
            / "turn_1"
            / "source"
            / "scene.py"
        )
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("print('debug')", encoding="utf-8")

        assert (
            service.is_public_output_path(
                "workspace/chat/math_animator/turn_1/artifacts/animation.mp4"
            )
            is True
        )
        assert (
            service.is_public_output_path("workspace/chat/math_animator/turn_1/source/scene.py")
            is False
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_public_output_filter_allows_chat_exec_artifacts(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "chat"
            / "chat"
            / "turn_1"
            / "exec"
            / "report.pdf"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_bytes(b"%PDF-1.4\n")

        private_script = allowed.with_name("build.py")
        private_script.write_text("print('internal')", encoding="utf-8")
        private_log = allowed.with_name("output.log")
        private_log.write_text("debug", encoding="utf-8")

        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/report.pdf") is True
        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/build.py") is False
        assert service.is_public_output_path("workspace/chat/chat/turn_1/exec/output.log") is False
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_task_workspace_maps_capabilities_into_workspace_chat(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        assert service.get_task_workspace("chat", "turn_1") == (
            tmp_path / "data" / "user" / "workspace" / "chat" / "chat" / "turn_1"
        )
        assert service.get_task_workspace("deep_question", "turn_2") == (
            tmp_path / "data" / "user" / "workspace" / "chat" / "deep_question" / "turn_2"
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_memory_dir_migrates_missing_legacy_markdown_when_target_exists(
    tmp_path: Path,
) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    original_workspace_root = service._workspace_root

    try:
        service._project_root = tmp_path
        service._workspace_root = tmp_path / "data"
        service._user_data_dir = tmp_path / "data" / "user"

        old_dir = service.get_workspace_feature_dir("memory")
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "SUMMARY.md").write_text("legacy summary", encoding="utf-8")
        (old_dir / "PROFILE.md").write_text("legacy profile", encoding="utf-8")

        new_dir = tmp_path / "data" / "memory"
        new_dir.mkdir(parents=True, exist_ok=True)

        assert service.get_memory_dir() == new_dir
        assert (new_dir / "SUMMARY.md").read_text(encoding="utf-8") == "legacy summary"
        assert (new_dir / "PROFILE.md").read_text(encoding="utf-8") == "legacy profile"
    finally:
        service._project_root = original_root
        service._workspace_root = original_workspace_root
        service._user_data_dir = original_user_dir


def test_memory_dir_migration_preserves_existing_target_files(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir
    original_workspace_root = service._workspace_root

    try:
        service._project_root = tmp_path
        service._workspace_root = tmp_path / "data"
        service._user_data_dir = tmp_path / "data" / "user"

        old_dir = service.get_workspace_feature_dir("memory")
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "PROFILE.md").write_text("legacy profile", encoding="utf-8")

        new_dir = tmp_path / "data" / "memory"
        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "PROFILE.md").write_text("current profile", encoding="utf-8")

        assert service.get_memory_dir() == new_dir
        assert (new_dir / "PROFILE.md").read_text(encoding="utf-8") == "current profile"
    finally:
        service._project_root = original_root
        service._workspace_root = original_workspace_root
        service._user_data_dir = original_user_dir
