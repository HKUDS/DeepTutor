"""Tests for the subagent driver layer: command building, event parsing,
the streaming-subprocess primitive, and settings.

Event parsing is exercised by feeding crafted CLI events straight into each
backend's handler — no real ``claude`` / ``codex`` process is spawned, so the
suite is fast and deterministic. The one live subprocess test drives ``python``
to prove the streaming primitive surfaces stdout/stderr in order with an exit.
"""

from __future__ import annotations

import sys

import pytest

from deeptutor.services.subagent.claude_code import ClaudeCodeBackend
from deeptutor.services.subagent.codex import CodexBackend
from deeptutor.services.subagent.config import (
    CONSULT_BUDGET_MAX,
    DEFAULT_CONSULT_BUDGET,
    BackendConfig,
    SubagentSettings,
    settings_from_dict,
)
from deeptutor.services.subagent.process import stream_process_lines
from deeptutor.services.subagent.types import ConsultResult

# ---- command building --------------------------------------------------------


def test_claude_command_build_fresh_and_resume() -> None:
    backend = ClaudeCodeBackend()
    cfg = BackendConfig(permission_mode="acceptEdits", extra_args=["--foo"])
    fresh = backend._build_command("hi", session_id=None, config=cfg)
    assert fresh[:3] == ["claude", "-p", "hi"]
    assert "--output-format" in fresh and "stream-json" in fresh and "--verbose" in fresh
    assert "--permission-mode" in fresh and "acceptEdits" in fresh
    assert "--resume" not in fresh
    assert fresh[-1] == "--foo"

    resumed = backend._build_command("again", session_id="sess-1", config=cfg)
    assert "--resume" in resumed and "sess-1" in resumed


def test_codex_command_build_sandbox_and_resume() -> None:
    backend = CodexBackend()
    cfg = BackendConfig(sandbox="workspace-write")
    fresh = backend._build_command("hi", session_id=None, config=cfg)
    assert fresh[:2] == ["codex", "exec"]
    assert "resume" not in fresh
    assert "--json" in fresh and "--skip-git-repo-check" in fresh
    assert "-c" in fresh and 'sandbox_mode="workspace-write"' in fresh
    assert fresh[-1] == "hi"  # prompt is the trailing positional

    resumed = backend._build_command("again", session_id="abc", config=cfg)
    assert resumed[1:3] == ["exec", "resume"] and "abc" in resumed


def test_claude_command_applies_model_effort_system_prompt() -> None:
    backend = ClaudeCodeBackend()
    cfg = BackendConfig(model="opus", effort="high", system_prompt="consulted by DeepTutor")
    cmd = backend._build_command("hi", session_id=None, config=cfg)
    assert "--model" in cmd and "opus" in cmd
    assert "--effort" in cmd and "high" in cmd
    assert "--append-system-prompt" in cmd and "consulted by DeepTutor" in cmd


def test_codex_command_applies_model_effort_network_ephemeral() -> None:
    backend = CodexBackend()
    cfg = BackendConfig(
        model="gpt-5-codex",
        effort="high",
        network_access=True,
        ephemeral=True,
        approval="never",
        sandbox="workspace-write",
    )
    fresh = backend._build_command("hi", session_id=None, config=cfg)
    assert "-m" in fresh and "gpt-5-codex" in fresh
    assert 'model_reasoning_effort="high"' in fresh
    assert 'approval_policy="never"' in fresh
    assert "sandbox_workspace_write.network_access=true" in fresh
    assert "--ephemeral" in fresh
    # --ephemeral is a fresh-only flag — resuming an existing session omits it.
    resumed = backend._build_command("hi", session_id="s1", config=cfg)
    assert "--ephemeral" not in resumed


def test_codex_command_bypass_uses_real_flag() -> None:
    backend = CodexBackend()
    cmd = backend._build_command("hi", session_id=None, config=BackendConfig(sandbox="bypass"))
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "-c" not in cmd  # bypass replaces the sandbox_mode override


