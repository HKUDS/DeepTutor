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

        denied = service._user_data_dir / "settings" / "env.json"
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("{}", encoding="utf-8")

        assert (
            service.is_public_output_path("workspace/chat/deep_solve/solve_1/artifacts/plot.png")
            is True
        )
        assert service.is_public_output_path("settings/env.json") is False
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


def test_public_output_filter_allows_structure_note_markdown_pdf_and_images(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        allowed = (
            service._user_data_dir
            / "workspace"
            / "structure_note"
            / "job_1"
            / "final"
            / "Week3-structure-note.pdf"
        )
        allowed.parent.mkdir(parents=True, exist_ok=True)
        allowed.write_text("pdf", encoding="utf-8")
        allowed_md = allowed.with_name("Week3-structure-note.md")
        allowed_md.write_text("# Note", encoding="utf-8")
        allowed_image = (
            service._user_data_dir
            / "workspace"
            / "structure_note"
            / "job_1"
            / "images"
            / "figure.png"
        )
        allowed_image.parent.mkdir(parents=True, exist_ok=True)
        allowed_image.write_text("png", encoding="utf-8")

        denied = (
            service._user_data_dir
            / "workspace"
            / "structure_note"
            / "job_1"
            / "chunks"
            / "generation_chunks.json"
        )
        denied.parent.mkdir(parents=True, exist_ok=True)
        denied.write_text("{}", encoding="utf-8")

        assert (
            service.is_public_output_path(
                "workspace/structure_note/job_1/final/Week3-structure-note.pdf"
            )
            is True
        )
        assert (
            service.is_public_output_path(
                "workspace/structure_note/job_1/final/Week3-structure-note.md"
            )
            is True
        )
        assert (
            service.is_public_output_path("workspace/structure_note/job_1/images/figure.png")
            is True
        )
        assert (
            service.is_public_output_path(
                "workspace/structure_note/job_1/chunks/generation_chunks.json"
            )
            is False
        )
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir
