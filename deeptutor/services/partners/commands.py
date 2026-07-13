"""Slash commands for partner chat surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Any, Callable

from deeptutor.agents._shared.tool_composition import default_optional_tools
from deeptutor.partners.bus.events import InboundMessage
from deeptutor.services.partners.sessions import PartnerSessionStore


@dataclass(frozen=True)
class PartnerCommandSpec:
    command: str
    description: str
    arg_hint: str = ""


@dataclass(frozen=True)
class PartnerCommandResult:
    content: str


BUILTIN_PARTNER_COMMANDS: tuple[PartnerCommandSpec, ...] = (
    PartnerCommandSpec("/help", "Show available partner commands."),
    PartnerCommandSpec("/new", "Archive this conversation and start a fresh one."),
    PartnerCommandSpec("/branch", "Archive this conversation and continue in a copy."),
    PartnerCommandSpec("/stop", "Stop the reply that's currently being generated."),
    PartnerCommandSpec("/sessions", "List this partner's conversations and their IDs."),
    PartnerCommandSpec("/resume", "Reopen an archived conversation.", "<session ID>"),
    PartnerCommandSpec("/delete", "Delete a conversation permanently.", "<session ID>"),
    PartnerCommandSpec("/status", "Show partner, session, model, and tool status."),
    PartnerCommandSpec("/history", "Show recent messages in this conversation.", "[n]"),
    PartnerCommandSpec("/tool", "Show or change enabled tools.", "[on|off <name>|reset]"),
)


def partner_command_palette() -> list[dict[str, str]]:
    return [
        {
            "command": spec.command,
            "description": spec.description,
            "arg_hint": spec.arg_hint,
        }
        for spec in BUILTIN_PARTNER_COMMANDS
    ]


def build_partner_help_text() -> str:
    lines = ["Partner commands:"]
    for spec in BUILTIN_PARTNER_COMMANDS:
        command = f"{spec.command} {spec.arg_hint}".rstrip()
        lines.append(f"{command} - {spec.description}")
    lines.append("/clear - Alias for /new.")
    return "\n".join(lines)


def looks_like_partner_command(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) > 1 and stripped.startswith("/") and stripped[1].isalpha()


class PartnerCommandHandler:
    def __init__(
        self,
        *,
        partner_id: str,
        config: Any,
        store: PartnerSessionStore,
        save_config: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.partner_id = partner_id
        self.config = config
        self.store = store
        self.save_config = save_config

    def dispatch(self, msg: InboundMessage) -> PartnerCommandResult | None:
        raw = msg.content.strip()
        if not looks_like_partner_command(raw):
            return None
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            return PartnerCommandResult(f"Could not parse command: {exc}")
        if not parts:
            return None

        command = parts[0].lower().split("@", 1)[0]
        args = parts[1:]
        if command == "/help":
            return PartnerCommandResult(build_partner_help_text())
        if command in {"/new", "/clear"}:
            return self._new(msg)
        if command == "/branch":
            return self._branch(msg)
        if command == "/stop":
            return PartnerCommandResult("There's nothing being generated to stop.")
        if command == "/sessions":
            return self._sessions()
        if command == "/resume":
            return self._resume(args)
        if command == "/delete":
            return self._delete(args)
        if command == "/status":
            return self._status(msg)
        if command == "/history":
            return self._history(msg, args)
        if command == "/tool":
            return self._tool(args)
        return PartnerCommandResult(f"Unknown command: {parts[0]}\n\n{build_partner_help_text()}")

    def _new(self, msg: InboundMessage) -> PartnerCommandResult:
        archived = self.store.archive(msg.session_key)
        if archived:
            return PartnerCommandResult(
                "Started a new conversation.\n"
                f"Archived {archived['message_count']} message(s) as `{archived['session_key']}`."
            )
        return PartnerCommandResult("Started a new conversation. No prior messages to archive.")

    def _branch(self, msg: InboundMessage) -> PartnerCommandResult:
        # Branching to a *copy* needs a new session key, which only the web app
        # mints; on IM there is one session per chat, so degrade to /new.
        archived = self.store.archive(msg.session_key)
        if archived:
            return PartnerCommandResult(
                f"Archived this conversation as `{archived['session_key']}` and started fresh. "
                "To keep the full history in a new branch, use the web app."
            )
        return PartnerCommandResult("Nothing to branch yet.")

    def _sessions(self) -> PartnerCommandResult:
        sessions = self.store.list_sessions()
        if not sessions:
            return PartnerCommandResult("No conversations yet.")
        lines = ["Conversations:"]
        for session in sessions[:30]:
            flag = " (archived)" if session.get("archived") else ""
            title = str(session.get("title") or "").strip() or "(untitled)"
            lines.append(
                f"- `{session['session_key']}`{flag} — {title} · {session['message_count']} msg"
            )
        lines.append("\nUse /resume <session ID> or /delete <session ID>.")
        return PartnerCommandResult("\n".join(lines))

    def _resume(self, args: list[str]) -> PartnerCommandResult:
        if not args:
            return PartnerCommandResult("Usage: /resume <session ID>")
        key = args[0]
        self.store.set_archived(key, False)
        return PartnerCommandResult(
            f"Conversation `{key}` is active again. In the web app it reopens automatically."
        )

    def _delete(self, args: list[str]) -> PartnerCommandResult:
        if not args:
            return PartnerCommandResult("Usage: /delete <session ID>")
        key = args[0]
        removed = self.store.delete_session(key)
        return PartnerCommandResult(
            f"Deleted conversation `{key}`." if removed else f"No conversation `{key}` found."
        )

    def _status(self, msg: InboundMessage) -> PartnerCommandResult:
        selection = getattr(self.config, "llm_selection", None) or {}
        model = (
            (selection.get("model_id") if isinstance(selection, dict) else None)
            or getattr(self.config, "model", None)
            or "default"
        )
        tools = self._current_tools()
        messages = self.store.messages(msg.session_key, limit=10_000)
        lines = [
            "Partner status:",
            f"- Partner: {getattr(self.config, 'name', self.partner_id)} (`{self.partner_id}`)",
            f"- Channel: {msg.channel}",
            f"- Session: `{msg.session_key}`",
            f"- Model: `{model}`",
            f"- Messages in current conversation: {len(messages)}",
            f"- Tools: {', '.join(f'`{name}`' for name in tools) if tools else '(none)'}",
        ]
        return PartnerCommandResult("\n".join(lines))

    def _history(self, msg: InboundMessage, args: list[str]) -> PartnerCommandResult:
        count = 10
        if args:
            try:
                count = max(1, min(int(args[0]), 50))
            except ValueError:
                return PartnerCommandResult("Usage: /history [count]")
        records = self.store.messages(msg.session_key, limit=count)
        visible = [self._format_message(record) for record in records]
        visible = [line for line in visible if line]
        if not visible:
            return PartnerCommandResult("No conversation history yet.")
        return PartnerCommandResult(f"Last {len(visible)} message(s):\n" + "\n".join(visible))

    def _tool(self, args: list[str]) -> PartnerCommandResult:
        available = default_optional_tools()
        current = self._current_tools()
        if not args:
            return PartnerCommandResult(self._format_tools(current, available))

        action = args[0].lower()
        if action == "reset":
            setattr(self.config, "enabled_tools", None)
            self._persist_config()
            return PartnerCommandResult(self._format_tools(self._current_tools(), available))

        if action not in {"on", "off"} or len(args) < 2:
            return PartnerCommandResult("Usage: /tool [on|off <name>|reset]")

        name = args[1]
        if name not in available:
            return PartnerCommandResult(
                f"Unknown tool `{name}`.\nAvailable: {', '.join(f'`{tool}`' for tool in available)}"
            )

        next_tools = list(current)
        if action == "on" and name not in next_tools:
            next_tools.append(name)
        elif action == "off" and name in next_tools:
            next_tools.remove(name)
        setattr(self.config, "enabled_tools", next_tools)
        self._persist_config()
        return PartnerCommandResult(self._format_tools(next_tools, available))

    def _current_tools(self) -> list[str]:
        configured = getattr(self.config, "enabled_tools", None)
        if configured is None:
            return default_optional_tools()
        available = set(default_optional_tools())
        return [str(name) for name in configured if str(name) in available]

    def _persist_config(self) -> None:
        if self.save_config is not None:
            self.save_config(self.partner_id, self.config)

    @staticmethod
    def _format_message(record: dict[str, Any]) -> str:
        role = str(record.get("role") or "")
        if role not in {"user", "assistant"}:
            return ""
        content = str(record.get("content") or "").strip()
        if not content:
            return ""
        if len(content) > 200:
            content = content[:199] + "..."
        label = "You" if role == "user" else "Partner"
        return f"{label}: {content}"

    @staticmethod
    def _format_tools(current: list[str], available: list[str]) -> str:
        return "\n".join(
            [
                "Tools:",
                f"- Enabled: {', '.join(f'`{name}`' for name in current) if current else '(none)'}",
                f"- Available: {', '.join(f'`{name}`' for name in available) if available else '(none)'}",
            ]
        )


__all__ = [
    "PartnerCommandHandler",
    "PartnerCommandResult",
    "PartnerCommandSpec",
    "build_partner_help_text",
    "looks_like_partner_command",
    "partner_command_palette",
]
