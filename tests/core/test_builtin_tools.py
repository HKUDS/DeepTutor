"""Tests for built-in tools and unified tool registry behavior."""

from __future__ import annotations

from pathlib import Path
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.services.path_service import PathService
from deeptutor.services.sandbox.spec import ExecResult
from deeptutor.tools.builtin import (
    BrainstormTool,
    ExecTool,
    GeoGebraAnalysisTool,
    PaperSearchToolWrapper,
    RAGTool,
    ReasonTool,
    WebSearchTool,
)


def _install_module(
    monkeypatch: pytest.MonkeyPatch, fullname: str, **attrs: Any
) -> types.ModuleType:
    """Install a fake module (and missing parent packages) into sys.modules."""
    parts = fullname.split(".")
    for idx in range(1, len(parts)):
        pkg_name = ".".join(parts[:idx])
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, pkg_name, pkg)
            if idx > 1:
                parent = sys.modules[".".join(parts[: idx - 1])]
                # Use monkeypatch (not raw setattr) so the parent package's
                # attribute is restored on teardown — otherwise a real
                # submodule the parent exposes (e.g. ``llm.config``) stays
                # shadowed by the fake and leaks into later tests.
                monkeypatch.setattr(parent, parts[idx - 1], pkg, raising=False)

    module = types.ModuleType(fullname)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, fullname, module)
    if len(parts) > 1:
        parent = sys.modules[".".join(parts[:-1])]
        monkeypatch.setattr(parent, parts[-1], module, raising=False)
    return module


