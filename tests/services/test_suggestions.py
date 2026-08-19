"""Starter suggestions — material, caching, shaping, and staying off the request path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

import pytest

from deeptutor.services import suggestions
from deeptutor.services.memory.recall import RecallHit

# The autouse fixture stubs _render_l3 so trace tests speak only about traces.
# The L3 tests below restore this.
_REAL_RENDER_L3 = suggestions._render_l3


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_workspace_dir(self) -> Path:
        return self._root

    def get_settings_file(self, name: str) -> Path:
        return self._root / "settings" / f"{name}.json"


@pytest.fixture(autouse=True)
def isolated_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route the cache into tmp_path, clear in-process maps, pin the language.

    L3 is stubbed empty by default so material tests speak only about traces;
    the tests that care about L3 override it.
    """
    import deeptutor.services.path_service as path_service

    monkeypatch.setattr(path_service, "get_path_service", lambda: _FakePathService(tmp_path))
    monkeypatch.setattr(suggestions, "_output_language", lambda: "en")
    monkeypatch.setattr(suggestions, "_render_l3", lambda cap: "")
    suggestions._inflight.clear()
    suggestions._last_probe.clear()
    yield tmp_path
    suggestions._inflight.clear()
    suggestions._last_probe.clear()


@pytest.fixture
def no_material(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.memory import recall

    monkeypatch.setattr(recall, "recent", lambda **_: [])
    monkeypatch.setattr(recall, "recent_queries", lambda **_: [])


def _hit(surface: str, label: str, age: int = 1, ts: str = "") -> RecallHit:
    # Descending ts by age keeps "newest first" meaningful in flat ordering.
    return RecallHit(
        surface=surface,
        label=label,
        ts=ts or f"2026-08-{max(1, 30 - age):02d}T10:00:00+00:00",
        days_ago=age,
    )


def _stub_material(monkeypatch: pytest.MonkeyPatch, hits: list[RecallHit]) -> None:
    from deeptutor.services.memory import recall

    monkeypatch.setattr(recall, "recent", lambda **_: list(hits))
    monkeypatch.setattr(recall, "recent_queries", lambda **_: [])


def _stub_llm(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[str]:
    """Replace the LLM with a canned reply; returns the list of prompts seen."""
    import deeptutor.services.llm as llm

    seen: list[str] = []

    async def _complete(prompt: str, **kwargs) -> str:
        seen.append(prompt)
        return reply

    monkeypatch.setattr(llm, "complete", _complete)
    return seen


_THREE = json.dumps(
    [
        {"label": "How agentic RAG differs from naive RAG", "prompt": "Explain the difference."},
        {"label": "Why the chain rule underlies backprop", "prompt": "Walk me through it."},
        {"label": "What an eigenvalue actually measures", "prompt": "Start from the geometry."},
    ]
)


def _write_cache(root: Path, payload: dict) -> None:
    directory = root / "suggestions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "starters.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ── Shaping ──────────────────────────────────────────────────────────────


def test_sanitize_accepts_a_plain_array() -> None:
    items = suggestions._sanitize(_THREE, "en")

    assert [item.label for item in items] == [
        "How agentic RAG differs from naive RAG",
        "Why the chain rule underlies backprop",
        "What an eigenvalue actually measures",
    ]


def test_sanitize_accepts_a_fenced_array_with_prose_around_it() -> None:
    raw = f"Sure, here they are:\n```json\n{_THREE}\n```\nHope that helps!"

    assert len(suggestions._sanitize(raw, "en")) == 3


def test_sanitize_discards_a_partial_set() -> None:
    """One lonely line under the composer reads as a rendering bug."""
    raw = json.dumps([{"label": "a", "prompt": "b"}, {"label": "c", "prompt": "d"}])

    assert suggestions._sanitize(raw, "en") == ()


def test_sanitize_bounds_are_per_language() -> None:
    """A character is not a unit of meaning, so one bound cannot serve both.

    These three are real model output for an English UI. Judged against a bound
    sized for Chinese they are all "too long" and the whole batch is discarded
    — which presents as the model failing, on English installs only.
    """
    english = json.dumps(
        [
            {
                "label": "How Self-Correction loops in LangGraph reduce pedagogical hallucinations",
                "prompt": "How can I use LangGraph's cyclic patterns to implement a "
                "self-correction loop that verifies factual accuracy?",
            },
            {
                "label": "Why RAG retrieval constraints differ for educational coaching versus search",
                "prompt": "How should RAG retrieval be constrained to guide a student "
                "toward an answer rather than simply providing it?",
            },
            {
                "label": "The trade-off between agentic autonomy and curriculum adherence",
                "prompt": "How do we balance an agent's autonomy against a syllabus?",
            },
        ]
    )

    assert len(suggestions._sanitize(english, "en")) == 3
    # The same text under the Chinese bound is correctly judged over-long.
    assert suggestions._sanitize(english, "zh") == ()


def test_sanitize_drops_items_that_ignored_the_brief() -> None:
    raw = json.dumps(
        [
            {"label": "x" * 200, "prompt": "fine"},  # label is a paragraph
            {"label": "ok", "prompt": "y" * 600},  # prompt is an essay
            {"label": "missing prompt"},
            {"label": "good", "prompt": "a real question"},
        ]
    )

    # Three were dropped, so the batch is short and goes entirely.
    assert suggestions._sanitize(raw, "en") == ()


def test_sanitize_dedupes_repeated_labels() -> None:
    raw = json.dumps(
        [
            {"label": "Same", "prompt": "one"},
            {"label": "same", "prompt": "two"},
            {"label": "Other", "prompt": "three"},
            {"label": "Third", "prompt": "four"},
        ]
    )

    assert [i.label for i in suggestions._sanitize(raw, "en")] == ["Same", "Other", "Third"]


def test_sanitize_strips_quotes_and_collapses_whitespace() -> None:
    raw = json.dumps(
        [
            {"label": '"Quoted"', "prompt": "a  ragged\n\nquestion"},
            {"label": "B", "prompt": "b"},
            {"label": "C", "prompt": "c"},
        ]
    )

    items = suggestions._sanitize(raw, "en")
    assert items[0].label == "Quoted"
    assert items[0].prompt == "a ragged question"


def test_sanitize_rejects_non_arrays() -> None:
    assert suggestions._sanitize('{"label": "x", "prompt": "y"}', "en") == ()
    assert suggestions._sanitize("no json here at all", "en") == ()


# ── Material: traces ─────────────────────────────────────────────────────


def test_traces_are_flat_and_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """One ordering across every surface. Which surface it came from says
    nothing about whether the learner is in the middle of it."""
    _stub_material(
        monkeypatch,
        [
            _hit("book", "Calculus notes", age=5),
            _hit("chat", "Chain rule", age=1),
            _hit("quiz", "What is an eigenvalue?", age=3),
        ],
    )

    topics = suggestions._collect_material(10).topics

    assert [t.label for t in topics] == [
        "Chain rule",
        "What is an eigenvalue?",
        "Calculus notes",
    ]


def test_trace_count_bounds_the_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_material(monkeypatch, [_hit("chat", f"Session {i}", age=i) for i in range(1, 30)])

    assert len(suggestions._collect_material(5).topics) == 5
    assert len(suggestions._collect_material(20).topics) == 20


def test_traces_merge_kb_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.memory import recall

    monkeypatch.setattr(recall, "recent", lambda **_: [_hit("chat", "Chain rule", age=2)])
    monkeypatch.setattr(
        recall, "recent_queries", lambda **_: [_hit("kb", "how does backprop work", age=1)]
    )

    labels = [t.label for t in suggestions._collect_material(10).topics]

    assert labels == ["how does backprop work", "Chain rule"]


def test_traces_drop_noise_before_the_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filtering after the cut would let a run of placeholders eat the budget.

    Placeholder titles are the *newest* rows by definition — a conversation is
    created before it is named — so a naive "take k then filter" returns
    nothing on an install where someone just opened three blank chats.
    """
    _stub_material(
        monkeypatch,
        [
            _hit("chat", "New conversation", age=0),
            _hit("chat", "新对话", age=0),
            _hit("kb", "q", age=0),
            _hit("chat", "LangGraph checkpointing", age=4),
        ],
    )

    assert [t.label for t in suggestions._collect_material(2).topics] == ["LangGraph checkpointing"]


def test_traces_dedupe_by_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_material(
        monkeypatch,
        [_hit("chat", "Chain rule", age=1), _hit("book", "chain RULE", age=3)],
    )

    assert len(suggestions._collect_material(10).topics) == 1


def test_traces_survive_a_broken_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.memory import recall

    def _boom(**_):
        raise RuntimeError("memory unreadable")

    monkeypatch.setattr(recall, "recent", _boom)
    monkeypatch.setattr(recall, "recent_queries", lambda **_: [_hit("kb", "a real query")])

    assert [t.label for t in suggestions._collect_material(10).topics] == ["a real query"]


# ── Material: L3 ─────────────────────────────────────────────────────────


class _FakeDoc:
    def __init__(self, title: str, sections: list[tuple[str, list[str]]]) -> None:
        self.title = title
        self.sections = [
            (name, [type("E", (), {"text": t})() for t in texts]) for name, texts in sections
        ]


def test_l3_renders_sections_and_bullets(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.memory as memory

    docs = {
        "scope": _FakeDoc("Knowledge scope", [("Unsure", ["Reranking trade-offs"])]),
        "profile": _FakeDoc("User profile", [("Level", ["Comfortable with Python"])]),
    }

    class _Store:
        def read_doc(self, layer: str, key: str):
            return docs.get(key, _FakeDoc("", []))

    monkeypatch.setattr(memory, "get_memory_store", lambda: _Store())
    monkeypatch.setattr(suggestions, "_render_l3", _REAL_RENDER_L3)

    rendered = suggestions._render_l3(6000)

    assert "## Knowledge scope" in rendered
    # Section names pass through untranslated — the consolidator writes them in
    # the deployment's language and reading them is the model's job.
    assert "### Unsure" in rendered
    assert "- Reranking trade-offs" in rendered
    assert "## User profile" in rendered


def test_l3_is_bounded_and_carries_unspent_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tiny preferences doc must not cost scope its share."""
    import deeptutor.services.memory as memory

    docs = {
        "preferences": _FakeDoc("Preferences", [("P", ["Terse"])]),
        "scope": _FakeDoc("Scope", [("Unsure", [f"item {i} " + "x" * 40 for i in range(40)])]),
    }

    class _Store:
        def read_doc(self, layer: str, key: str):
            return docs.get(key, _FakeDoc("", []))

    monkeypatch.setattr(memory, "get_memory_store", lambda: _Store())
    monkeypatch.setattr(suggestions, "_render_l3", _REAL_RENDER_L3)

    small = suggestions._render_l3(200)
    large = suggestions._render_l3(4000)

    assert len(small) <= 400  # bounded, with per-section headers as overhead
    assert len(large) > len(small)
    # The scope entries got more than a bare quarter share, because preferences
    # spent almost none of its own.
    assert large.count("item ") > 4


def test_l3_failure_is_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.memory as memory

    def _boom():
        raise RuntimeError("memory offline")

    monkeypatch.setattr(memory, "get_memory_store", _boom)
    monkeypatch.setattr(suggestions, "_render_l3", _REAL_RENDER_L3)

    assert suggestions._render_l3(6000) == ""


# ── Reads ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_without_a_cache_is_empty_and_stale(no_material) -> None:
    result = await suggestions.get_suggestions()

    assert result["suggestions"] == []
    assert result["stale"] is True


@pytest.mark.asyncio
async def test_read_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch, isolated_scope: Path
) -> None:
    """The request path reads one JSON file and nothing else."""
    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])
    calls = _stub_llm(monkeypatch, _THREE)
    _write_cache(
        isolated_scope,
        {
            "suggestions": [{"label": "cached", "prompt": "from disk"}],
            "language": "en",
            "generated_at": time.time(),
            "fingerprint": "whatever",
        },
    )

    result = await suggestions.get_suggestions()

    assert [i["label"] for i in result["suggestions"]] == ["cached"]
    assert result["stale"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_expired_cache_is_still_served_while_it_regenerates(
    monkeypatch: pytest.MonkeyPatch, isolated_scope: Path
) -> None:
    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])
    _stub_llm(monkeypatch, _THREE)
    _write_cache(
        isolated_scope,
        {
            "suggestions": [{"label": "yesterday", "prompt": "old"}],
            "language": "en",
            "generated_at": time.time() - suggestions._TTL_SECONDS - 1,
            "fingerprint": "old",
        },
    )

    result = await suggestions.get_suggestions()

    # Served immediately, flagged for a second look.
    assert [i["label"] for i in result["suggestions"]] == ["yesterday"]
    assert result["stale"] is True

    await asyncio.gather(*suggestions._inflight.values())
    after = await suggestions.get_suggestions()
    assert len(after["suggestions"]) == 3


