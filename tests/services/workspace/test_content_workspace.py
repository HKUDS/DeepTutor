from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.runtime.agentic import DispatchOutcome
from deeptutor.services.path_service import PathService
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.execution import (
    logical_workspace_path,
    logicalize_workspace_text,
    prepare_workspace_execution_env,
)
from deeptutor.tools.workspace import (
    WorkspaceExportTool,
    WorkspaceListTool,
    WorkspacePresentTool,
    WorkspaceReadTool,
    WorkspaceSearchTool,
)


@pytest.fixture
def workspace_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from deeptutor.services.workspace import service as service_module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    return ContentWorkspaceService(), paths


def test_default_workspace_keeps_runtime_compatible_layout(workspace_service) -> None:
    service, paths = workspace_service
    binding = service.current_binding(ensure_output=True)

    assert binding.root == paths.get_workspace_dir().resolve()
    assert binding.is_default is True
    assert (binding.root / "outputs").is_dir()


def test_custom_workspace_is_saved_and_turn_output_is_scoped(
    workspace_service, tmp_path: Path
) -> None:
    service, _paths = workspace_service
    custom = tmp_path / "course-project"
    custom.mkdir()

    binding = service.set_workspace(custom)
    context = service.create_runtime_context(
        capability="deep research",
        session_id="session/one",
        turn_id="turn:1",
    )

    assert service.current_binding().workspace_id == binding.workspace_id
    assert context.root == str(custom.resolve())
    assert context.logical_output_dir == "outputs/deep_research/session_one/turn_1"
    assert Path(context.output_dir).is_dir()


def test_writes_are_confined_to_outputs(workspace_service) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)

    with pytest.raises(WorkspaceError, match="outside outputs"):
        service.resolve(binding, "notes/source.md", write=True)
    with pytest.raises(WorkspaceError, match="cannot leave"):
        service.resolve(binding, "../secret.txt")


def test_symlink_cannot_escape_workspace(workspace_service, tmp_path: Path) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = binding.root / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspaceError, match="leaves"):
        service.resolve(binding, "outside-link.txt")


def test_outputs_symlink_is_rejected_before_write(workspace_service, tmp_path: Path) -> None:
    service, paths = workspace_service
    root = paths.get_workspace_dir().resolve()
    outputs = root / "outputs"
    if outputs.exists():
        outputs.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        outputs.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspaceError, match="leaves"):
        service.current_binding(ensure_output=True)
    assert not any(outside.iterdir())


def test_presentation_is_a_fixed_content_addressed_version(workspace_service) -> None:
    service, paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "notes.md"
    source.write_text("version one", encoding="utf-8")

    first = service.publish(binding, [{"path": "notes.md", "title": "Notes"}])[0]
    duplicate = service.publish(binding, [{"path": "notes.md", "title": "Notes"}])[0]
    source.write_text("version two", encoding="utf-8")
    second = service.publish(binding, [{"path": "notes.md", "title": "Notes"}])[0]
    blob, loaded = service.resolve_published_item(first.workspace_id, first.workspace_item_id)

    assert blob.read_text(encoding="utf-8") == "version one"
    assert duplicate.workspace_item_id == first.workspace_item_id
    assert second.workspace_item_id != first.workspace_item_id
    assert loaded.relative_path == "notes.md"
    assert loaded.title == "Notes"
    assert loaded.url.startswith("/files/workspace-items/")
    assert blob.is_relative_to(paths.get_runtime_state_dir())
    assert not (binding.root / "outputs" / ".deeptutor").exists()


def test_private_presentation_store_rejects_symlink_redirection(
    workspace_service, tmp_path: Path
) -> None:
    service, paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    outside = tmp_path / "outside-presentations"
    outside.mkdir()
    presentation_root = paths.get_runtime_state_dir() / "workspace_presentations"
    try:
        presentation_root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspaceError, match="symbolic links"):
        service.publish(binding, [{"path": "notes.md"}])
    assert not any(outside.iterdir())