@pytest.mark.asyncio
async def test_exec_tool_reports_generated_public_artifacts(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_service = PathService(workspace_root=tmp_path / "data")
    workdir = path_service.get_task_workspace("chat", "turn_1") / "exec"

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            assert user_id == "user-1"
            assert request.command == "python build_pdf.py"
            output_dir = PathService(workspace_root=tmp_path / "data").get_task_workspace(
                "chat", "turn_1"
            )
            assert request.workdir == str(output_dir / "exec")
            work = output_dir / "exec"
            work.mkdir(parents=True, exist_ok=True)
            (work / "report.pdf").write_bytes(b"%PDF-1.4\n")
            (work / "build_pdf.py").write_text("print('internal')", encoding="utf-8")
            return ExecResult(stdout="created report.pdf\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        code="python build_pdf.py",
        language="shell",
        _sandbox_user_id="user-1",
        _sandbox_workdir=str(workdir),
    )

    assert result.success is True
    assert "Generated artifacts" in result.content
    assert "report.pdf" in result.content
    # The model is told to mention the exact filename (the UI linkifies it); the
    # raw download URL is delivered out-of-band (sources/metadata), never in the
    # model-facing text, so the model can't paste it.
    assert "already presented" in result.content
    assert "/files/outputs/" not in result.content
    assert "build_pdf.py" not in result.content
    assert result.metadata["artifacts"][0]["filename"] == "report.pdf"
    assert (
        result.metadata["artifacts"][0]["url"]
        == "/files/outputs/workspace/chat/chat/turn_1/exec/report.pdf"
    )
    assert result.sources[0]["url"].endswith("/report.pdf")


@pytest.mark.asyncio
async def test_exec_tool_reports_missing_artifacts_after_success(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_service = PathService(workspace_root=tmp_path / "data")
    workdir = path_service.get_task_workspace("chat", "turn_1") / "exec"
    workdir.mkdir(parents=True, exist_ok=True)

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            return ExecResult(stdout="done\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        code="python build_pdf.py",
        language="shell",
        _sandbox_user_id="user-1",
        _sandbox_workdir=str(workdir),
    )

    assert result.success is True
    assert "No new or changed artifacts were produced by this call." in result.content
    assert result.metadata["artifacts"] == []


@pytest.mark.asyncio
async def test_exec_tool_runs_python_source_by_default(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_service = PathService(workspace_root=tmp_path / "data")
    code_workdir = path_service.get_task_workspace("chat", "turn_1") / "code_runs"
    captured: dict[str, Any] = {}

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            captured["request"] = request
            run_dir = Path(request.workdir)
            assert run_dir == code_workdir
            source = next(run_dir.glob(".deeptutor/exec_calls/python_*/main.py"))
            assert source.read_text(encoding="utf-8") == "print(2 + 2)"
            return ExecResult(stdout="4\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        code="print(2 + 2)",
        _sandbox_user_id="user-1",
        _sandbox_code_workdir=str(code_workdir),
        _sandbox_env={"PIP_TARGET": "/shared/python-packages"},
    )

    assert result.success is True
    assert result.metadata["language"] == "python"
    assert captured["request"].command.startswith("python3 .deeptutor/exec_calls/python_")
    assert captured["request"].command.endswith("/main.py")
    assert captured["request"].env["PIP_TARGET"] == "/shared/python-packages"


@pytest.mark.asyncio
async def test_exec_tool_creates_a_pdf_with_the_real_python_runtime(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.sandbox.backends import RestrictedSubprocessBackend
    from deeptutor.services.workspace.execution import prepare_workspace_execution_env

    path_service = PathService(workspace_root=tmp_path / "data")
    turn_dir = path_service.get_task_workspace("chat", "turn_pdf")
    code_workdir = turn_dir / "code_runs"
    backend = RestrictedSubprocessBackend()

    class DirectSandboxService:
        async def run(self, request, *, user_id: str):
            return await backend.exec(request)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: DirectSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        code=(
            "from reportlab.pdfgen import canvas\n"
            "pdf = canvas.Canvas('deeptutor_intro.pdf')\n"
            "pdf.drawString(72, 760, 'DeepTutor')\n"
            "pdf.save()\n"
            "print('created deeptutor_intro.pdf')\n"
        ),
        _sandbox_code_workdir=str(code_workdir),
        _sandbox_env=prepare_workspace_execution_env(turn_dir),
    )

    pdf_path = code_workdir / "deeptutor_intro.pdf"
    assert result.success is True
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert [row["filename"] for row in result.metadata["artifacts"]] == ["deeptutor_intro.pdf"]


@pytest.mark.asyncio
async def test_exec_tool_hides_physical_workspace_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_service = PathService(workspace_root=tmp_path / "data")
    workspace_root = path_service.workspace_root.resolve()
    workdir = workspace_root / "outputs" / "chat" / "session" / "turn" / "exec"
    workdir.mkdir(parents=True)

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            return ExecResult(
                stderr=f'Traceback: File "{workspace_root}/outputs/chat/job.py"\n',
                exit_code=1,
                error=f"failed below {workspace_root}/outputs/chat/job.py",
            )

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        code="exit 1",
        language="shell",
        _sandbox_workdir=str(workdir),
        _workspace_root=str(workspace_root),
    )

    assert str(workspace_root) not in result.content
    assert "outputs/chat/job.py" in result.content
    assert str(workspace_root) not in result.metadata["sandbox_error"]


@pytest.mark.asyncio
async def test_brainstorm_tool_passes_llm_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_brainstorm(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "## 1. Test idea\n- Rationale: worth exploring"}

    _install_module(monkeypatch, "deeptutor.tools.brainstorm", brainstorm=fake_brainstorm)

    result = await BrainstormTool().execute(
        topic="agent-native tutoring",
        context="Focus on fast ideation",
        model="gpt-test",
    )

    assert "Test idea" in result.content
    assert captured["topic"] == "agent-native tutoring"
    assert captured["context"] == "Focus on fast ideation"
    assert captured["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_rag_tool_forwards_query_and_extra_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_rag_search(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "grounded answer", "provider": "fake"}

    _install_module(monkeypatch, "deeptutor.tools.rag_tool", rag_search=fake_rag_search)

    result = await RAGTool().execute(
        query="what is a tensor",
        kb_name="demo-kb",
        mode="hybrid",
        only_need_context=True,
    )

    assert result.content == "grounded answer"
    assert captured["query"] == "what is a tensor"
    assert captured["kb_name"] == "demo-kb"
    assert captured["mode"] == "hybrid"
    assert captured["only_need_context"] is True


@pytest.mark.asyncio
async def test_rag_tool_cites_retrieved_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retrieval's own provenance must reach the citation stream — echoing
    the query back was all a grounded answer used to carry (issue #694)."""

    async def fake_rag_search(**_kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "grounded answer",
            "sources": [
                {"title": "Chapter 3", "chunk_id": "chunk-7", "content": "…tensors…"},
                {"title": "tensor", "chunk_id": "entity-2", "content": "…rank…"},
            ],
        }

    _install_module(monkeypatch, "deeptutor.tools.rag_tool", rag_search=fake_rag_search)

    result = await RAGTool().execute(query="what is a tensor", kb_name="demo-kb")

    assert [s["chunk_id"] for s in result.sources] == ["chunk-7", "entity-2"]
    assert [s["title"] for s in result.sources] == ["Chapter 3", "tensor"]
    assert all(s["type"] == "rag" and s["kb_name"] == "demo-kb" for s in result.sources)


@pytest.mark.asyncio
async def test_rag_tool_falls_back_to_query_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    """An engine that surfaces no provenance still names the KB it consulted."""

    async def fake_rag_search(**_kwargs: Any) -> dict[str, Any]:
        return {"answer": "grounded answer", "sources": []}

    _install_module(monkeypatch, "deeptutor.tools.rag_tool", rag_search=fake_rag_search)

    result = await RAGTool().execute(query="what is a tensor", kb_name="demo-kb")

    assert result.sources == [{"type": "rag", "query": "what is a tensor", "kb_name": "demo-kb"}]


@pytest.mark.asyncio
async def test_rag_tool_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_rag_search(**_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"answer": "should not run"}

    _install_module(monkeypatch, "deeptutor.tools.rag_tool", rag_search=fake_rag_search)

    with pytest.raises(ValueError, match="RAG query must be a non-empty string"):
        await RAGTool().execute(query="  ", kb_name="demo-kb")

    assert called is False


@pytest.mark.asyncio
async def test_web_search_tool_wraps_sync_function(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_web_search(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "answer": "web summary",
            "citations": [{"url": "https://example.com", "title": "Example"}],
        }

    _install_module(monkeypatch, "deeptutor.tools.web_search", web_search=fake_web_search)

    result = await WebSearchTool().execute(query="latest benchmark", output_dir="/tmp/out")

    assert result.content == "web summary"
    assert captured["query"] == "latest benchmark"
    assert captured["output_dir"] == "/tmp/out"
    assert result.sources[0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_exec_tool_runs_python_via_sandbox(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    path_service = PathService(workspace_root=tmp_path / "data")
    workdir = path_service.get_task_workspace("chat", "turn_1") / "code_runs"

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            assert user_id == "user-1"
            assert request.command.startswith("python3 .deeptutor/exec_calls/python_")
            run_dir = Path(request.workdir)
            assert run_dir == workdir
            source = next(run_dir.glob(".deeptutor/exec_calls/python_*/main.py"))
            assert source.read_text(encoding="utf-8") == "print(2 + 2)"
            (run_dir / "result.txt").write_text("ok", encoding="utf-8")
            return ExecResult(stdout="4\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        language="python",
        code="print(2 + 2)",
        _sandbox_user_id="user-1",
        _sandbox_code_workdir=str(workdir),
    )

    assert result.success is True
    assert "4" in result.content
    assert result.metadata["language"] == "python"
    assert result.metadata["command"].startswith("python3 .deeptutor/exec_calls/python_")
    # The program-generated file surfaces; the source file we wrote is filtered.
    artifact_names = [row["filename"] for row in result.metadata["artifacts"]]
    assert "result.txt" in artifact_names
    assert "main.py" not in artifact_names


@pytest.mark.asyncio
async def test_exec_tool_warns_when_no_artifacts_are_generated(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_service = PathService(workspace_root=tmp_path / "data")
    workdir = path_service.get_task_workspace("chat", "turn_1") / "code_runs"

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            return ExecResult(stdout="PDF created\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        language="python",
        code="print('PDF created')",
        _sandbox_user_id="user-1",
        _sandbox_code_workdir=str(workdir),
    )

    assert result.success is True
    assert "No new or changed artifacts were produced by this call." in result.content
    assert result.metadata["artifacts"] == []
    assert result.sources == []


@pytest.mark.asyncio
async def test_exec_tool_compiles_cpp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    path_service = PathService(workspace_root=tmp_path / "data")
    workdir = path_service.get_task_workspace("chat", "turn_1") / "code_runs"
    captured: dict[str, Any] = {}

    class FakeSandboxService:
        async def run(self, request, *, user_id: str):
            captured["command"] = request.command
            run_dir = Path(request.workdir)
            assert run_dir == workdir
            assert next(run_dir.glob(".deeptutor/exec_calls/cpp_*/main.cpp")).exists()
            return ExecResult(stdout="hi\n", exit_code=0)

    import deeptutor.services.sandbox as sandbox_pkg
    import deeptutor.services.sandbox.artifacts as sandbox_artifacts

    monkeypatch.setattr(sandbox_pkg, "get_sandbox_service", lambda: FakeSandboxService())
    monkeypatch.setattr(sandbox_artifacts, "get_path_service", lambda: path_service)

    result = await ExecTool().execute(
        language="cpp",
        code="int main(){}",
        _sandbox_code_workdir=str(workdir),
    )

    assert result.success is True
    assert captured["command"].startswith("c++ -std=c++17 .deeptutor/exec_calls/cpp_")
    assert " -O2 -o .deeptutor/exec_calls/cpp_" in captured["command"]


def test_exec_tool_uses_windows_shell_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.tools.exec_tool as exec_module

    monkeypatch.setattr(exec_module.sys, "platform", "win32")

    assert ExecTool._command_for_platform("python", has_stdin=False) == "python main.py"
    assert (
        ExecTool._command_for_platform("cpp", has_stdin=True)
        == "$stdinText = Get-Content -Raw stdin.txt; g++ -std=c++17 -O2 main.cpp -o prog.exe; if ($LASTEXITCODE -eq 0) { $stdinText | & .\\prog.exe }"
    )
    command = ExecTool._command_for_platform(
        "python",
        has_stdin=True,
        call_dir="C:/Deep Tutor/runtime/exec_calls/python_1",
    )
    assert command == (
        "Get-Content 'C:\\Deep Tutor\\runtime\\exec_calls\\python_1\\stdin.txt' | "
        "python 'C:\\Deep Tutor\\runtime\\exec_calls\\python_1\\main.py'"
    )


@pytest.mark.asyncio
async def test_exec_tool_rejects_bad_input() -> None:
    tool = ExecTool()
    with pytest.raises(ValueError, match="Unsupported exec language"):
        await tool.execute(language="ruby", code="puts 1")
    with pytest.raises(ValueError, match="non-empty 'code'"):
        await tool.execute(language="python", code="   ")


@pytest.mark.asyncio
async def test_reason_tool_passes_llm_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_reason(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "reasoned"}

    _install_module(monkeypatch, "deeptutor.tools.reason", reason=fake_reason)

    result = await ReasonTool().execute(
        query="derive the formula",
        context="prior work",
        api_key="key",
        base_url="url",
        model="gpt-test",
    )

    assert result.content == "reasoned"
    assert captured["model"] == "gpt-test"
    assert captured["context"] == "prior work"


@pytest.mark.asyncio
async def test_paper_search_tool_formats_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeArxivSearchTool:
        async def search_papers(self, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs["query"] == "graph learning"
            return [
                {
                    "title": "Graph Learning 101",
                    "year": 2024,
                    "authors": ["Ada", "Grace"],
                    "arxiv_id": "1234.5678",
                    "url": "https://arxiv.org/abs/1234.5678",
                    "abstract": "A compact abstract.",
                }
            ]

    _install_module(
        monkeypatch,
        "deeptutor.tools.paper_search_tool",
        ArxivSearchTool=FakeArxivSearchTool,
    )

    result = await PaperSearchToolWrapper().execute(query="graph learning")

    assert "Graph Learning 101" in result.content
    assert result.sources[0]["provider"] == "arxiv"


@pytest.mark.asyncio
async def test_geogebra_analysis_tool_handles_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeVisionSolverAgent:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def process(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["question_text"] == "analyze this"
            return {
                "has_image": True,
                "final_ggb_commands": ["A=(0,0)", "B=(1,0)"],
                "analysis_output": {
                    "constraints": ["AB = 1"],
                    "geometric_relations": [{"description": "A and B are on x-axis"}],
                },
                "image_is_reference": False,
            }

        def format_ggb_block(self, commands: list[str]) -> str:
            return "\n".join(commands)

    _install_module(
        monkeypatch,
        "deeptutor.agents.vision_solver.vision_solver_agent",
        VisionSolverAgent=FakeVisionSolverAgent,
    )
    _install_module(
        monkeypatch,
        "deeptutor.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u"),
    )

    result = await GeoGebraAnalysisTool().execute(
        question="analyze this",
        image_base64="ZmFrZQ==",
        language="en",
    )

    assert result.success is True
    assert "A=(0,0)" in result.content
    assert result.metadata["commands_count"] == 2


@pytest.mark.asyncio
async def test_tool_registry_exposes_no_legacy_execution_aliases() -> None:
    class DummyTool(BaseTool):
        def __init__(self, tool_name: str) -> None:
            self._tool_name = tool_name
            self.calls: list[dict[str, Any]] = []

        def get_definition(self) -> ToolDefinition:
            param_name = {
                "rag": "query",
                "exec": "code",
            }[self._tool_name]
            return ToolDefinition(
                name=self._tool_name,
                description="dummy",
                parameters=[ToolParameter(name=param_name, type="string")],
            )

        async def execute(self, **kwargs: Any) -> ToolResult:
            self.calls.append(kwargs)
            return ToolResult(content=self._tool_name)

    rag = DummyTool("rag")
    code = DummyTool("exec")

    registry = ToolRegistry()
    registry.register(rag)
    registry.register(code)

    rag_result = await registry.execute("rag_hybrid", query="find this")
    code_result = await registry.execute("exec", language="python", code="print(1)")

    assert rag_result.content == "rag"
    assert rag.calls[0]["mode"] == "hybrid"
    assert rag.calls[0]["query"] == "find this"
    assert code_result.content == "exec"
    assert code.calls[0]["code"] == "print(1)"
    assert code.calls[0]["language"] == "python"
    for removed_name in ("code_execution", "run_code", "code_execute"):
        assert registry.get(removed_name) is None
        with pytest.raises(KeyError, match="Unknown tool"):
            await registry.execute(removed_name, code="print(2)")