@pytest.mark.asyncio
async def test_a_cache_in_another_language_is_not_served(
    monkeypatch: pytest.MonkeyPatch, isolated_scope: Path, no_material
) -> None:
    """Changing the model-output setting invalidates what was generated before."""
    _write_cache(
        isolated_scope,
        {
            "suggestions": [{"label": "缓存的", "prompt": "旧的"}],
            "language": "zh",
            "generated_at": time.time(),
            "fingerprint": "x",
        },
    )

    result = await suggestions.get_suggestions()  # setting says "en"

    assert result["suggestions"] == []
    assert result["stale"] is True


@pytest.mark.asyncio
async def test_probe_is_throttled_across_a_burst_of_loads(
    monkeypatch: pytest.MonkeyPatch, no_material
) -> None:
    scheduled: list[int] = []

    async def _noop() -> None:
        scheduled.append(1)

    monkeypatch.setattr(suggestions, "_regenerate_if_due", _noop)

    for _ in range(5):
        await suggestions.get_suggestions()
    await asyncio.gather(*suggestions._inflight.values())

    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_a_language_switch_regenerates_without_waiting_out_the_throttle(
    monkeypatch: pytest.MonkeyPatch, isolated_scope: Path, no_material
) -> None:
    """Changing the output setting must not leave a minute of empty screen.

    The learner is on the home screen (which already spent this scope's probe),
    goes to Settings, changes the language, and comes back. The cached set is
    now unusable, so the ordinary interval — which exists for bursts of page
    loads where nothing changed — is exactly the wrong thing to enforce.
    """
    scheduled: list[int] = []

    async def _noop() -> None:
        scheduled.append(1)

    monkeypatch.setattr(suggestions, "_regenerate_if_due", _noop)
    _write_cache(
        isolated_scope,
        {
            "suggestions": [{"label": "\u65e7\u7684", "prompt": "\u65e7\u7684"}],
            "language": "zh",
            "generated_at": time.time(),
            "fingerprint": "x",
        },
    )
    # Spend the throttle, as a first page load would.
    suggestions._last_probe[suggestions._scope_key()] = time.monotonic()

    result = await suggestions.get_suggestions()  # setting now says "en"
    await asyncio.gather(*suggestions._inflight.values())

    assert result["suggestions"] == []
    assert scheduled == [1], "the language switch should have forced a probe"


