"""Real lightweight CLI children against a published-schema synthetic bundle."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys

from pip._vendor.distlib.scripts import ScriptMaker
import pytest

from deeptutor.services.parsing.cache import load_ir
from deeptutor.services.parsing.engines.mineru import local

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/mineru4-contract"
FAKE_CLI = r"""
import copy,json,os,pathlib,sys,time,zipfile
def main():
    args=sys.argv[1:]
    mode=os.environ.get('MINERU_FIXTURE_MODE','success')
    version=os.environ.get('MINERU_FIXTURE_VERSION','4.1.3')
    if '--version' in args:
        if mode=='version_timeout': time.sleep(10)
        print('MinerU, version '+version,flush=True)
        return
    if mode=='fail':
        print('synthetic CLI failure',flush=True)
        raise SystemExit(7)
    if mode=='sleep': time.sleep(10)
    if mode=='empty': return
    output=pathlib.Path(args[args.index('-o')+1])
    if version.startswith('3.'):
        output.mkdir(parents=True,exist_ok=True)
        (output/'legacy.md').write_text('# Legacy document',encoding='utf-8')
        return
    assert args[0]=='parse' and args[args.index('--pages')+1]=='all'
    assert args[args.index('--format')+1]=='zip'
    source=pathlib.Path(args[1])
    count=source.read_bytes().count(b'/Type /Page ')
    fixture=pathlib.Path(os.environ['MINERU_FIXTURE_DIR'])
    middle=json.loads((fixture/'middle_json.json').read_text(encoding='utf-8'))
    structured=json.loads((fixture/'structured_content.json').read_text(encoding='utf-8'))
    for document in (middle,structured):
        page=document['pages'][0]
        document['pages']=[dict(copy.deepcopy(page),page_idx=i) for i in range(count)]
        document['metadata']['document']['page_count']=count
    if mode=='partial':
        middle['pages']=middle['pages'][:10]
        structured['pages']=structured['pages'][:10]
        middle['is_full_document']=False
    if mode=='invalid_schema': middle['schema_version']='invalid'
    if mode=='false_complete':
        middle['pages']=middle['pages'][:10]
        structured['pages']=structured['pages'][:10]
    if mode=='bad_bbox': structured['pages'][0]['blocks'][0]['bbox']=[0,0,1000,1000]
    if mode=='missing_asset': structured['pages'][0]['blocks'][-1]['image_source']='images/missing.png'
    if mode=='traversal': structured['pages'][0]['blocks'][-1]['image_source']='../outside.png'
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('middle_json.json',json.dumps(middle))
        z.writestr('structured_content.json',json.dumps(structured))
        z.writestr('markdown.md','\n\n'.join('Page '+str(i+1)+': synthetic evidence' for i in range(count)))
        z.writestr('images/figure.png',(fixture/'images/figure.png').read_bytes())
        if mode=='zip_traversal': z.writestr('../outside.txt','unsafe')
