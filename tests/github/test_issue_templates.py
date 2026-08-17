from __future__ import annotations

import json
from pathlib import Path

import yaml

ISSUE_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE"
PULL_REQUEST_TEMPLATE = Path(__file__).resolve().parents[2] / ".github" / "pull_request_template.md"


def _load(name: str) -> dict:
    return yaml.safe_load((ISSUE_TEMPLATE_DIR / name).read_text(encoding="utf-8"))


def _fields(template: dict) -> list[dict]:
    return [entry for entry in template["body"] if entry.get("type") != "markdown"]


def test_issue_templates_have_unique_required_field_ids() -> None:
    for path in sorted(ISSUE_TEMPLATE_DIR.glob("*.yml")):
        if path.name == "config.yml":
            continue
        template = yaml.safe_load(path.read_text(encoding="utf-8"))
        fields = _fields(template)
        ids = [field.get("id") for field in fields]
        assert all(ids), f"{path.name} has a field without an id"
        assert len(ids) == len(set(ids)), f"{path.name} has duplicate field ids"


def test_core_triage_fields_are_required() -> None:
    required = {
        "bug_report.yml": {"description", "reproduce", "expected_behavior", "module"},
        "feature_request.yml": {"feature_request_description", "use_case", "module"},
        "question.yml": {"question", "module"},
    }
    for name, expected in required.items():
        fields = {field["id"]: field for field in _fields(_load(name))}
        for field_id in expected:
            assert fields[field_id].get("validations", {}).get("required") is True


def test_all_issue_templates_require_duplicate_checks() -> None:
    for path in sorted(ISSUE_TEMPLATE_DIR.glob("*.yml")):
        if path.name == "config.yml":
            continue
        fields = {field["id"]: field for field in _fields(_load(path.name))}
        assert fields["existingcheck"].get("validations", {}).get("required") is True


def test_docs_template_collects_actionable_resolution_context() -> None:
    fields = {field["id"]: field for field in _fields(_load("docs.yml"))}

    for field_id in ("page", "kind", "problem", "expected", "environment"):
        assert fields[field_id].get("validations", {}).get("required") is True


def test_eduhub_template_requires_reproduction_context_and_warns_about_secrets() -> None:
    template = _load("eduhub.yml")
    fields = {field["id"]: field for field in _fields(template)}

    for field_id in ("existingcheck", "area", "description", "environment"):
        assert fields[field_id].get("validations", {}).get("required") is True
    rendered = json.dumps(template)
    assert "Redact API keys, tokens, private URLs" in rendered


def test_product_area_options_cover_current_surfaces() -> None:
    expected = {
        "Dashboard",
        "Chat",
        "Knowledge Base Management",
        "Smart Solver",
        "Question Generator",
        "Deep Research",
        "Visualize",
        "Math Animator",
        "Co-Writer",
        "Notebook",
        "Guided Learning",
        "Idea Generation",
        "Memory",
        "Partners",
        "Tools / Skills",
        "Provider Integrations",
        "CLI",
        "API/Backend",
        "Frontend/Web",
        "Installation/Setup",
    }
    for name in ("bug_report.yml", "feature_request.yml", "question.yml"):
        fields = {field["id"]: field for field in _fields(_load(name))}
        area_options = set(fields["module"]["attributes"]["options"])
        terminal_option = "General" if name == "question.yml" else "Other"
        assert area_options == expected | {terminal_option}


def test_bug_template_warns_against_secrets() -> None:
    template = json.dumps(_load("bug_report.yml"))
    assert "Redact API keys, tokens, private URLs" in template


def test_pull_request_template_requires_verification_and_current_product_areas() -> None:
    template = PULL_REQUEST_TEMPLATE.read_text(encoding="utf-8")

    for heading in (
        "### Summary",
        "### Product Area(s)",
        "### Verification",
        "### Compatibility / Migration",
    ):
        assert heading in template
    for area in (
        "Visualize / Math Animator",
        "Co-Writer / Book",
        "Learning Space / Memory",
        "Partners / My Agents",
        "Provider Integrations",
    ):
        assert area in template
    assert "`agents`" not in template
    assert "`services`" not in template
    assert "PASS / FAIL / BLOCKED" in template
    assert "security, privacy, and secret-leakage" in template
