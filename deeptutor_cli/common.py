"""Shared CLI helpers."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
import signal
import sys
from typing import Any, Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.status import Status
from rich.table import Table
from rich.text import Text

from deeptutor.app import DeepTutorApp, TurnRequest

from ._tool_result import ToolResultBuffer, ToolResultEntry

console = Console()

# Process-wide buffer that backs the ``/show`` REPL command. The buffer
# lives at module scope so a single ``deeptutor chat`` session shares one
# ring across turns; ``deeptutor run`` doesn't read it (single-shot mode),
# but populating it is harmless.
tool_results = ToolResultBuffer()

# Content call_kinds whose ``call_status: running`` marker drives the
# spinner instead of printing a progress line (one LLM round each).
_LLM_ROUND_CALL_KINDS = frozenset({"agent_loop_round", "llm_final_response"})


class TurnInterrupted(Exception):
    """User aborted the running turn (Ctrl-C / Ctrl-D at a prompt)."""


def parse_config_items(items: list[str]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for item in items:
        key, sep, raw_value = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"Invalid --config item `{item}`. Expected KEY=VALUE.")
        config[key.strip()] = _parse_scalar_value(raw_value.strip())
    return config


def parse_json_object(raw: str | None) -> dict[str, Any]:
    normalized = (raw or "").strip()
    if not normalized:
        return {}
    try:
        value = json.loads(normalized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid JSON config: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON config must be an object.")
    return value


def parse_notebook_references(items: list[str]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        notebook_id, _, record_part = item.partition(":")
        resolved_notebook_id = notebook_id.strip()
        if not resolved_notebook_id:
            raise ValueError(f"Invalid notebook reference `{item}`.")
        record_ids = [
            record_id.strip() for record_id in record_part.split(",") if record_id.strip()
        ]
        refs.append({"notebook_id": resolved_notebook_id, "record_ids": record_ids})
    return refs


async def run_turn_and_render(
    *,
    app: DeepTutorApp,
    request: TurnRequest,
    fmt: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    session, turn = await app.start_turn(request)

    if fmt == "json":
        await stream_turn_as_json(app=app, turn_id=turn["id"])
        return session, turn

    summary = await render_turn_stream(app=app, turn_id=turn["id"])
    console.print(
        f"[dim]session={session['id']} turn={turn['id']} "
        f"capability={request.capability}{summary}[/]",
        highlight=False,
    )
    return session, turn


async def regenerate_and_render(
    *,
    app: DeepTutorApp,
    session_id: str,
    capability: str = "chat",
    fmt: str = "rich",
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        session, turn = await app.regenerate_last_turn(session_id)
    except RuntimeError as exc:
        reason = str(exc)
        if reason == "regenerate_busy":
            console.print(
                "[yellow]Cannot regenerate while another turn is running. "
                "Wait for it to finish or cancel it first.[/]"
            )
        elif reason == "nothing_to_regenerate":
            console.print("[yellow]Nothing to regenerate yet — send a message first.[/]")
        else:
            console.print(f"[red]Regenerate failed:[/] {reason}")
        return None

    if fmt == "json":
        await stream_turn_as_json(app=app, turn_id=turn["id"])
        return session, turn

    summary = await render_turn_stream(app=app, turn_id=turn["id"])
    console.print(
        f"[dim]session={session['id']} turn={turn['id']} "
        f"capability={capability}{summary} (regenerated)[/]",
        highlight=False,
    )
    return session, turn


async def stream_turn_as_json(*, app: DeepTutorApp, turn_id: str) -> None:
    """NDJSON passthrough for ``--format json``.

    ``ask_user`` pauses are auto-resolved with an empty reply so headless
    runs cannot hang on a question no one will answer — the model sees
    "(empty reply)" as the tool result and must proceed on its own.
    """
    async for item in app.stream_turn(turn_id):
        # One event per line: rich wraps long lines at terminal width and
        # interprets ``[...]`` as markup, both of which corrupt NDJSON.
        console.print(
            json.dumps(item, ensure_ascii=False),
            soft_wrap=True,
            markup=False,
            highlight=False,
        )
        if _ask_user_payload(item) is not None:
            await app.submit_user_reply(turn_id, text="")


async def render_turn_stream(*, app: DeepTutorApp, turn_id: str) -> str:
    """Render a turn's event stream; returns a ``key=value`` summary suffix
    (rounds / tools / tokens / cost) for the caller's session line.

    Ctrl-C while the turn is streaming cancels the turn server-side and
    returns control to the caller (the REPL keeps running) instead of
    unwinding the whole CLI. While an ``ask_user`` prompt is on screen the
    default KeyboardInterrupt behaviour is restored so Ctrl-C aborts the
    prompt (and with it the turn).
    """
    task = asyncio.current_task()
    interrupted = False

    def _on_sigint() -> None:
        nonlocal interrupted
        if interrupted:
            return
        interrupted = True
        if task is not None:
            task.cancel()

    sigint = _SigintInterceptor(_on_sigint)
    renderer = TurnStreamRenderer(app=app, turn_id=turn_id, sigint=sigint)
    sigint.resume()
    try:
        async for item in app.stream_turn(turn_id):
            await renderer.handle(item)
    except TurnInterrupted:
        await _cancel_interrupted_turn(app=app, turn_id=turn_id, renderer=renderer)
    except asyncio.CancelledError:
        if not interrupted:
            renderer.close()
            raise
        # Our own SIGINT handler cancelled us; absorb the cancellation so
        # the REPL survives, then cancel the turn server-side. Drain the
        # whole cancel count — a hammered Ctrl-C must not leave a pending
        # cancellation that detonates at the next await.
        if task is not None:
            while task.cancelling() > 0:
                task.uncancel()
        await _cancel_interrupted_turn(app=app, turn_id=turn_id, renderer=renderer)
    finally:
        sigint.suspend()
        renderer.close()
    return renderer.summary_suffix()


async def _cancel_interrupted_turn(
    *,
    app: DeepTutorApp,
    turn_id: str,
    renderer: "TurnStreamRenderer",
) -> None:
    renderer.abort()
    with contextlib.suppress(Exception):
        await app.cancel_turn(turn_id)
    console.print("\n[dim]Interrupted — turn cancelled.[/]")


class _SigintInterceptor:
    """Route Ctrl-C to a callback while a turn is streaming (POSIX only).

    ``suspend``/``resume`` bracket blocking prompts so ``console.input``
    gets the default KeyboardInterrupt behaviour back (an installed
    asyncio handler never fires while the loop is blocked in a read).
    On platforms without ``add_signal_handler`` (Windows) this is a no-op
    and Ctrl-C falls through to ``maybe_run``'s graceful exit.
    """

    def __init__(self, on_sigint: Callable[[], None]) -> None:
        self._on_sigint = on_sigint
        self._installed = False

    def resume(self) -> None:
        if self._installed:
            return
        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGINT, self._on_sigint)
            self._installed = True
        except (NotImplementedError, RuntimeError, ValueError, AttributeError):
            self._installed = False

    def suspend(self) -> None:
        if not self._installed:
            return
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().remove_signal_handler(signal.SIGINT)
        self._installed = False


def _stdin_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _ask_user_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    """The ``ask_user`` question payload carried by a tool_result event."""
    if str(item.get("type", "")) != "tool_result":
        return None
    metadata = item.get("metadata") or {}
    tool_meta = metadata.get("tool_metadata")
    if not isinstance(tool_meta, dict):
        return None
    ask = tool_meta.get("ask_user")
    if isinstance(ask, dict) and ask.get("questions"):
        return ask
    return None


class TurnStreamRenderer:
    """State machine that renders one turn's event stream.

    The chat agent loop streams EVERY round's text as ``content`` chunks
    and only labels the round once it completes — a ``call_status`` marker
    whose ``call_role`` says whether that text was ``narration`` (preamble
    to tool calls; rendered dim, in place, before its tools) or the
    ``finish`` (the user-facing answer; rendered as Markdown). Chunks are
    therefore buffered per ``call_id`` and settled when the round's marker
    arrives — the marker is emitted before the round's tool calls
    dispatch, so terminal order matches the model's order.

    Content without that trace metadata (other capabilities) keeps the
    legacy behaviour: buffer and render at stage boundaries / done.
    """

    def __init__(
        self,
        *,
        app: DeepTutorApp,
        turn_id: str,
        sigint: _SigintInterceptor | None = None,
    ) -> None:
        self.app = app
        self.turn_id = turn_id
        self._sigint = sigint
        self._legacy_buf = ""
        self._round_bufs: dict[str, str] = {}
        self._round_order: list[str] = []
        self._thinking_bufs: dict[str, str] = {}
        self._thinking_indicated: set[str] = set()
        self._status: Status | None = None
        self._sources: list[dict[str, Any]] = []
        self._result_meta: dict[str, Any] = {}

    async def handle(self, item: dict[str, Any]) -> None:
        handler = getattr(self, f"_on_{str(item.get('type', ''))}", None)
        if handler is not None:
            await handler(item)

    # ---- lifecycle -------------------------------------------------------

    def abort(self) -> None:
        """Settle whatever already streamed (the backend persists the same
        partial text on cancel), then stop the spinner."""
        with contextlib.suppress(Exception):
            self._flush_pending()
        self._status_stop()

    def close(self) -> None:
        self._status_stop()

    def summary_suffix(self) -> str:
        meta = self._result_meta
        parts: list[str] = []
        rounds = meta.get("rounds")
        if isinstance(rounds, int) and rounds > 0:
            parts.append(f"rounds={rounds}")
        tool_steps = meta.get("tool_steps")
        if isinstance(tool_steps, int) and tool_steps > 0:
            parts.append(f"tools={tool_steps}")
        cost = (meta.get("metadata") or {}).get("cost_summary") or {}
        tokens = cost.get("total_tokens")
        if isinstance(tokens, (int, float)) and tokens > 0:
            parts.append(f"tokens={_format_tokens(int(tokens))}")
        cost_usd = cost.get("total_cost_usd")
        if isinstance(cost_usd, (int, float)) and cost_usd > 0:
            parts.append(f"cost=${cost_usd:.4f}")
        return (" " + " ".join(parts)) if parts else ""

    # ---- event handlers --------------------------------------------------

    async def _on_stage_start(self, item: dict[str, Any]) -> None:
        self._flush_pending()
        stage = str(item.get("stage", "") or "")
        if str(item.get("source", "")) == "chat" and stage == "responding":
            # The chat loop is one wrapper stage; a banner adds nothing.
            return
        self._status_stop()
        console.print(f"\n[bold cyan]▶ {stage or 'working'}[/]", highlight=False)

    async def _on_stage_end(self, item: dict[str, Any]) -> None:
        self._flush_pending()

    async def _on_thinking(self, item: dict[str, Any]) -> None:
        metadata = item.get("metadata") or {}
        call_id = str(metadata.get("call_id") or "")
        text = str(item.get("content", "") or "")
        if not call_id:
            # Legacy capabilities emit coarse-grained thinking lines.
            if text.strip():
                console.print(f"  [dim]{escape(text)}[/]", highlight=False)
            return
        # Chat-loop reasoning streams chunk-by-chunk: collapse it to one
        # indicator and stash the full text for ``/show`` at settle time.
        self._thinking_bufs[call_id] = self._thinking_bufs.get(call_id, "") + text
        if call_id not in self._thinking_indicated:
            self._thinking_indicated.add(call_id)
            if self._status is not None:
                self._status.update("[dim]thinking…[/]")
                console.print("  [dim]✻ thinking…[/]", highlight=False)
            else:
                console.print("  [dim]✻ thinking…[/]", highlight=False)

    async def _on_progress(self, item: dict[str, Any]) -> None:
        metadata = item.get("metadata") or {}
        content = str(item.get("content", "") or "")
        if metadata.get("trace_kind") == "call_status":
            await self._on_call_status(content, metadata)
            return
        if not content.strip():
            return
        console.print(f"  [dim]{escape(content)}[/]", highlight=False)

    async def _on_call_status(self, content: str, metadata: dict[str, Any]) -> None:
        call_state = str(metadata.get("call_state") or "")
        if call_state == "complete":
            call_role = str(metadata.get("call_role") or "")
            if call_role in {"narration", "finish"}:
                self._settle_round(str(metadata.get("call_id") or ""), role=call_role)
                return
            if content.strip():
                console.print(f"  [dim]{escape(content)}[/]", highlight=False)
            return
        if metadata.get("call_kind") in _LLM_ROUND_CALL_KINDS:
            # One LLM round starting — show liveness without a printed line.
            self._status_start(content.strip() or "working")
            return
        if content.strip():
            console.print(f"  [dim]{escape(content)}[/]", highlight=False)

    async def _on_content(self, item: dict[str, Any]) -> None:
        metadata = item.get("metadata") or {}
        text = str(item.get("content", "") or "")
        if not text:
            return
        call_id = str(metadata.get("call_id") or "")
        trace_kind = str(metadata.get("trace_kind") or "")
        if call_id and trace_kind == "llm_chunk":
            if call_id not in self._round_bufs:
                self._round_bufs[call_id] = ""
                self._round_order.append(call_id)
            self._round_bufs[call_id] += text
            if self._status is not None:
                self._status.update("[dim]writing…[/]")
            return
        if trace_kind == "llm_output":
            # Whole-text emission (terminator tool / section / fallback).
            # Flush buffered chunks first so blocks keep the model's order.
            self._flush_pending()
            self._status_stop()
            console.print(Markdown(text))
            return
        self._legacy_buf += text

    async def _on_tool_call(self, item: dict[str, Any]) -> None:
        _render_tool_call(item)

    async def _on_tool_result(self, item: dict[str, Any]) -> None:
        ask = _ask_user_payload(item)
        if ask is not None:
            await self._handle_ask_user(ask)
            return
        _render_tool_result(item)

    async def _on_error(self, item: dict[str, Any]) -> None:
        self._status_stop()
        console.print(f"[bold red]Error:[/] {escape(str(item.get('content', '') or ''))}")

    async def _on_sources(self, item: dict[str, Any]) -> None:
        entries = (item.get("metadata") or {}).get("sources")
        if isinstance(entries, list):
            self._sources.extend(entry for entry in entries if isinstance(entry, dict))

    async def _on_result(self, item: dict[str, Any]) -> None:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            self._result_meta = metadata

    async def _on_done(self, item: dict[str, Any]) -> None:
        self._flush_pending()
        self._status_stop()
        self._print_sources()

    async def _on_wait_for_input(self, item: dict[str, Any]) -> None:
        """Legacy in-band input request (``StreamBus.wait_for_input``)."""
        from deeptutor.core.stream_bus import get_bus

        self._status_stop()
        bus = get_bus(self.turn_id)
        if bus is None:
            return
        if not _stdin_interactive():
            bus.submit_input("")
            return
        prompt = str(item.get("content", "") or "").strip()
        if prompt:
            console.print(f"\n  [bold cyan]?[/] {escape(prompt)}", highlight=False)
        raw = self._read_line("  [bold green]answer>[/] ")
        if raw is None:
            raise TurnInterrupted
        bus.submit_input(raw)

    # ---- ask_user --------------------------------------------------------

    async def _handle_ask_user(self, ask: dict[str, Any]) -> None:
        self._status_stop()
        if not _stdin_interactive():
            console.print(
                "  [yellow]●[/] [dim]ask_user: stdin is not interactive — sending an "
                "empty reply so the turn can continue.[/]",
                highlight=False,
            )
            await self.app.submit_user_reply(self.turn_id, text="")
            return
        answers = self._prompt_ask_user(ask)
        if answers is None:
            raise TurnInterrupted
        await self.app.submit_user_reply(self.turn_id, answers=answers)

    def _prompt_ask_user(self, ask: dict[str, Any]) -> list[dict[str, str]] | None:
        """Render the question card and collect one answer per question.

        Returns ``None`` when the user aborts (Ctrl-C / Ctrl-D) — the
        caller cancels the turn, mirroring the web composer's stop button.
        """
        questions = [q for q in (ask.get("questions") or []) if isinstance(q, dict)]
        if not questions:
            return []
        console.print()
        console.print("[bold cyan]?[/] [bold]The model needs your input[/]", highlight=False)
        intro = str(ask.get("intro") or "").strip()
        if intro:
            console.print(f"  {escape(intro)}", highlight=False)
        answers: list[dict[str, str]] = []
        for index, question in enumerate(questions):
            reply = self._prompt_one_question(question, index=index, total=len(questions))
            if reply is None:
                return None
            answers.append(
                {"questionId": str(question.get("id") or f"q{index + 1}"), "text": reply}
            )
        return answers

    def _prompt_one_question(
        self,
        question: dict[str, Any],
        *,
        index: int,
        total: int,
    ) -> str | None:
        prompt = str(question.get("prompt") or "").strip()
        header = str(question.get("header") or "").strip()
        numbering = f"({index + 1}/{total}) " if total > 1 else ""
        chip = f"[cyan]{escape(header)}[/] " if header else ""
        console.print(f"\n  {numbering}{chip}{escape(prompt)}", highlight=False)
        labels: list[str] = []
        for option in question.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = str(option.get("label") or "").strip()
            if not label:
                continue
            labels.append(label)
            description = str(option.get("description") or "").strip()
            suffix = f" [dim]— {escape(description)}[/]" if description else ""
            console.print(f"    {len(labels)}. {escape(label)}{suffix}", highlight=False)
        multi = bool(question.get("multi_select"))
        hint = _answer_hint(
            has_options=bool(labels),
            multi=multi,
            placeholder=str(question.get("placeholder") or "").strip(),
        )
        raw = self._read_line(f"  [bold green]{hint}>[/] ")
        if raw is None:
            return None
        return _resolve_answer(raw, labels, multi)

    def _read_line(self, prompt: str) -> str | None:
        """Blocking prompt with default Ctrl-C semantics; ``None`` = abort."""
        if self._sigint is not None:
            self._sigint.suspend()
        try:
            return console.input(prompt)
        except (KeyboardInterrupt, EOFError):
            return None
        finally:
            if self._sigint is not None:
                self._sigint.resume()

    # ---- rendering internals ---------------------------------------------

    def _settle_round(self, call_id: str, *, role: str) -> None:
        """Render a completed chat-loop round's buffered text.

        ``narration`` stays dim and lands before the round's tool lines
        (the marker precedes tool dispatch); ``finish`` is the answer.
        """
        text = self._round_bufs.pop(call_id, "")
        if call_id in self._round_order:
            self._round_order.remove(call_id)
        thinking = self._thinking_bufs.pop(call_id, "").strip()
        if thinking:
            tool_results.remember("thinking", thinking)
        body = text.strip()
        if not body:
            return
        self._status_stop()
        if role == "narration":
            console.print(Text(body, style="dim"))
        else:
            console.print(Markdown(text))

    def _flush_pending(self) -> None:
        """Render any unsettled buffered text as answer Markdown.

        Chat rounds normally settle via their ``call_role`` marker; this is
        the stage-boundary / done / llm_output fallback so no text is ever
        dropped (and so other capabilities keep their old flush points).
        """
        for call_id in list(self._round_order):
            self._settle_round(call_id, role="finish")
        if self._legacy_buf:
            self._status_stop()
            console.print(Markdown(self._legacy_buf))
            self._legacy_buf = ""

    def _print_sources(self) -> None:
        if not self._sources:
            return
        seen: set[str] = set()
        rows: list[str] = []
        for source in self._sources:
            title = str(
                source.get("title")
                or source.get("filename")
                or source.get("file_name")
                or source.get("source")
                or source.get("url")
                or ""
            ).strip()
            location = str(source.get("url") or source.get("file_path") or "").strip()
            key = location or title
            if not key or key in seen:
                continue
            seen.add(key)
            row = title or location
            if location and location != row:
                row = f"{row} — {location}"
            rows.append(row)
        if not rows:
            return
        shown = rows[:8]
        console.print(f"[dim]sources ({len(rows)}):[/]", highlight=False)
        for index, row in enumerate(shown):
            console.print(f"  [dim][{index + 1}] {escape(row)}[/]", highlight=False)
        if len(rows) > len(shown):
            console.print(f"  [dim]… +{len(rows) - len(shown)} more[/]", highlight=False)

    def _status_start(self, label: str) -> None:
        if not console.is_terminal:
            return
        text = f"[dim]{escape(label)}[/]"
        if self._status is None:
            self._status = console.status(text, spinner="dots")
            self._status.start()
        else:
            self._status.update(text)

    def _status_stop(self) -> None:
        if self._status is not None:
            with contextlib.suppress(Exception):
                self._status.stop()
            self._status = None


def _answer_hint(*, has_options: bool, multi: bool, placeholder: str) -> str:
    if has_options and multi:
        return "answer (numbers/text, comma-separated; Enter to skip)"
    if has_options:
        return "answer (number or text; Enter to skip)"
    if placeholder:
        return f"answer ({escape(placeholder)}; Enter to skip)"
    return "answer (Enter to skip)"


def _resolve_answer(raw: str, labels: list[str], multi: bool) -> str:
    """Map ``1``-style selections onto option labels; pass text through.

    Multi-select accepts comma-separated tokens, each a number or free
    text; results join with ", " (the reply travels as one string).
    """
    cleaned = raw.strip()
    if not cleaned:
        return ""
    tokens = [t.strip() for t in cleaned.split(",") if t.strip()] if multi else [cleaned]
    resolved: list[str] = []
    for token in tokens:
        if token.isdigit() and labels and 1 <= int(token) <= len(labels):
            resolved.append(labels[int(token) - 1])
        else:
            resolved.append(token)
    return ", ".join(resolved)


def _format_tokens(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _render_tool_call(item: dict[str, Any]) -> None:
    """Print a one-line tool-call header. Long arg payloads are summarised
    so the call stays scannable; the full body lands in tool_result if the
    tool echoes it back, or in the stream metadata for debug tooling."""

    tool_name = str(item.get("content", "") or "tool")
    metadata = item.get("metadata", {}) or {}
    args = metadata.get("args", {})
    # Budget the args summary so the whole header — "  ● <name>(<args>)" —
    # fits the current terminal width on one line. We pick a soft floor so
    # very narrow terminals still get something useful.
    overhead = len(f"  ● {tool_name}()")
    budget = max(20, (console.width or 100) - overhead)
    summary = _summarize_call_args(args, max_len=budget)
    if summary:
        console.print(f"  [yellow]●[/] {tool_name}([dim]{escape(summary)}[/])", highlight=False)
    else:
        console.print(f"  [yellow]●[/] {tool_name}", highlight=False)


def _render_tool_result(item: dict[str, Any]) -> None:
    """Print a truncated preview of a tool result, stashing the full text
    in the shared :data:`tool_results` buffer so ``/show`` can expand it."""

    body = str(item.get("content", "") or "")
    metadata = item.get("metadata", {}) or {}
    label = str(metadata.get("tool") or "tool")
    entry = tool_results.remember(label, body)
    head, hidden = tool_results.truncate(body)

    # Empty result still gets a marker so the user can see the call closed.
    if not head.strip() and not hidden:
        console.print(
            f"  [green]└[/] [dim]#{entry.index} {label} → (empty result)[/]", highlight=False
        )
        return

    if head:
        for line in head.split("\n"):
            console.print(f"  [green]│[/] {escape(line)}", highlight=False)
    if hidden:
        console.print(
            f"  [green]└[/] [dim]#{entry.index} {label} — +{hidden} more line"
            f"{'s' if hidden != 1 else ''}; "
            f"run [bold]/show {entry.index}[/] (or [bold]/show last[/]) to expand[/]",
            highlight=False,
        )
    else:
        console.print(f"  [green]└[/] [dim]#{entry.index} {label}[/]", highlight=False)


def _summarize_call_args(args: Any, max_len: int = 120) -> str:
    """Render call args as a short ``key=value, …`` string.

    The full rendering is assembled first, then a single trailing-ellipsis
    clip is applied so we never leave a dangling ``", "`` at the end when
    the last key's value runs over the budget.
    """

    if isinstance(args, dict) and args:
        rendered = ", ".join(f"{key}={_one_line(value)}" for key, value in args.items())
    elif args:
        rendered = _one_line(args)
    else:
        return ""
    if len(rendered) > max_len:
        return rendered[: max_len - 1].rstrip(", ") + "…"
    return rendered


def _one_line(value: Any) -> str:
    """Compact one-line repr for a single arg value. No truncation here —
    the caller's overall budget handles that uniformly so we don't double-
    clip a dict and end up with a half-finished key=value pair."""

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = repr(value)
    return text.replace("\n", " ")


def render_tool_result_entry(entry: ToolResultEntry) -> None:
    """Fully print a stored tool result. Backs the ``/show`` REPL command."""

    from rich.panel import Panel

    console.print(
        Panel(
            escape(entry.body) if entry.body else "[dim](empty result)[/]",
            title=f"#{entry.index} {entry.label}",
            border_style="green",
        ),
        highlight=False,
    )


def build_turn_request(
    *,
    content: str,
    capability: str,
    session_id: str | None,
    tools: list[str],
    knowledge_bases: list[str],
    language: str,
    config_items: list[str],
    config_json: str | None,
    notebook_refs: list[str],
    history_refs: list[str],
) -> TurnRequest:
    config = parse_json_object(config_json)
    config.update(parse_config_items(config_items))
    return TurnRequest(
        content=content,
        capability=capability,
        session_id=session_id,
        tools=tools,
        knowledge_bases=knowledge_bases,
        language=language,
        config=config,
        notebook_references=parse_notebook_references(notebook_refs),
        history_references=[item.strip() for item in history_refs if item.strip()],
    )


def maybe_run(coro):  # noqa: ANN001
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/]")
        return None


def print_session_table(sessions: list[dict[str, Any]]) -> None:
    table = Table(title="Sessions")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Capability")
    table.add_column("Status")
    table.add_column("Messages", justify="right")
    for session in sessions:
        table.add_row(
            str(session.get("id", "")),
            str(session.get("title", "")),
            str(session.get("capability", "") or "chat"),
            str(session.get("status", "")),
            str(session.get("message_count", 0)),
        )
    console.print(table)


def print_notebook_table(notebooks: list[dict[str, Any]]) -> None:
    table = Table(title="Notebooks")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Records", justify="right")
    table.add_column("Description")
    for notebook in notebooks:
        table.add_row(
            str(notebook.get("id", "")),
            str(notebook.get("name", "")),
            str(notebook.get("record_count", 0)),
            str(notebook.get("description", "")),
        )
    console.print(table)


def print_path_result(path: str | Path) -> None:
    console.print(f"[dim]{Path(path).resolve()}[/]")


def _parse_scalar_value(raw_value: str) -> Any:
    lowered = raw_value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return raw_value