def test_claude_command_forwards_images_via_read() -> None:
    # CC's -p has no image flag, so we point its Read tool at the files and grant
    # their directory with --add-dir.
    backend = ClaudeCodeBackend()
    imgs = ["/tmp/dt-x/00_a.png", "/tmp/dt-x/01_b.png"]
    cmd = backend._build_command("look", session_id=None, config=BackendConfig(), images=imgs)
    prompt = cmd[2]
    assert "Read tool" in prompt
    assert "/tmp/dt-x/00_a.png" in prompt and "/tmp/dt-x/01_b.png" in prompt
    assert "--add-dir" in cmd and "/tmp/dt-x" in cmd


def test_codex_command_attaches_images_with_repeated_flag() -> None:
    # Repeated -i (not the variadic form) so the trailing prompt is never swallowed.
    backend = CodexBackend()
    imgs = ["/tmp/dt-y/00_a.png", "/tmp/dt-y/01_b.png"]
    cmd = backend._build_command("look", session_id=None, config=BackendConfig(), images=imgs)
    assert cmd.count("-i") == 2
    assert cmd[cmd.index("-i") + 1] == "/tmp/dt-y/00_a.png"
    assert cmd[-1] == "look"  # prompt stays the trailing positional


# ---- Claude Code event parsing -----------------------------------------------


async def _drive(backend, events):
    """Feed crafted events through a backend handler, collecting emitted events."""
    result = ConsultResult()
    emitted: list[tuple[str, str]] = []

    async def emit(kind, text, raw, meta=None):
        emitted.append((kind, text))

    if isinstance(backend, ClaudeCodeBackend):
        assistant_text: list[str] = []
        stream: dict = {"msg_id": "", "blocks": {}}
        for ev in events:
            await backend._handle_event(ev, result, assistant_text, stream, emit)
        if not result.final_text and assistant_text:
            result.final_text = "\n".join(assistant_text)
    else:
        for ev in events:
            await backend._handle_event(ev, result, emit)
    return result, emitted


@pytest.mark.asyncio
async def test_claude_event_parsing_captures_session_text_and_tools() -> None:
    backend = ClaudeCodeBackend()
    events = [
        {"type": "system", "subtype": "init", "session_id": "s1", "model": "opus"},
        {
            "type": "assistant",
            "session_id": "s1",
            "message": {
                "content": [
                    {"type": "text", "text": "Looking into it."},
                    {"type": "tool_use", "name": "Read", "input": {"file": "a.py"}},
                ]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "file body"}]},
        },
        # The final answer arrives as an assistant text block …
        {
            "type": "assistant",
            "session_id": "s1",
            "message": {"content": [{"type": "text", "text": "Final answer."}]},
        },
        # … and the result event mirrors it (we don't re-emit — no duplicate row).
        {"type": "result", "subtype": "success", "result": "Final answer.", "session_id": "s1"},
    ]
    result, emitted = await _drive(backend, events)
    assert result.session_id == "s1"
    assert result.final_text == "Final answer."
    kinds = [k for k, _ in emitted]
    assert "text" in kinds and "tool" in kinds and "tool_result" in kinds
    # The answer text is emitted exactly once (as the assistant block, not again
    # as a separate result event).
    assert [t for k, t in emitted if t == "Final answer."] == ["Final answer."]


@pytest.mark.asyncio
async def test_claude_falls_back_to_assistant_text_without_result() -> None:
    backend = ClaudeCodeBackend()
    events = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Partial thought."}]},
        },
    ]
    result, _ = await _drive(backend, events)
    assert result.final_text == "Partial thought."