"""


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    directory = tmp_path / "CLI with spaces 教材"
    directory.mkdir()
    (directory / "mineru_fixture.py").write_text(FAKE_CLI, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(directory))
    monkeypatch.setenv("MINERU_FIXTURE_DIR", str(FIXTURE))

    def make(name="mineru-kit"):
        maker = ScriptMaker(None, str(directory))
        maker.executable = sys.executable
        maker.variants = {""}
        paths = maker.make(f"{name} = mineru_fixture:main")
        return (
            next(str(Path(p)) for p in paths if p.endswith(".exe")) if os.name == "nt" else paths[0]
        )

    return make


def _pdf(path: Path, count: int = 13) -> None:
    """Write a real, blank synthetic PDF with more than ten page objects."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Count %s /Kids [%s] >>"
            % (count, " ".join(f"{i + 3} 0 R" for i in range(count)))
        ).encode(),
    ]
    objects.extend(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>" for _ in range(count))
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(content)


def test_stateless_v4_preserves_all_pages_structure_and_images(tmp_path, fake_cli) -> None:
    from pypdf import PdfReader

    source = tmp_path / "多页 textbook.pdf"
    _pdf(source)
    original = source.read_bytes()
    assert len(PdfReader(source).pages) == 13
    result = local.parse_document_with_mineru_result(
        source, tmp_path / "out", cli_command=fake_cli()
    )
    assert result.ok, result
    output = tmp_path / "out" / source.stem
    markdown, blocks, assets = load_ir(output)
    assert "Page 13" in markdown
    assert {b["page_idx"] for b in blocks} == set(range(13))
    assert next(b for b in blocks if b["type"] == "equation")["text"] == "E=mc^2"
    assert "A" in next(b for b in blocks if b["type"] == "table")["table_body"]
    image = next(b for b in blocks if b["type"] == "image")
    assert Path(image["img_path"]).is_file() and assets == output / "images"
    assert image["bbox"] == [50, 100, 850, 400]
    assert (output / "middle_json.json").is_file()
    assert (output / "structured_content.json").is_file()
    assert source.read_bytes() == original

    from deeptutor.services.parsing.types import ParsedDocument
    from deeptutor.services.rag.visual_assets import collect_visual_assets

    parsed = ParsedDocument(
        markdown=markdown,
        blocks=blocks,
        asset_dir=assets,
        engine="mineru",
        source_hash="synthetic",
        parser_signature="mineru4-contract",
    )
    candidates = collect_visual_assets(parsed, source, tmp_path)
    assert len(candidates) == 1
    assert candidates[0].record["caption"] == "Synthetic reference diagram"
    assert candidates[0].record["page_number"] == 1
    assert candidates[0].record["bbox"] == [50, 100, 850, 400]


@pytest.mark.parametrize(
    "mode",
    [
        "fail",
        "empty",
        "partial",
        "false_complete",
        "invalid_schema",
        "bad_bbox",
        "missing_asset",
        "traversal",
        "zip_traversal",
    ],
)
def test_failed_attempt_preserves_previous_result_and_can_retry(
    tmp_path, fake_cli, monkeypatch, mode
):
    source = tmp_path / "source.pdf"
    _pdf(source)
    output = tmp_path / "out" / source.stem
    output.mkdir(parents=True)
    previous = output / "previous.md"
    previous.write_text("Previously validated evidence", encoding="utf-8")
    command = fake_cli()
    monkeypatch.setenv("MINERU_FIXTURE_MODE", mode)
    result = local.parse_document_with_mineru_result(source, output.parent, cli_command=command)
    assert not result.ok
    assert previous.read_text(encoding="utf-8") == "Previously validated evidence"
    assert list(output.parent.glob(".mineru-attempt-*/state.json"))
    assert not (output.parent / "outside.txt").exists()
    monkeypatch.setenv("MINERU_FIXTURE_MODE", "success")
    assert local.parse_document_with_mineru_result(source, output.parent, cli_command=command).ok
    assert not previous.exists()
    assert "Page 13" in load_ir(output)[0]


@pytest.mark.parametrize("version,name", [("5.0.0", "mineru-kit"), ("4.1.3", "mineru")])
def test_unsupported_cli_does_not_replace_configured_executable(
    tmp_path, fake_cli, monkeypatch, version, name
):
    source = tmp_path / "source.pdf"
    _pdf(source)
    monkeypatch.setenv("MINERU_FIXTURE_VERSION", version)
    monkeypatch.setattr(
        local, "check_mineru_installed", lambda: pytest.fail("must use configured CLI")
    )
    result = local.parse_document_with_mineru_result(
        source, tmp_path / "out", cli_command=fake_cli(name)
    )
    assert result.reason == local.LocalParseReason.UNSUPPORTED_CLI
    assert not (tmp_path / "out").exists()


def test_real_legacy_cli_retains_existing_contract(tmp_path, fake_cli, monkeypatch):
    source = tmp_path / "source.pdf"
    _pdf(source)
    monkeypatch.setenv("MINERU_FIXTURE_VERSION", "3.4.5")
    assert local.parse_document_with_mineru_result(
        source, tmp_path / "out", cli_command=fake_cli("mineru")
    ).ok
    assert load_ir(tmp_path / "out" / source.stem)[0] == "# Legacy document"


def test_version_probe_and_parse_deadlines_are_bounded(tmp_path, fake_cli, monkeypatch):
    from deeptutor.services.parsing.engines.mineru.cli_contract import read_cli_version

    command = fake_cli()
    monkeypatch.setenv("MINERU_FIXTURE_MODE", "version_timeout")
    with pytest.raises(TimeoutError, match="version probe"):
        read_cli_version(command, timeout=0.2)
    source = tmp_path / "source.pdf"
    _pdf(source)
    monkeypatch.setenv("MINERU_FIXTURE_MODE", "sleep")
    result = local.parse_document_with_mineru_result(
        source,
        tmp_path / "out",
        cli_command=command,
        extra_env={"MINERU_TASK_RESULT_TIMEOUT_SECONDS": "1"},
    )
    assert result.reason == local.LocalParseReason.TIMEOUT


def test_signature_uses_external_cli_version_and_readiness_does_not_trust_legacy_cache(
    fake_cli, monkeypatch
):
    from deeptutor.services.parsing.engines.mineru import readiness
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig
    from deeptutor.services.parsing.engines.mineru.engine import MinerUParser

    config = MinerUConfig(mode="local", local_cli_path=fake_cli())
    parser = MinerUParser()
    version4 = parser.signature(config).hash()
    monkeypatch.setenv("MINERU_FIXTURE_VERSION", "3.4.5")
    assert parser.signature(config).hash() != version4
    monkeypatch.setattr(readiness, "mineru_models_ready", lambda source: True)
    assert parser.is_ready(config).reason == "models_missing"
    assert parser.is_ready(replace(config, allow_local_model_download=True)).ready


def test_v4_parse_honors_task_cancellation(tmp_path, fake_cli, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.services.parsing import progress

    source = tmp_path / "source.pdf"
    _pdf(source)

    def cancel():
        raise progress.IndexingCancelled("cancelled test task")

    monkeypatch.setattr(progress, "current_run", lambda: SimpleNamespace(check=cancel))
    monkeypatch.setenv("MINERU_FIXTURE_MODE", "sleep")
    result = local.parse_document_with_mineru_result(
        source, tmp_path / "out", cli_command=fake_cli()
    )
    assert result.reason == local.LocalParseReason.CANCELLED
    assert not (tmp_path / "out" / source.stem).exists()
