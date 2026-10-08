"""Scientific workflows: actual paper pixels, pinned code and abstention."""

import json
from pathlib import Path

import fitz
import httpx
import pytest

import deeptutor.services.research.primitives as primitives
from deeptutor.services.research.primitives import (
    ResearchClient,
    ResearchError,
    arxiv_id,
    audit_checks,
    literature,
    read_pdf,
)
from deeptutor.tools.research_tools import PreprintTool, ResearchAuditTool


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_feed_rejects_entity_declarations_in_supported_xml_encodings(encoding):
    raw = (
        '<!DOCTYPE feed [<!ENTITY injected "untrusted">]>'
        '<feed xmlns="http://www.w3.org/2005/Atom">&injected;</feed>'
    ).encode(encoding)
    with pytest.raises(ResearchError):
        primitives.parse_feed(raw)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(primitives, "ARXIV_INTERVAL", 0)
    monkeypatch.setattr(primitives, "_NEXT_API", 0)

    async def allowed(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(primitives, "validate_mcp_url_async", allowed)
    document = fitz.open()
    for number in range(3):
        page = document.new_page()
        page.insert_text(
            (40, 40), f"Page {number + 1}: dropout = 0.1. Figure {number + 1}: source diagram."
        )
        page.draw_rect(fitz.Rect(40, 70, 180, 120), color=(0, 0, 1))
    pdf = document.tobytes()
    document.close()
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v3</id><title>Known paper</title><summary>Primary author abstract.</summary><author><name>Known Author</name></author><published>2017-06-12</published><updated>2017-06-13</updated></entry></feed>"""
    sha = "a" * 40
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, content=feed)
        if request.url.host == "arxiv.org":
            return httpx.Response(200, content=pdf)
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": sha})
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200, json={"tree": [{"type": "blob", "mode": "100644", "path": "model.py"}]}
            )
        if "/contents/" in request.url.path:
            return httpx.Response(200, content=b"dropout = 0.2\n# Static source only\n")
        return httpx.Response(404)

    client = ResearchClient(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        cache_root=tmp_path,
    )
    monkeypatch.setattr("deeptutor.tools.research_tools._client", lambda: client)
    return client, requests, pdf


@pytest.mark.asyncio
async def test_audit_compares_real_quotes_against_pinned_code_and_never_claims_reproduction(
    sources,
):
    result = await ResearchAuditTool().execute(
        paper="1706.03762v3",
        repository="https://github.com/owner/repo",
        files=["model.py"],
        checks=[
            {
                "claim": "dropout default",
                "paper_quote": "dropout = 0.1",
                "file": "model.py",
                "code_quote": "dropout = 0.2",
                "expected": "0.1",
                "implemented": "0.2",
            },
            {
                "claim": "invented value",
                "paper_quote": "dropout = 0.9",
                "file": "model.py",
                "code_quote": "dropout = 0.2",
                "expected": "0.9",
                "implemented": "0.2",
            },
        ],
    )
    assert result.success
    data = json.loads(result.content)
    assert data["implementation"]["commit"] == "a" * 40
    assert data["implementation"]["execution"] == "not_run"
    assert data["checks"][0]["status"] == "candidate_discrepancy"
    assert data["checks"][1]["status"] == "unverified"
    assert any("ref=" + "a" * 40 in request for request in sources[1])


@pytest.mark.asyncio
async def test_figures_attach_actual_selected_pages_only_to_private_model_context(sources):
    result = await PreprintTool().execute(
        paper="1706.03762", action="figures", pages=[2, 3], _vision_supported=True
    )
    assert result.success
    data = json.loads(result.content)
    assert data["arxiv_id"] == "1706.03762v3"
    assert data["rendered_pages"] == [2, 3]
    assert result.model_message["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert "base64" not in result.content and "base64" not in json.dumps(result.metadata)
    assert data["source_page_links"][0]["url"].endswith("1706.03762v3#page=2")
    without_vision = await PreprintTool().execute(paper="1706.03762", action="figures", pages=[2])
    assert without_vision.model_message is None
    assert "do not claim" in json.loads(without_vision.content)["visual_inspection"]


@pytest.mark.asyncio
async def test_recursive_literature_deduplicates_and_leaves_abstract_consensus_unverified(sources):
    result = await literature(sources[0], "attention", ["attention counterexample"])
    assert len(result["searches"]) == 2
    assert len(result["papers"]) == 1
    assert result["comparative_matrix"][0]["agreement"] == "requires_full_text_comparison"
    assert result["comparative_matrix"][0]["contention"] == "requires_full_text_comparison"


@pytest.mark.parametrize(
    "value",
    [
        "https://arxiv.org.evil.test/abs/1706.03762",
        "https://arxiv.org/abs/1706.03762?token=secret",
        "../../paper.pdf",
        "https://127.0.0.1/abs/1706.03762",
    ],
)
def test_preprint_identifiers_reject_noncanonical_targets(value):
    with pytest.raises(ResearchError):
        arxiv_id(value)


def test_version_and_legacy_archive_identity_is_preserved():
    assert arxiv_id("https://arxiv.org/pdf/hep-th/9901001v2.pdf") == "hep-th/9901001v2"


@pytest.mark.asyncio
async def test_http_failures_are_not_reported_as_no_papers(monkeypatch):
    async def allowed(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(primitives, "validate_mcp_url_async", allowed)
    client = ResearchClient(
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429))
        )
    )
    with pytest.raises(ResearchError, match="HTTP 429"):
        await client.fetch("https://export.arxiv.org/api/query", limit=100)


@pytest.mark.asyncio
async def test_redirect_cannot_expand_primary_host_scope(monkeypatch):
    async def allowed(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(primitives, "validate_mcp_url_async", allowed)
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/metadata"})

    client = ResearchClient(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ResearchError, match="primary-source hosts"):
        await client.fetch("https://arxiv.org/pdf/1706.03762", limit=100)
    assert len(calls) == 1


def test_pdf_page_budget_rejects_invalid_or_huge_selections(sources):
    with pytest.raises(ResearchError):
        read_pdf(sources[2], [0], True)
    with pytest.raises(ResearchError):
        read_pdf(sources[2], [1] * 21, True)


def test_numeric_comparison_preserves_semantic_uncertainty():
    paper = {"pages": [{"page": 1, "text": "weight 0.1"}]}
    code = {
        "files": [
            {
                "path": "a.py",
                "status": "read",
                "text": "weight = 1e-1",
                "url": "https://example.test/a",
            }
        ]
    }
    row = audit_checks(
        paper,
        code,
        [
            {
                "paper_quote": "weight 0.1",
                "file": "a.py",
                "code_quote": "weight = 1e-1",
                "expected": "0.1",
                "implemented": "1e-1",
            }
        ],
    )[0]
    assert row["status"] == "values_match"
    assert "units" in row["interpretation"]


def test_figure_discovery_prefers_caption_pages_and_blank_text_stays_unknown():
    document = fitz.open()
    document.new_page().insert_text((40, 40), "Introduction without a figure.")
    document.new_page().insert_text((40, 40), "Figure 1: original vector diagram.")
    document.new_page()
    data, images = read_pdf(document.tobytes(), None, True)
    assert data["rendered_pages"] == [2]
    assert len(images) == 1
    blank, _ = read_pdf(document.tobytes(), [3], False)
    assert blank["text_status"] == "no_extractable_text" and blank["partial"]
    document.close()


def test_damaged_pdf_cannot_be_reported_as_primary_page_evidence():
    with pytest.raises(ResearchError, match="unreadable"):
        read_pdf(b"%PDF-1.7 damaged", [1], False)


@pytest.mark.asyncio
async def test_github_credential_is_never_sent_to_a_paper_host_or_redirect(monkeypatch):
    async def allowed(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(primitives, "validate_mcp_url_async", allowed)
    captured = []

    def handler(request):
        captured.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"location": "https://arxiv.org/abs/1706.03762"})
        return httpx.Response(200, content=b"public source")

    client = ResearchClient(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        github_token="private-test-token",
    )
    await client.fetch("https://api.github.com/repos/owner/repo", limit=100)
    assert captured == [("api.github.com", "Bearer private-test-token"), ("arxiv.org", None)]


def test_other_accounts_do_not_borrow_deployment_github_credentials(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from deeptutor.tools.research_tools import _client

    monkeypatch.setattr(
        "deeptutor.tools.research_tools.get_path_service",
        lambda: SimpleNamespace(get_parse_cache_root=lambda: tmp_path),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "deployment-private-token")
    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user_or_none",
        lambda: SimpleNamespace(role="user"),
    )
    assert _client().github_token is None
    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user_or_none",
        lambda: SimpleNamespace(role="admin"),
    )
    assert _client().github_token == "deployment-private-token"