@pytest.mark.asyncio
async def test_claude_partial_messages_stream_cumulative_text() -> None:
    # --include-partial-messages emits stream_event deltas; we accumulate them
    # into cumulative text under one merge id, and the complete assistant block
    # finalizes the same row (no duplicate). The frontend keeps the latest.
    backend = ClaudeCodeBackend()
    captured: list[tuple[str, str, str]] = []

    async def emit(kind, text, raw, meta=None):
        captured.append((kind, text, (meta or {}).get("merge_id", "")))

    result = ConsultResult()
    assistant_text: list[str] = []
    stream: dict = {"msg_id": "", "blocks": {}}
    events = [
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "msg_1"}}},
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
        },
        {
            "type": "assistant",
            "message": {"id": "msg_1", "content": [{"type": "text", "text": "Hello"}]},
        },
    ]
    for ev in events:
        await backend._handle_event(ev, result, assistant_text, stream, emit)

    texts = [(t, mid) for k, t, mid in captured if k == "text"]
    assert texts == [
        ("Hel", "txt:msg_1:0"),
        ("Hello", "txt:msg_1:0"),
        ("Hello", "txt:msg_1:0"),
    ]


@pytest.mark.asyncio
async def test_claude_result_without_assistant_text_is_surfaced() -> None:
    # Degenerate run: the answer arrives only in the result event (no assistant
    # text block streamed) — surface it so the user still sees an answer.
    backend = ClaudeCodeBackend()
    result, emitted = await _drive(
        backend, [{"type": "result", "subtype": "success", "result": "Only here."}]
    )
    assert result.final_text == "Only here."
    assert ("text", "Only here.") in emitted


# ---- Codex event parsing -----------------------------------------------------


@pytest.mark.asyncio
async def test_codex_event_parsing_thread_items_and_final() -> None:
    backend = CodexBackend()
    events = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "ls",
                "exit_code": 0,
                "output": "a\nb",
            },
        },
        {"type": "item.completed", "item": {"type": "agent_message", "text": "All done."}},
        {"type": "turn.completed", "usage": {}},
    ]
    result, emitted = await _drive(backend, events)
    assert result.session_id == "t1"
    assert result.final_text == "All done."
    kinds = [k for k, _ in emitted]
    # The answer renders as the terminal text of the run (not a separate result).
    assert "tool" in kinds and "tool_result" in kinds and "text" in kinds


@pytest.mark.asyncio
async def test_codex_web_search_start_and_finish_share_merge_id() -> None:
    # web_search streams a start placeholder then a filled finish; both carry
    # the SAME merge id so the UI collapses them into one evolving row (rather
    # than two lines, one empty). command_execution is unaffected (two rows).
    backend = CodexBackend()
    captured: list[tuple[str, str]] = []

    async def emit(kind, text, raw, meta=None):
        captured.append((text, (meta or {}).get("merge_id", "")))

    result = ConsultResult()
    for ev in (
        {"type": "item.started", "item": {"id": "ws_1", "type": "web_search", "query": ""}},
        {
            "type": "item.completed",
            "item": {"id": "ws_1", "type": "web_search", "query": "agentic RAG"},
        },
    ):
        await backend._handle_event(ev, result, emit)

    web = [(t, mid) for t, mid in captured if "web search" in t]
    assert [t for t, _ in web] == ["web search", "web search · agentic RAG"]
    assert {mid for _, mid in web} == {"ws_1"}  # both phases share the merge id


@pytest.mark.asyncio
async def test_codex_non_web_items_render_once_on_completion() -> None:
    # agent_message has no meaningful start line → renders once, on completion.
    backend = CodexBackend()
    events = [
        {"type": "item.started", "item": {"id": "m1", "type": "agent_message", "text": ""}},
        {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "done"}},
    ]
    result, emitted = await _drive(backend, events)
    assert [t for _k, t in emitted] == ["done"]


@pytest.mark.asyncio
async def test_codex_item_updated_streams_cumulative_answer() -> None:
    # "*.updated" frames carry the answer's growing text; we stream the running
    # text under the item id, and ".completed" finalizes the same merged row.
    backend = CodexBackend()
    captured: list[tuple[str, str, str]] = []

    async def emit(kind, text, raw, meta=None):
        captured.append((kind, text, (meta or {}).get("merge_id", "")))

    result = ConsultResult()
    events = [
        {"type": "item.started", "item": {"id": "m1", "type": "agent_message", "text": ""}},
        {"type": "item.updated", "item": {"id": "m1", "type": "agent_message", "text": "The ans"}},
        {
            "type": "item.updated",
            "item": {"id": "m1", "type": "agent_message", "text": "The answer"},
        },
        {
            "type": "item.completed",
            "item": {"id": "m1", "type": "agent_message", "text": "The answer is 42"},
        },
    ]
    for ev in events:
        await backend._handle_event(ev, result, emit)

    texts = [(t, mid) for k, t, mid in captured if k == "text"]
    assert texts == [
        ("The ans", "m1"),
        ("The answer", "m1"),
        ("The answer is 42", "m1"),
    ]
    assert result.final_text == "The answer is 42"


