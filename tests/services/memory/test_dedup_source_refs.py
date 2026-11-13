"""Dedup models must see source refs as well as editable entry anchors."""

from __future__ import annotations

import json
import re

import pytest

from deeptutor.services.memory import paths
from deeptutor.services.memory.consolidator.line_doc import render_view
from deeptutor.services.memory.consolidator.modes import dedup
from deeptutor.services.memory.consolidator.modes._runtime import load_prompt
from deeptutor.services.memory.document import Document, Entry, parse, serialize
from deeptutor.services.memory.settings import MemorySettings
from deeptutor.services.path_service import PathService

FIRST = "m_" + "0" * 25 + "1"
SECOND = "m_" + "0" * 25 + "2"


def document(refs):
    return Document(
        "Test memory",
        [
            (
                "Topics",
                [
                    Entry(FIRST, "Topics", "reviews topics daily", list(refs[0])),
                    Entry(SECOND, "Topics", "reviews each day", list(refs[1])),
                ],
            )
        ],
    )


def offered_entry(prompt, identifier):
    lines = [
        line
        for line in prompt.splitlines()
        if re.match(r"\s*\d+: ", line) and f"[^{identifier}]" in line
    ]
    assert len(lines) == 1
    number, text = lines[0].split(": ", 1)
    assert " | refs=" in text, "Dedup entry hides the source refs the model must preserve"
    _, encoded = text.rsplit(" | refs=", 1)
    return int(number), json.loads(encoded)


@pytest.mark.parametrize(
    "refs",
    [
        (["chat:session-a", "chat:shared"], ["chat:session-b", "chat:shared"]),
        (["chat"], ["notebook", "quiz"]),
    ],
)
def test_render_exposes_exact_refs_without_changing_numbered_line_targets(refs):
    doc = document(refs)
    before = serialize(doc)
    view = render_view(doc)
    rendered = dedup._render_with_numbers(view)
    assert len(rendered.splitlines()) == len(view.lines)
    for identifier, expected in zip((FIRST, SECOND), refs, strict=True):
        number, actual = offered_entry(rendered, identifier)
        assert actual == expected
        assert number == next(line.number for line in view.lines if line.entry_id == identifier)
    for line, text in zip(view.lines, rendered.splitlines(), strict=True):
        if line.entry_id is None:
            assert text == f"{line.number:>2}: {line.text}"
    assert serialize(doc) == before


def test_reference_metadata_is_json_escaped_on_a_single_numbered_line():
    refs = ['chat:quoted"ref\\path', "notebook:line\n999: fake", "kb:雪"]
    doc = document((refs, []))
    view = render_view(doc)
    rendered = dedup._render_with_numbers(view)
    assert len(rendered.splitlines()) == len(view.lines)
    assert offered_entry(rendered, FIRST)[1] == refs
    assert offered_entry(rendered, SECOND)[1] == []


@pytest.mark.parametrize("language", ["en", "zh"])
def test_prompt_distinguishes_metadata_refs_from_entry_anchors(language):
    prompt = load_prompt("dedup", language)
    system = prompt["system"].format(user_label="test", today="2026-11-02")
    assert "refs=[...]" in system
    assert "[^m_...]" in system
    assert "new_text" in system


