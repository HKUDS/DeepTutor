"""Semantic-search tests against the existing locator-addressed reader."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.reading import ReadingCatalogStore, ReadingStore
from deeptutor.reading import description_search as semantic


def _material(tmp_path: Path) -> tuple[ReadingStore, str]:
    # Two target-sized sections make group and passage refs deterministic while
    # still going through the real extractor/store layout.
    source = tmp_path / "journey.txt"
    alpha = ("Mira studies maps beside the northern river. " * 520).strip()
    beta = ("In Athens, Mira discovers that her wallet was stolen. " * 520).strip()
    source.write_text(alpha + "\n\n" + beta, encoding="utf-8")
    store = ReadingStore(tmp_path / "reading")
    manifest = store.ingest(source)
    assert manifest.unit_count >= 2
    return store, manifest.material_id


@pytest.fixture(autouse=True)
def configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        semantic,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="test-model",
            binding="openai",
            context_window=100_000,
            max_tokens=4_096,
        ),
    )


@pytest.mark.asyncio
async def test_index_builds_one_deep_card_per_group_and_reuses_fresh_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, material_id = _material(tmp_path)
    calls: list[str] = []

    async def fake_complete(*, prompt: str, **kwargs):
        calls.append(prompt)
        assert kwargs["reasoning_effort"] == "high"
        return json.dumps(
            {
                "summary": "Source-faithful chapter summary",
                "characters": ["Mira"],
                "locations": ["Athens"],
                "time_markers": [],
                "timeline": ["A wallet is stolen"],
                "causal_links": [],
                "turning_points": [],
                "themes_and_motifs": [],
                "searchable_phrases": ["stolen wallet"],
            }
        )

    monkeypatch.setattr(semantic, "complete", fake_complete)
    groups = semantic.derive_search_groups(store, material_id)

    status = await semantic.build_description_index(store, material_id)

    assert status["status"] == "ready"
    assert status["completed_groups"] == len(groups)
    assert len(calls) == len(groups)

    await semantic.build_description_index(store, material_id)
    assert len(calls) == len(groups), "fresh source/model cards must not be regenerated"

    # Independent library copies share extracted content and derived cards,
    # unlike user-owned reading state. They must also share the build lock.
    manifest = store.manifest(material_id)
    copy_id = "rm_123456abcdef"
    ReadingCatalogStore(store.root).upsert_material(
        content_id=material_id,
        material_id=copy_id,
        filename=manifest.filename,
        title="Second copy",
        source_kind="file",
        status="ready",
    )
    assert semantic._lock_for(store, copy_id) is semantic._lock_for(store, material_id)
    copy_status = await semantic.build_description_index(store, copy_id)
    assert copy_status["status"] == "ready"
    assert len(calls) == len(groups)

    # A refreshed source must never reuse a same-size but different passage.
    locator, text = next(store.iter_units(material_id))
    unit_path = store.root / material_id / "units" / f"{locator:04d}.txt"
    unit_path.write_text(text.replace("Mira", "Zara"), encoding="utf-8")
    stale = semantic.description_index_status(store, copy_id)
    assert stale["needs_build"]
    assert stale["completed_groups"] < len(groups)
    await semantic.build_description_index(store, copy_id)
    assert len(calls) > len(groups)


@pytest.mark.asyncio
async def test_fast_search_routes_then_resolves_only_real_source_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, material_id = _material(tmp_path)
    target_locator = next(
        locator for locator, text in store.iter_units(material_id) if "Athens" in text
    )
    target_group = next(
        group
        for group in semantic.derive_search_groups(store, material_id)
        if target_locator in group.locators
    )
    target_ref = next(
        ref
        for ref, passage in semantic.passages_for_locators(
            store, material_id, target_group.locators
        ).items()
        if "Athens" in passage.text
    )

    async def fake_complete(*, prompt: str, system_prompt: str, **kwargs):
        if "Build a source-faithful retrieval card" in system_prompt:
            return json.dumps(
                {
                    "summary": "Athens travel and a stolen wallet"
                    if "Athens" in prompt
                    else "Maps",
                    "characters": ["Mira"],
                    "locations": ["Athens"] if "Athens" in prompt else ["river"],
                    "time_markers": [],
                    "timeline": [],
                    "causal_links": [],
                    "turning_points": [],
                    "themes_and_motifs": [],
                    "searchable_phrases": ["wallet stolen"],
                }
            )
        if "Route a semantic book search" in system_prompt:
            assert kwargs["reasoning_effort"] == "minimal"
            return json.dumps(
                {
                    "candidates": [
                        {
                            "group_id": target_group.group_id,
                            "confidence": 92,
                            "reason": "The card mentions Athens and a stolen wallet.",
                            "search_instructions": ["find the theft"],
                        }
                    ]
                }
            )
        assert "Find source passages" in system_prompt
        assert kwargs["reasoning_effort"] == "high"
        return json.dumps(
            {
                "matches": [
                    {
                        "ref": target_ref,
                        "score": 95,
                        "reason": "Direct event match",
                    },
                    {"ref": "invented-ref", "score": 100, "reason": "must be ignored"},
                ]
            }
        )

    monkeypatch.setattr(semantic, "complete", fake_complete)
    await semantic.build_description_index(store, material_id)

    hits, metadata = await semantic.fast_description_search(
        store, material_id, "the trip where a wallet disappeared"
    )

    assert metadata["resolved_mode"] == "description_fast"
    assert metadata["fallback_used"] is False
    assert [hit.locator for hit in hits] == [target_locator]
    assert "Athens" in hits[0].quote
    assert "invented" not in hits[0].quote


@pytest.mark.asyncio
async def test_low_router_confidence_retries_with_unchanged_fine_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, material_id = _material(tmp_path)
    target_locator = next(
        locator for locator, text in store.iter_units(material_id) if "Athens" in text
    )
    target_group = next(
        group
        for group in semantic.derive_search_groups(store, material_id)
        if target_locator in group.locators
    )
    target_ref = next(
        ref
        for ref, passage in semantic.passages_for_locators(
            store, material_id, range(1, store.manifest(material_id).unit_count + 1)
        ).items()
        if "Athens" in passage.text
    )

    async def fake_complete(*, prompt: str, system_prompt: str, **kwargs):
        if "Build a source-faithful retrieval card" in system_prompt:
            return json.dumps(
                {
                    "summary": "summary",
                    "characters": [],
                    "locations": [],
                    "time_markers": [],
                    "timeline": [],
                    "causal_links": [],
                    "turning_points": [],
                    "themes_and_motifs": [],
                    "searchable_phrases": [],
                }
            )
        if "Route a semantic book search" in system_prompt:
            return json.dumps(
                {
                    "candidates": [
                        {
                            "group_id": target_group.group_id,
                            "confidence": 20,
                            "reason": "weak",
                        }
                    ]
                }
            )
        assert "Locate passages in a book by meaning" in system_prompt
        return json.dumps(
            {
                "matches": [
                    {
                        "ref": target_ref,
                        "score": 90,
                        "reason": "fine match",
                    }
                ]
            }
        )

    monkeypatch.setattr(semantic, "complete", fake_complete)
    await semantic.build_description_index(store, material_id)

    hits, metadata = await semantic.fast_description_search(store, material_id, "wallet")

    assert hits and hits[0].locator == target_locator
    assert metadata == {
        "resolved_mode": "description_fine",
        "fallback_used": True,
        "fallback_reason": "low_router_confidence",
    }


@pytest.mark.asyncio
async def test_description_search_is_gated_below_50k_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, material_id = _material(tmp_path)
    monkeypatch.setattr(
        semantic,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="small-model",
            binding="openai",
            context_window=32_000,
            max_tokens=4_096,
        ),
    )

    with pytest.raises(semantic.DescriptionSearchUnavailable, match="50k"):
        await semantic.fine_description_search(store, material_id, "wallet")


def test_passages_keep_exact_offsets_and_locator_addresses(tmp_path: Path) -> None:
    store, material_id = _material(tmp_path)
    source = store.unit_text(material_id, 2)

    passages = semantic.passages_for_locators(store, material_id, [2])

    assert passages
    for passage in passages.values():
        assert passage.locator == 2
        assert source[passage.start : passage.end] == passage.text