@pytest.mark.asyncio
async def test_codex_turn_failed_marks_error() -> None:
    backend = CodexBackend()
    result, emitted = await _drive(backend, [{"type": "turn.failed", "message": "boom"}])
    assert result.success is False and result.error == "boom"
    assert ("error", "boom") in emitted


# ---- streaming subprocess primitive ------------------------------------------


@pytest.mark.asyncio
async def test_stream_process_lines_interleaves_and_reports_exit() -> None:
    script = "import sys; print('out1'); print('err1', file=sys.stderr); print('out2')"
    seen: list[tuple[str, str]] = []
    async for channel, line in stream_process_lines([sys.executable, "-c", script]):
        seen.append((channel, line))
    assert ("stdout", "out1") in seen
    assert ("stdout", "out2") in seen
    assert ("stderr", "err1") in seen
    assert seen[-1] == ("exit", "0")


@pytest.mark.asyncio
async def test_stream_process_lines_reports_nonzero_exit() -> None:
    seen = [
        item
        async for item in stream_process_lines([sys.executable, "-c", "import sys; sys.exit(3)"])
    ]
    assert seen[-1] == ("exit", "3")


# ---- settings ----------------------------------------------------------------


def test_settings_from_dict_clamps_budget_and_reads_backends() -> None:
    s = settings_from_dict(
        {
            "consult_budget": 999,
            "backends": {"codex": {"sandbox": "read-only", "enabled": False}},
        }
    )
    assert s.consult_budget == CONSULT_BUDGET_MAX
    assert s.backend("codex").sandbox == "read-only"
    assert s.backend("codex").enabled is False
    # Unknown backend → defaults.
    assert s.backend("claude_code").permission_mode == BackendConfig().permission_mode


def test_settings_defaults() -> None:
    assert SubagentSettings().consult_budget == DEFAULT_CONSULT_BUDGET
    assert settings_from_dict({}).consult_budget == DEFAULT_CONSULT_BUDGET


# ---- image forwarding (materialization) --------------------------------------


def test_materialize_images_writes_only_resolvable_images(tmp_path) -> None:
    import base64 as _b64
    from pathlib import Path

    from deeptutor.core.context import Attachment
    from deeptutor.services.subagent.images import materialize_images

    atts = [
        Attachment(
            type="image", base64=_b64.b64encode(b"\x89PNGdata").decode(), mime_type="image/png"
        ),
        Attachment(
            type="image",
            base64="data:image/jpeg;base64," + _b64.b64encode(b"JPEGdata").decode(),
            filename="shot.jpg",
        ),
        Attachment(type="file", base64=_b64.b64encode(b"x").decode()),  # not an image
        Attachment(type="image", url="https://example.com/remote.png"),  # external, unresolvable
    ]
    paths = materialize_images(atts, tmp_path)

    assert len(paths) == 2  # the two inline images only
    assert paths[0].endswith(".png") and paths[1].endswith(".jpg")
    assert Path(paths[0]).read_bytes() == b"\x89PNGdata"
    assert Path(paths[1]).read_bytes() == b"JPEGdata"


# ---- Claude Code /model scraping (live model sync) ---------------------------