@pytest.mark.asyncio
async def test_a_forced_probe_still_respects_the_in_flight_guard(
    monkeypatch: pytest.MonkeyPatch, no_material
) -> None:
    """Bypassing the interval must not mean fanning out concurrent calls."""
    started = asyncio.Event()
    release = asyncio.Event()
    runs: list[int] = []

    async def _slow() -> None:
        runs.append(1)
        started.set()
        await release.wait()

    monkeypatch.setattr(suggestions, "_regenerate_if_due", _slow)

    suggestions._schedule_probe(force=True)
    await started.wait()
    suggestions._schedule_probe(force=True)
    suggestions._schedule_probe(force=True)

    release.set()
    await asyncio.gather(*suggestions._inflight.values())

    assert runs == [1]


# ── Generation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_material_means_no_model_call(
    monkeypatch: pytest.MonkeyPatch, no_material
) -> None:
    """A brand-new learner has no history to ground a suggestion in."""
    calls = _stub_llm(monkeypatch, _THREE)

    result = await suggestions.refresh_suggestions()

    assert result.suggestions == ()
    assert calls == []


@pytest.mark.asyncio
async def test_l3_alone_is_enough_material(monkeypatch: pytest.MonkeyPatch, no_material) -> None:
    """Someone whose traces have aged out still has a consolidated profile."""
    monkeypatch.setattr(suggestions, "_render_l3", lambda cap: "## Scope\n### Unsure\n- Rerankers")
    calls = _stub_llm(monkeypatch, _THREE)

    result = await suggestions.refresh_suggestions()

    assert len(result.suggestions) == 3
    assert "Rerankers" in calls[0]


