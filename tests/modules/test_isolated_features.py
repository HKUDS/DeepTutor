"""Run independent feature paths with unrelated module imports prohibited.

A full developer environment hides missing wheel dependencies. Each subprocess
has a fresh import table and fails even when the excluded source files exist.
"""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = """
import asyncio, importlib.abc, importlib.machinery, sys
from pathlib import Path
from deeptutor.modules import catalog
allowed = set(catalog.dependency_order([FEATURE])) | {"core"}
catalog.installed = lambda name: name in allowed
catalog.selection = lambda: {}
root = Path.cwd()
class Isolate(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(("deeptutor.", "deeptutor_cli.")):
            return
        relative = fullname.replace(".", "/")
        candidate = relative + ".py"
        if not (root / candidate).is_file():
            candidate = relative + "/__init__.py"
        owner = catalog.module_for_path(candidate)
        if owner in allowed:
            return
        if any(prefix.startswith(relative + "/") for name in allowed
               for prefix in catalog.manifests()[name]["paths"]):
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [str(root / relative)]
            return spec
        raise ModuleNotFoundError(f"Undeclared dependency: {FEATURE} -> {owner}: {fullname}")
sys.meta_path.insert(0, Isolate())
from deeptutor.services.setup import init_user_directories
init_user_directories()
"""
ASSEMBLY = """
from importlib import import_module
for owner in sorted(allowed):
    row = catalog.manifests()[owner]
    for kind in ("capabilities", "loops", "tools"):
        for name, spec in row[kind].items():
            if catalog.contribution_enabled(kind, name):
                module, attribute = spec["class_path"].split(":")
                assert getattr(import_module(module), attribute)() is not None
    for service in row["services"]:
        for action in ("start", "stop"):
            module, attribute = service[action].split(":")
            assert callable(getattr(import_module(module), attribute))
    for command in row["commands"]:
        module, attribute = command["register"].split(":")
        assert callable(getattr(import_module(module), attribute))
"""
CASES = {
    "core": """
from deeptutor.services.suggestions import _collect_material
assert not _collect_material(5)
from deeptutor.services.doctor import run_diagnostics
report = asyncio.run(run_diagnostics())
assert next(row for row in report.checks if row.key == "rag").status == "skip"
from deeptutor.runtime.registry.tool_registry import ToolRegistry
registry = ToolRegistry(); registry.load_builtins()
assert registry.get("paper_search") is None
assert registry.get("partner_read") is None
assert registry.get("web_search") is not None
""",
    "parsing": """
from deeptutor.services.parsing import get_parse_service
from deeptutor.runtime.home import get_runtime_home
source = get_runtime_home() / "lesson.txt"
source.write_text("Independent parsing still works.")
service = get_parse_service()
first = service.parse(source, engine="text_only")
second = service.parse(source, engine="text_only")
assert "Independent parsing" in first.markdown
assert first.markdown == second.markdown
""",
    "research": """
from deeptutor.agents.research.pipeline import ResearchPipeline
from deeptutor.tools.research_tools import _client
assert _client() is not None
pipeline = ResearchPipeline.__new__(ResearchPipeline)
pipeline.kb_name = None
asyncio.run(pipeline._prepare_pageindex_tools())
assert pipeline._pageindex_tool_context is None
from deeptutor.runtime.registry.tool_registry import ToolRegistry
registry = ToolRegistry(); registry.load_builtins()
assert registry.get("paper_search") is not None
assert registry.get("knowledge_frontier") is None
""",
    "questions": """
from deeptutor.agents.question.pipeline import QuestionPipeline
pipeline = QuestionPipeline.__new__(QuestionPipeline)
pipeline.kb_name = None
asyncio.run(pipeline._prepare_pageindex_tools())
assert pipeline._pageindex_tool_context is None
""",
    "calendar": """
from datetime import datetime, timezone, timedelta
from deeptutor.services.calendar import layers
from deeptutor.services.cron import service
from types import SimpleNamespace
service.get_cron_service = lambda: SimpleNamespace(list_jobs=lambda owner: [])
layers.owner_key = lambda: "fixture"
start = datetime.now(timezone.utc)
result = layers.read_layers("fixture", start, start + timedelta(days=7), "UTC")
assert not result.automations
assert not result.reviews
""",
    "server": """
from fastapi.testclient import TestClient
from deeptutor.api.main import app
with TestClient(app) as client:
    for path in ("/", "/api/modules", "/api/sessions", "/api/settings/readiness", "/api/dashboard/learning-index"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text)
    assert client.get("/api/settings/document-parsing").status_code == 404
""",
}


@pytest.mark.parametrize(
    "feature", sorted(path.stem for path in (ROOT / "deeptutor/modules/manifests").glob("*.json"))
)
def test_feature_without_unrelated_modules(feature, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"FEATURE = {feature!r}\n"
            + BOOTSTRAP
            + ASSEMBLY
            + textwrap.dedent(CASES.get(feature, "")),
        ],
        cwd=ROOT,
        env={**os.environ, "DEEPTUTOR_HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