# A faithful render of the ``/model`` picker (as pyte produces it: real columns,
# a ❯ cursor, a ✔ on the active row, wrapped description continuation lines).
_CLAUDE_MODEL_SCREEN = """\
  Select model
  Switch between Claude models. Your pick becomes the default for new
  sessions. For other/previous model names, specify with --model.
    1. Default (recommended)  Opus 4.8 with 1M context · Best for everyday,
                              complex tasks
  ❯ 2. Opus ✔                 Opus 4.8 with 1M context · Best for everyday,
                              complex tasks
    3. Sonnet                 Sonnet 4.6 · Efficient for routine tasks
    4. Sonnet (1M context)    Sonnet 4.6 with 1M context · Draws from usage
                              credits · $3/$15 per Mtok
    5. Haiku                  Haiku 4.5 · Fastest for quick answers
    6. Fable (disabled)       Claude Fable 5 is currently unavailable. Learn
                              more: https://www.anthropic.com/news/fable
  ◉ xHigh effort ←/→ to adjust
  Enter to set as default · s to use this session only · Esc to cancel
"""


def test_parse_claude_model_screen() -> None:
    from deeptutor.services.subagent.claude_models import _parse_model_screen

    models = _parse_model_screen(_CLAUDE_MODEL_SCREEN)
    # Default (recommended) → CLI default (skipped); Fable (disabled) → skipped.
    # Sonnet's 1M variant maps to the [1m] alias.
    assert models == [
        {"slug": "opus", "display_name": "Opus 4.8 with 1M context"},
        {"slug": "sonnet", "display_name": "Sonnet 4.6"},
        {"slug": "sonnet[1m]", "display_name": "Sonnet 4.6 with 1M context"},
        {"slug": "haiku", "display_name": "Haiku 4.5"},
    ]


def test_claude_models_cache_roundtrip(monkeypatch, tmp_path) -> None:
    from deeptutor.services.subagent import claude_models as cm

    monkeypatch.setattr(cm, "_cache_path", lambda: tmp_path / "claude_models_cache.json")
    assert cm.load_cached_claude_models() == ([], "")

    cm._write_cache([{"slug": "opus", "display_name": "Opus 4.8"}], "2026-06-17T00:00:00Z")
    models, fetched = cm.load_cached_claude_models()
    assert models == [{"slug": "opus", "display_name": "Opus 4.8"}]
    assert fetched == "2026-06-17T00:00:00Z"


@pytest.mark.asyncio
async def test_claude_options_prefers_synced_cache(monkeypatch) -> None:
    """When a /model sync has cached a catalog, _claude_options uses it over the
    curated fallback."""
    from deeptutor.services.subagent import claude_models as cm
    from deeptutor.services.subagent import models as models_mod

    monkeypatch.setattr(
        cm,
        "load_cached_claude_models",
        lambda: ([{"slug": "opus", "display_name": "Opus 4.8 (synced)"}], "2026-06-17T00:00:00Z"),
    )

    async def fake_probe(cmd):
        return True, "claude x.y"

    monkeypatch.setattr(models_mod, "probe_version", fake_probe)

    opts = await models_mod._claude_options()
    assert [m.slug for m in opts.models] == ["opus"]
    assert opts.models[0].display_name == "Opus 4.8 (synced)"
    assert opts.synced_at == "2026-06-17T00:00:00Z"


# ---- persistent session registry (cross-turn continuity) ---------------------


def test_session_registry_roundtrip(monkeypatch, tmp_path) -> None:
    from deeptutor.services.subagent import sessions as sess

    monkeypatch.setattr(sess, "_path", lambda: tmp_path / "subagent_sessions.json")
    key = sess.session_key("chat1", "agentX")
    assert sess.get_session(key) is None

    sess.remember_session(key, "sid-9", kind="codex", cwd="/p")
    sess.remember_session("chat1::other", "sid-2")
    assert sess.get_session(key) == "sid-9"

    # Disconnecting agentX drops only its sessions.
    sess.forget_connection("agentX")
    assert sess.get_session(key) is None
    assert sess.get_session("chat1::other") == "sid-2"

    # Empty session id is a no-op (never persisted).
    sess.remember_session("chat1::agentZ", "")
    assert sess.get_session("chat1::agentZ") is None