@pytest.mark.asyncio
async def test_generation_shows_both_halves_of_the_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_material(monkeypatch, [_hit("quiz", "What is an eigenvalue?", age=0)])
    monkeypatch.setattr(suggestions, "_render_l3", lambda cap: "## Scope\n### Unsure\n- Eigenbases")
    calls = _stub_llm(monkeypatch, _THREE)

    await suggestions.refresh_suggestions()

    prompt = calls[0]
    assert "Eigenbases" in prompt  # L3
    assert "What is an eigenvalue?" in prompt  # trace
    assert "practice question" in prompt  # surface, in the learner's words
    assert "today" in prompt  # recency


@pytest.mark.asyncio
async def test_output_language_comes_from_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not from the caller: the UI locale can resolve before settings load."""
    monkeypatch.setattr(suggestions, "_output_language", lambda: "zh")
    _stub_material(monkeypatch, [_hit("quiz", "特征值的几何意义", age=0)])
    calls = _stub_llm(monkeypatch, _THREE)

    result = await suggestions.refresh_suggestions()

    assert result.language == "zh"
    assert "错题" in calls[0]  # Chinese surface vocabulary
    assert "今天" in calls[0]


@pytest.mark.asyncio
async def test_a_failing_model_leaves_an_empty_set_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.services.llm as llm

    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])

    async def _boom(**_):
        raise RuntimeError("no provider configured")

    monkeypatch.setattr(llm, "complete", _boom)

    result = await suggestions.refresh_suggestions()

    assert result.suggestions == ()


@pytest.mark.asyncio
async def test_a_failed_generation_is_not_cached_over_the_material(
    monkeypatch: pytest.MonkeyPatch, isolated_scope: Path
) -> None:
    """Caching a failure would pin it in place for a whole TTL.

    The fingerprint of a failed run matches the material it failed on, so the
    background pass would then see "fresh, unchanged" and never retry — the
    learner gets an empty slot for six hours because one call timed out.
    """
    import deeptutor.services.llm as llm

    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])

    async def _boom(**_):
        raise RuntimeError("provider timed out")

    monkeypatch.setattr(llm, "complete", _boom)
    await suggestions.refresh_suggestions()

    assert not (isolated_scope / "suggestions" / "starters.json").exists()

    # And the retry lands, rather than being skipped as "nothing due".
    calls = _stub_llm(monkeypatch, _THREE)
    await suggestions._regenerate_if_due()
    assert len(calls) == 1
    assert len((await suggestions.get_suggestions())["suggestions"]) == 3


@pytest.mark.asyncio
async def test_an_empty_result_with_no_material_is_cached(
    isolated_scope: Path, no_material
) -> None:
    """Empty is the right answer here, and repeating it should stay free."""
    await suggestions.refresh_suggestions()

    assert (isolated_scope / "suggestions" / "starters.json").exists()


@pytest.mark.asyncio
async def test_unchanged_material_inside_the_ttl_skips_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])
    calls = _stub_llm(monkeypatch, _THREE)

    await suggestions.refresh_suggestions()
    assert len(calls) == 1

    # Same material, still fresh: the background pass must not spend a call.
    await suggestions._regenerate_if_due()
    assert len(calls) == 1

    # New material: it must.
    _stub_material(monkeypatch, [_hit("chat", "Eigenvalues")])
    await suggestions._regenerate_if_due()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_changed_l3_alone_triggers_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The profile is half the material, so it belongs in the fingerprint."""
    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])
    monkeypatch.setattr(suggestions, "_render_l3", lambda cap: "## Scope\n- A")
    calls = _stub_llm(monkeypatch, _THREE)

    await suggestions.refresh_suggestions()
    assert len(calls) == 1

    monkeypatch.setattr(suggestions, "_render_l3", lambda cap: "## Scope\n- B")
    await suggestions._regenerate_if_due()
    assert len(calls) == 2


# ── Isolation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_users_never_see_each_others_suggestions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is addressed through the multi-user path service, so one
    user's lines must not leak into another's response."""
    import deeptutor.services.path_service as path_service

    alice, bob = tmp_path / "alice", tmp_path / "bob"
    current = {"root": alice}
    monkeypatch.setattr(path_service, "get_path_service", lambda: _FakePathService(current["root"]))
    _stub_material(monkeypatch, [_hit("chat", "Chain rule")])
    _stub_llm(monkeypatch, _THREE)

    await suggestions.refresh_suggestions()
    mine = await suggestions.get_suggestions()
    assert len(mine["suggestions"]) == 3

    current["root"] = bob
    theirs = await suggestions.get_suggestions()
    assert theirs["suggestions"] == []