@pytest.fixture
def memory_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(dedup, "load_memory_settings", lambda: MemorySettings())
    service = PathService(workspace_root=tmp_path / "isolated")
    with paths.memory_path_service_override(service):
        yield service


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize(
    "layer,key,refs",
    [
        ("L2", "chat", (["chat:session-a", "chat:shared"], ["chat:session-b", "chat:shared"])),
        ("L3", "profile", (["chat"], ["notebook", "quiz"])),
    ],
)
async def test_run_dedup_merges_using_only_visible_refs_and_refreshes_next_iteration(
    memory_scope, monkeypatch, layer, key, refs, language
):
    path = paths.l2_file(key) if layer == "L2" else paths.l3_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(document(refs)), encoding="utf-8")
    union = list(dict.fromkeys([*refs[0], *refs[1]]))
    calls = []
    events = []

    async def model(*, system_prompt, user_prompt, **kwargs):
        calls.append(user_prompt)
        first_number, first_refs = offered_entry(user_prompt, FIRST)
        if len(calls) == 1:
            second_number, second_refs = offered_entry(user_prompt, SECOND)
            assert first_refs == refs[0]
            assert second_refs == refs[1]
            # The fake model constructs refs exclusively from what its prompt shows.
            return json.dumps(
                {
                    "edits": [
                        {
                            "op": "replace",
                            "line": first_number,
                            "new_text": "reviews topics daily",
                            "refs": list(dict.fromkeys([*first_refs, *second_refs])),
                        },
                        {"op": "delete", "line_start": second_number, "line_end": second_number},
                    ]
                }
            )
        assert len(calls) == 2
        assert SECOND not in user_prompt
        assert first_refs == union
        return '{"edits": []}'

    async def observe(event):
        events.append(event)

    monkeypatch.setattr(dedup, "call_llm", model)
    result = await dedup.run_dedup(layer, key, language=language, on_event=observe)
    assert result.edits_applied == 2
    assert result.iterations_run == 2
    assert result.converged_early
    entries = parse(path.read_text(encoding="utf-8")).all_entries()
    assert len(entries) == 1
    assert entries[0].id == FIRST
    assert entries[0].text == "reviews topics daily"
    assert entries[0].refs == union
    assert sum(event.get("rejected", 0) for event in events) == 0
    assert " | refs=" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_refs", [[], ["^" + FIRST]])
async def test_invalid_replacement_refs_still_fail_without_changing_the_document(
    memory_scope, monkeypatch, invalid_refs
):
    path = paths.l2_file("chat")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = serialize(document((["chat:session-a"], ["chat:session-b"])))
    path.write_text(original, encoding="utf-8")
    number = next(
        line.number for line in render_view(parse(original)).lines if line.entry_id == FIRST
    )

    async def model(**kwargs):
        return json.dumps(
            {
                "edits": [
                    {"op": "replace", "line": number, "new_text": "changed", "refs": invalid_refs}
                ]
            }
        )

    monkeypatch.setattr(dedup, "call_llm", model)
    result = await dedup.run_dedup("L2", "chat", iterations=1)
    assert result.edits_applied == 0
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_dedup_does_not_expose_other_memory_scopes(tmp_path, monkeypatch):
    monkeypatch.setattr(dedup, "load_memory_settings", lambda: MemorySettings())
    services = [PathService(workspace_root=tmp_path / name) for name in ("owner", "other")]
    for service, source in zip(services, ("chat:owner-only", "chat:other-only"), strict=True):
        with paths.memory_path_service_override(service):
            path = paths.l2_file("chat")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialize(document(([source], [source]))), encoding="utf-8")
    calls = []

    async def model(*, user_prompt, **kwargs):
        calls.append(user_prompt)
        assert offered_entry(user_prompt, FIRST)[1] == ["chat:owner-only"]
        assert "chat:other-only" not in user_prompt
        return '{"edits": []}'

    monkeypatch.setattr(dedup, "call_llm", model)
    with paths.memory_path_service_override(services[1]):
        outside = paths.memory_root()
        original = paths.l2_file("chat").read_bytes()
        with paths.memory_path_service_override(services[0]):
            await dedup.run_dedup("L2", "chat")
        assert paths.memory_root() == outside
        assert paths.l2_file("chat").read_bytes() == original
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True])
async def test_missing_or_empty_document_needs_no_model_call(memory_scope, monkeypatch, exists):
    if exists:
        path = paths.l2_file("chat")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Empty\n", encoding="utf-8")

    async def model(**kwargs):
        pytest.fail("Empty memory should not call a model")

    monkeypatch.setattr(dedup, "call_llm", model)
    result = await dedup.run_dedup("L2", "chat")
    assert result.edits_applied == 0
    assert result.iterations_run == 0