def test_private_presentation_subdirectory_rejects_symlink_redirection(
    workspace_service, tmp_path: Path
) -> None:
    service, paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    outside = tmp_path / "outside-blobs"
    outside.mkdir()
    private_root = paths.get_runtime_state_dir() / "workspace_presentations" / binding.workspace_id
    private_root.mkdir(parents=True)
    try:
        (private_root / "blobs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspaceError, match="symbolic links"):
        service.publish(binding, [{"path": "notes.md"}])
    assert not any(outside.iterdir())


def test_artifact_delta_is_applied_before_the_result_limit(
    workspace_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    workdir = binding.root / "outputs" / "chat" / "session" / "turn" / "exec"
    workdir.mkdir(parents=True)
    for index in range(50):
        (workdir / f"a{index:02}.txt").write_text("old", encoding="utf-8")

    from deeptutor.services.sandbox.artifacts import (
        collect_public_artifact_batch,
        snapshot_public_artifact_files,
    )

    before = snapshot_public_artifact_files(workdir)
    (workdir / "z-new.txt").write_text("new", encoding="utf-8")
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service", lambda: service
    )
    batch = collect_public_artifact_batch(
        workdir,
        workspace_id=binding.workspace_id,
        max_files=50,
        changed_since=before,
    )

    assert batch.total_count == 1
    assert [artifact.filename for artifact in batch.artifacts] == ["z-new.txt"]
    assert batch.truncated is False


def test_workspace_traversal_is_bounded_and_skips_symlinks(
    workspace_service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    for index in range(4):
        (binding.root / f"entry-{index}.txt").write_text("ordinary", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("private needle", encoding="utf-8")
    link = binding.root / "external-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable")

    listed = service.list_entries_page(binding, limit=2)
    assert listed["scanned_entries"] == 2
    assert listed["truncated"] is True
    assert all(row["name"] != link.name for row in listed["entries"])

    from deeptutor.services.workspace import service as service_module

    monkeypatch.setattr(service_module, "_MAX_SEARCH_SCAN_ENTRIES", 2)
    searched = service.search_page(binding, "private needle")
    assert searched["scanned_entries"] == 2
    assert searched["truncated"] is True
    assert searched["matches"] == []


def test_question_pipeline_uses_shared_media_and_hidden_exec_binding(
    workspace_service,
) -> None:
    from deeptutor.agents.question.pipeline import QuestionPipeline

    service, _paths = workspace_service
    runtime = service.create_runtime_context(
        capability="deep_question",
        session_id="session",
        turn_id="turn",
    )
    context = UnifiedContext(
        runtime=TurnRuntimeContext(workspace=runtime),
        language="en",
    )
    pipeline = QuestionPipeline.__new__(QuestionPipeline)

    media = pipeline._augment_tool_kwargs("imagegen", {"prompt": "diagram"}, context)
    execution = pipeline._augment_tool_kwargs("exec", {"code": "print(1)"}, context)

    assert Path(media["_workspace_dir"]) == Path(runtime.output_dir) / "media"
    assert media["_workspace_id"] == runtime.workspace_id
    internal = Path(runtime.output_dir) / ".deeptutor" / "execution"
    state_mount = execution["_sandbox_mounts"][-1]
    assert Path(state_mount.host_path) == internal
    assert Path(execution["_sandbox_source_dir"]) == internal / "exec_calls"
    assert Path(execution["_sandbox_internal_root"]) == internal


@pytest.mark.asyncio
async def test_pipeline_bound_exec_keeps_source_hidden_and_artifact_public(
    workspace_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.agents.question.pipeline import QuestionPipeline
    import deeptutor.services.sandbox as sandbox_package
    from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend
    from deeptutor.tools.exec_tool import ExecTool

    service, _paths = workspace_service
    runtime = service.create_runtime_context(
        capability="deep_question",
        session_id="session",
        turn_id="turn",
    )
    context = UnifiedContext(runtime=TurnRuntimeContext(workspace=runtime))
    pipeline = QuestionPipeline.__new__(QuestionPipeline)
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service", lambda: service
    )
    backend = RestrictedSubprocessBackend()

    class _DirectSandboxService:
        async def run(self, request, *, user_id: str):
            return await backend.exec(request)

    monkeypatch.setattr(sandbox_package, "get_sandbox_service", lambda: _DirectSandboxService())
    kwargs = pipeline._augment_tool_kwargs(
        "exec",
        {
            "code": (
                "from pathlib import Path\n"
                "Path('private-source-ok.txt').write_text('ok', encoding='utf-8')\n"
                "print('created')\n"
            )
        },
        context,
    )

    result = await ExecTool().execute(**kwargs)

    state_root = Path(kwargs["_sandbox_internal_root"])
    assert result.success is True
    assert (Path(runtime.output_dir) / "exec" / "private-source-ok.txt").read_text() == "ok"
    assert next((state_root / "exec_calls").glob("python_*/main.py")).is_file()
    assert str(state_root) not in result.content
    assert str(state_root) not in result.metadata["command"]
    assert result.metadata["artifacts"][0]["filename"] == "private-source-ok.txt"


def test_internal_manifests_are_hidden_and_invalid_batch_writes_nothing(
    workspace_service,
) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "notes.md"
    source.write_text("notes", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="not a file"):
        service.publish(binding, [{"path": "missing.md"}])
    internal = binding.root / "outputs" / ".deeptutor" / "presentations"
    assert not internal.exists()

    service.publish(binding, [{"path": "notes.md"}])
    with pytest.raises(WorkspaceError, match="not listable"):
        service.list_entries(binding, "outputs/.deeptutor")
    with pytest.raises(WorkspaceError, match="not searchable"):
        service.search(binding, "notes", path="outputs/.deeptutor")


def test_one_time_export_copies_only_the_approved_output(workspace_service) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "outputs" / "chat" / "report.md"
    source.parent.mkdir(parents=True)
    source.write_text("approved version", encoding="utf-8")

    request = service.validate_export(
        binding,
        source_path="outputs/chat/report.md",
        destination_path="notes/report.md",
    )
    completed = service.export_once(
        binding,
        source_path=request["source_path"],
        destination_path=request["destination_path"],
        expected_sha256=request["sha256"],
    )

    assert completed["destination_path"] == "notes/report.md"
    assert (binding.root / "notes" / "report.md").read_text() == "approved version"
    with pytest.raises(WorkspaceError, match="already exists"):
        service.validate_export(
            binding,
            source_path="outputs/chat/report.md",
            destination_path="notes/report.md",
        )


def test_one_time_export_rejects_a_source_changed_after_prompt(workspace_service) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "outputs" / "answer.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("first", encoding="utf-8")
    request = service.validate_export(
        binding,
        source_path="outputs/answer.txt",
        destination_path="answer.txt",
    )
    source.write_text("second", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="changed after authorization"):
        service.export_once(
            binding,
            source_path=request["source_path"],
            destination_path=request["destination_path"],
            expected_sha256=request["sha256"],
        )
    assert not (binding.root / "answer.txt").exists()


def test_one_time_export_rejects_a_symlinked_destination(
    workspace_service,
) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "outputs" / "answer.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("answer", encoding="utf-8")
    real = binding.root / "real"
    real.mkdir()
    link = binding.root / "lesson"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspaceError, match="symbolic links"):
        service.validate_export(
            binding,
            source_path="outputs/answer.txt",
            destination_path="lesson/answer.txt",
        )


@pytest.mark.asyncio
async def test_universal_workspace_tools_share_one_binding(workspace_service) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    (binding.root / "lesson.txt").write_text("Fourier transform", encoding="utf-8")

    listed = await WorkspaceListTool().execute(_workspace_id=binding.workspace_id)
    searched = await WorkspaceSearchTool().execute(
        query="Fourier", _workspace_id=binding.workspace_id
    )
    read = await WorkspaceReadTool().execute(path="lesson.txt", _workspace_id=binding.workspace_id)
    presented = await WorkspacePresentTool().execute(
        items=[{"path": "lesson.txt"}], _workspace_id=binding.workspace_id
    )

    assert listed.success and "lesson.txt" in listed.content
    assert searched.success and "lesson.txt" in searched.content
    assert read.content == "Fourier transform"
    assert presented.success
    assert presented.metadata["workspace_items"][0]["relative_path"] == "lesson.txt"


@pytest.mark.asyncio
async def test_workspace_export_tool_pauses_without_writing(workspace_service) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "outputs" / "draft.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("draft", encoding="utf-8")

    result = await WorkspaceExportTool().execute(
        source_path="outputs/draft.txt",
        destination_path="draft.txt",
        reason="Save the finished draft",
        _workspace_id=binding.workspace_id,
        _language="en",
    )

    assert result.success
    assert result.pause_for_user
    assert result.metadata["workspace_export"]["destination_path"] == "draft.txt"
    assert not (binding.root / "draft.txt").exists()


@pytest.mark.asyncio
async def test_workspace_export_resume_requires_the_exact_approval(
    workspace_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _paths = workspace_service
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "outputs" / "draft.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("draft", encoding="utf-8")
    request = service.validate_export(
        binding,
        source_path="outputs/draft.txt",
        destination_path="lesson/draft.txt",
    )
    request.update(
        {
            "allow_label": "Allow once",
            "question_id": "workspace_export_authorization",
        }
    )
    dispatch = DispatchOutcome(
        pause=True,
        pause_payload={"tool_name": "workspace_export", "ask_user": {}},
        pause_tool_call_id="call-export",
        tool_metadata_by_id={"call-export": {"workspace_export": request}},
    )
    context = UnifiedContext(
        runtime=TurnRuntimeContext(
            workspace=WorkspaceRuntimeContext(
                workspace_id=binding.workspace_id,
                root=str(binding.root),
                output_dir=str(binding.root / "outputs"),
            )
        )
    )
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service", lambda: service
    )

    denied = await AgenticChatPipeline._resolve_workspace_export(
        context=context,
        dispatch=dispatch,
        reply_text="Deny",
        answers=[{"questionId": "workspace_export_authorization", "text": "Deny"}],
    )
    assert "denied" in denied
    assert not (binding.root / "lesson" / "draft.txt").exists()

    approved = await AgenticChatPipeline._resolve_workspace_export(
        context=context,
        dispatch=dispatch,
        reply_text="Allow once",
        answers=[
            {
                "questionId": "workspace_export_authorization",
                "text": "Allow once",
            }
        ],
    )
    assert "completed" in approved
    assert (binding.root / "lesson" / "draft.txt").read_text() == "draft"


def test_deployment_root_locks_user_selection(
    workspace_service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _paths = workspace_service
    deployment = tmp_path / "mounted-workspace"
    deployment.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(deployment))

    binding = service.current_binding(ensure_output=True)

    assert binding.root == deployment.resolve()
    assert binding.locked is True
    with pytest.raises(WorkspaceError, match="locks"):
        service.set_workspace(tmp_path)


def test_workspace_id_cannot_be_reused_by_another_user(workspace_service) -> None:
    service, paths = workspace_service
    shared = paths.get_workspace_dir() / "shared"
    shared.mkdir(parents=True)
    admin_binding = service.set_workspace(shared)
    user = CurrentUser(
        id="user-two",
        username="two",
        role="user",
        scope=UserScope(kind="user", user_id="user-two", root=paths.workspace_root),
    )

    token = set_current_user(user)
    try:
        with pytest.raises(WorkspaceError, match="no longer registered"):
            service.binding_by_id(admin_binding.workspace_id)
    finally:
        reset_current_user(token)


def test_execution_environment_keeps_mutable_tool_state_in_the_turn(
    tmp_path: Path,
) -> None:
    turn_dir = tmp_path / "outputs" / "chat" / "session" / "turn"
    workspace_root = tmp_path / "workspace"

    exec_env = prepare_workspace_execution_env(turn_dir, workspace_root=workspace_root)
    code_env = prepare_workspace_execution_env(turn_dir, workspace_root=workspace_root)

    internal = (turn_dir / ".deeptutor" / "execution").resolve()
    for key in (
        "HOME",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "PIP_CACHE_DIR",
        "PIP_TARGET",
        "PYTHONUSERBASE",
        "npm_config_cache",
        "npm_config_prefix",
        "CARGO_HOME",
        "GOPATH",
        "HF_HOME",
        "TORCH_HOME",
        "MPLCONFIGDIR",
    ):
        Path(exec_env[key]).resolve().relative_to(internal)
        assert exec_env[key] == code_env[key]
    assert exec_env["PYTHONPATH"] == exec_env["PIP_TARGET"]
    assert exec_env["DEEPTUTOR_WORKSPACE_ROOT"] == str(workspace_root.resolve())


def test_execution_environment_rejects_hidden_state_symlink(
    tmp_path: Path,
) -> None:
    turn_dir = tmp_path / "outputs" / "chat" / "session" / "turn"
    turn_dir.mkdir(parents=True)
    outside = tmp_path / "outside-execution"
    outside.mkdir()
    try:
        (turn_dir / ".deeptutor").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(ValueError, match="cannot contain symbolic links"):
        prepare_workspace_execution_env(turn_dir)
    assert not any(outside.iterdir())


def test_execution_results_expose_only_workspace_relative_paths(tmp_path: Path) -> None:
    root = (tmp_path / "workspace").resolve()
    run_dir = root / "outputs" / "chat" / "turn" / "code_runs" / "python_1"
    physical = str(run_dir / "main.py")

    rendered = logicalize_workspace_text(f'File "{physical}"', root)

    assert str(root) not in rendered
    assert "outputs/chat/turn/code_runs/python_1/main.py" in rendered
    assert logical_workspace_path(run_dir, root) == ("outputs/chat/turn/code_runs/python_1")