# ---- backend options (models.py, the /settings sync source) ------------------


@pytest.mark.asyncio
async def test_list_backend_options_reads_codex_cache(monkeypatch, tmp_path) -> None:
    """Codex options come from the live models_cache.json + config.toml default;
    Claude Code falls back to its aliases and allows a free-text model."""
    import json

    from deeptutor.services.subagent import models as models_mod

    home = tmp_path / "codex"
    home.mkdir()
    (home / "models_cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-06-17T00:00:00Z",
                "models": [
                    {
                        "slug": "gpt-5.5",
                        "display_name": "GPT-5.5",
                        "default_reasoning_level": "medium",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (home / "config.toml").write_text('model = "gpt-5.5"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))

    async def fake_probe(cmd):  # never spawn a real CLI in tests
        return True, f"{cmd[0]} x.y"

    monkeypatch.setattr(models_mod, "probe_version", fake_probe)

    options = {o.kind: o for o in await models_mod.list_backend_options()}

    codex = options["codex"]
    assert codex.default_model == "gpt-5.5"
    assert codex.synced_at == "2026-06-17T00:00:00Z"
    assert codex.models[0].slug == "gpt-5.5"
    assert codex.models[0].default_effort == "medium"
    assert codex.models[0].efforts == ["low", "medium", "high"]

    claude = options["claude_code"]
    assert claude.allow_custom_model is True
    assert {m.slug for m in claude.models} >= {"opus", "sonnet", "haiku"}
    assert "high" in claude.efforts


@pytest.mark.asyncio
async def test_codex_options_tolerate_missing_cache(monkeypatch, tmp_path) -> None:
    """No models_cache.json → empty model list, still allows a custom model."""
    from deeptutor.services.subagent import models as models_mod

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex"))

    async def fake_probe(cmd):
        return False, "codex CLI not found on PATH"

    monkeypatch.setattr(models_mod, "probe_version", fake_probe)

    options = {o.kind: o for o in await models_mod.list_backend_options()}
    codex = options["codex"]
    assert codex.available is False
    assert codex.models == []
    assert codex.allow_custom_model is True


# ---- registry: partner backend is registered but not a local CLI -------------


def test_registry_partner_is_non_cli_backend() -> None:
    from deeptutor.services.subagent import PARTNER_BACKEND_KIND, get_backend, list_backend_kinds

    assert PARTNER_BACKEND_KIND in list_backend_kinds()
    backend = get_backend(PARTNER_BACKEND_KIND)
    assert backend is not None
    assert backend.local_cli is False
    assert get_backend("claude_code").local_cli is True


@pytest.mark.asyncio
async def test_detect_all_excludes_partner_backend() -> None:
    from deeptutor.services.subagent import detect_all

    kinds = {d.kind for d in await detect_all()}
    assert "partner" not in kinds
    assert kinds <= {"claude_code", "codex"}


# ---- partner backend: drive a partner as a subagent --------------------------


class _FakePartnerInstance:
    def __init__(self, running: bool = True) -> None:
        self.running = running


class _FakePartnerManager:
    """Stands in for the partner manager: records calls, scripts a reply/trace."""

    def __init__(
        self, *, exists: bool = True, running: bool = True, reply: str = "Hi from partner."
    ) -> None:
        self._exists = exists
        self._running = running
        self._reply = reply
        self.started: list[str] = []
        self.sent: list[dict] = []
        self._trace: list = []

    def script_trace(self, events: list) -> None:
        self._trace = events

    def partner_exists(self, pid: str) -> bool:
        return self._exists

    def get_partner(self, pid: str):
        return _FakePartnerInstance(self._running) if self._running else None

    async def start_partner(self, pid: str):
        self.started.append(pid)
        self._running = True
        return _FakePartnerInstance(True)

    async def send_message(self, pid, content, *, session_key, media=None, on_event=None):
        self.sent.append(
            {"pid": pid, "content": content, "session_key": session_key, "media": media or []}
        )
        if on_event is not None:
            for ev in self._trace:
                await on_event(ev)
        return self._reply


def _patch_manager(monkeypatch, manager) -> None:
    import deeptutor.services.partners as partners_pkg

    monkeypatch.setattr(partners_pkg, "get_partner_manager", lambda: manager)


@pytest.mark.asyncio
async def test_partner_consult_mints_session_key_and_returns_reply(monkeypatch) -> None:
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.services.subagent.partner import PartnerBackend

    manager = _FakePartnerManager(reply="The answer.")
    manager.script_trace(
        [
            StreamEvent(type=StreamEventType.THINKING, content="thinking…"),
            StreamEvent(
                type=StreamEventType.TOOL_CALL,
                content="web_search",
                metadata={"call_id": "c1", "args": {"q": "x"}},
            ),
            StreamEvent(
                type=StreamEventType.CONTENT, content="The answer.", metadata={"call_id": "c2"}
            ),
            StreamEvent(type=StreamEventType.DONE),  # bookkeeping → dropped
        ]
    )
    _patch_manager(monkeypatch, manager)

    emitted: list[tuple[str, str]] = []

    async def on_event(ev):
        emitted.append((ev.kind, ev.text))

    result = await PartnerBackend().consult("hello", on_event=on_event, partner_id="paul")

    assert result.success is True
    assert result.final_text == "The answer."
    # First consult mints a fresh, colon-free partner session key …
    assert result.session_id.startswith("dt-")
    # … and send_message used exactly that key.
    assert manager.sent[0]["session_key"] == result.session_id
    assert manager.sent[0]["pid"] == "paul"
    # The substantive trace is forwarded; the DONE marker is dropped.
    kinds = [k for k, _ in emitted]
    assert "reasoning" in kinds and "tool" in kinds and "text" in kinds
    assert result.event_count == 3


@pytest.mark.asyncio
async def test_partner_consult_resumes_given_session(monkeypatch) -> None:
    from deeptutor.services.subagent.partner import PartnerBackend

    manager = _FakePartnerManager()
    _patch_manager(monkeypatch, manager)

    async def on_event(ev):
        pass

    result = await PartnerBackend().consult(
        "again", on_event=on_event, partner_id="paul", session_id="dt-abc123"
    )
    # A remembered key is reused verbatim — the partner session continues.
    assert result.session_id == "dt-abc123"
    assert manager.sent[0]["session_key"] == "dt-abc123"


@pytest.mark.asyncio
async def test_partner_consult_starts_partner_when_idle(monkeypatch) -> None:
    from deeptutor.services.subagent.partner import PartnerBackend

    manager = _FakePartnerManager(running=False)
    _patch_manager(monkeypatch, manager)

    async def on_event(ev):
        pass

    await PartnerBackend().consult("q", on_event=on_event, partner_id="paul")
    assert manager.started == ["paul"]  # brought online before messaging


@pytest.mark.asyncio
async def test_partner_consult_requires_partner_id() -> None:
    from deeptutor.services.subagent.partner import PartnerBackend

    async def on_event(ev):
        pass

    result = await PartnerBackend().consult("q", on_event=on_event)
    assert result.success is False
    assert "partner" in result.error.lower()


@pytest.mark.asyncio
async def test_partner_consult_unknown_partner(monkeypatch) -> None:
    from deeptutor.services.subagent.partner import PartnerBackend

    manager = _FakePartnerManager(exists=False)
    _patch_manager(monkeypatch, manager)

    async def on_event(ev):
        pass

    result = await PartnerBackend().consult("q", on_event=on_event, partner_id="ghost")
    assert result.success is False
    assert manager.sent == []  # never messaged a non-existent partner


@pytest.mark.asyncio
async def test_partner_consult_empty_reply_is_unsuccessful(monkeypatch) -> None:
    from deeptutor.services.subagent.partner import PartnerBackend

    manager = _FakePartnerManager(reply="")
    _patch_manager(monkeypatch, manager)

    async def on_event(ev):
        pass

    result = await PartnerBackend().consult("q", on_event=on_event, partner_id="paul")
    assert result.success is False
    assert result.final_text == ""


def _partner_trace_state() -> dict[str, dict[str, str]]:
    return {"text": {}, "reason": {}, "pending_tools": {}}


def test_partner_event_mapping_covers_channels() -> None:
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.services.subagent.partner import _to_subagent_events

    def kinds(etype, **kw):
        return [
            e.kind
            for e in _to_subagent_events(StreamEvent(type=etype, **kw), _partner_trace_state())
        ]

    assert kinds(StreamEventType.CONTENT, content="hi") == ["text"]
    assert kinds(StreamEventType.THINKING, content="plan") == ["reasoning"]
    # A tool call without a call_id can't be paired -> emitted immediately.
    assert kinds(StreamEventType.TOOL_CALL, content="rag") == ["tool"]
    # A tool result with no buffered call -> just the result row.
    assert kinds(StreamEventType.TOOL_RESULT, content="rows") == ["tool_result"]
    assert kinds(StreamEventType.ERROR, content="boom") == ["error"]
    # Status / bookkeeping markers are dropped (the tool rows already carry the
    # substance - keeping the trace clean like the CLI backends).
    assert kinds(StreamEventType.PROGRESS, content="step 1") == []
    assert kinds(StreamEventType.RESULT, content="final") == []
    assert kinds(StreamEventType.DONE) == []
    # Only a truly-empty CONTENT delta is dropped; whitespace is preserved so
    # streamed spacing survives the accumulation.
    assert kinds(StreamEventType.CONTENT, content="") == []
    assert kinds(StreamEventType.CONTENT, content=" ") == ["text"]


def test_partner_tool_call_pairs_with_its_result_adjacently() -> None:
    # The loop dispatches tools in parallel - both TOOL_CALL events, then both
    # TOOL_RESULT events - sharing a call_id per tool. Each call is buffered and
    # re-emitted right before its own result, so the trace reads as adjacent
    # call -> result pairs (never two calls then two results).
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.services.subagent.partner import _to_subagent_events

    st = _partner_trace_state()
    a = _to_subagent_events(
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            content="partner_search",
            metadata={"call_id": "c1", "args": {"query": "Agentic RAG"}},
        ),
        st,
    )
    b = _to_subagent_events(
        StreamEvent(
            type=StreamEventType.TOOL_CALL,
            content="read_skill",
            metadata={"call_id": "c2", "args": {"name": "x"}},
        ),
        st,
    )
    assert a == [] and b == []  # both deferred until their results

    r1 = _to_subagent_events(
        StreamEvent(type=StreamEventType.TOOL_RESULT, content="hits", metadata={"call_id": "c1"}),
        st,
    )
    assert [e.kind for e in r1] == ["tool", "tool_result"]
    assert "partner_search" in r1[0].text and "Agentic RAG" in r1[0].text
    assert r1[1].text == "hits"

    r2 = _to_subagent_events(
        StreamEvent(type=StreamEventType.TOOL_RESULT, content="body", metadata={"call_id": "c2"}),
        st,
    )
    assert [e.kind for e in r2] == ["tool", "tool_result"]
    assert "read_skill" in r2[0].text
    # No shared merge_id - each call and result is its own row.
    assert not any(e.meta.get("merge_id") for e in r1 + r2)


def test_partner_content_accumulates_cumulatively() -> None:
    # Incremental CONTENT deltas accumulate into a growing full-text row under a
    # stable merge_id - so the streamed answer never gets wiped by a new chunk.
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.services.subagent.partner import _to_subagent_events

    st = _partner_trace_state()
    a = _to_subagent_events(
        StreamEvent(type=StreamEventType.CONTENT, content="The ", metadata={"call_id": "f1"}), st
    )
    b = _to_subagent_events(
        StreamEvent(type=StreamEventType.CONTENT, content="answer", metadata={"call_id": "f1"}), st
    )
    assert a[0].text == "The " and b[0].text == "The answer"
    assert a[0].meta["merge_id"] == b[0].meta["merge_id"] == "text:f1"
