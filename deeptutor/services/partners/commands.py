"""Slash commands for partner chat surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
from typing import Any, Callable

from deeptutor.agents._shared.tool_composition import default_optional_tools
from deeptutor.multi_user.model_access import allowed_llm_options, apply_allowed_llm_selection
from deeptutor.multi_user.partner_access import can_manage_partner
from deeptutor.multi_user.paths import user_context
from deeptutor.partners.bus.events import InboundMessage
from deeptutor.services.config import get_model_catalog_service
from deeptutor.services.model_selection import apply_llm_selection_to_catalog, list_llm_options
from deeptutor.services.partners.sessions import PartnerSessionStore


@dataclass(frozen=True)
class PartnerCommandSpec:
    command: str
    description: str
    arg_hint: str = ""


@dataclass(frozen=True)
class PartnerCommandResult:
    content: str
    metadata: dict[str, Any] | None = None


BUILTIN_PARTNER_COMMANDS: tuple[PartnerCommandSpec, ...] = (
    PartnerCommandSpec("/help", "Show available partner commands."),
    PartnerCommandSpec("/new", "Archive this conversation and start a fresh one."),
    PartnerCommandSpec("/branch", "Archive this conversation and continue in a copy."),
    PartnerCommandSpec("/stop", "Stop the reply that's currently being generated."),
    PartnerCommandSpec("/sessions", "List this partner's conversations and their IDs."),
    PartnerCommandSpec("/resume", "Reopen an archived conversation.", "<session ID>"),
    PartnerCommandSpec("/delete", "Delete a conversation permanently.", "<session ID>"),
    PartnerCommandSpec("/status", "Show partner, session, model, and tool status."),
    PartnerCommandSpec("/model", "List or switch this partner's model.", "[number|model name]"),
    PartnerCommandSpec("/history", "Show recent messages in this conversation.", "[n]"),
    PartnerCommandSpec("/tool", "Show or change enabled tools.", "[on|off <name>|reset]"),
    PartnerCommandSpec(
        "/link",
        "Connect this chat account to your DeepTutor account.",
        "<code from the web app>",
    ),
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
        if command == "/model":
            return self._model(msg, args)
        if command == "/history":
            return self._history(msg, args)
        if command == "/tool":
            return self._tool(args)
        if command == "/link":
            return self._link(msg, args)
        return PartnerCommandResult(f"Unknown command: {parts[0]}\n\n{build_partner_help_text()}")

    def _link(self, msg: InboundMessage, args: list[str]) -> PartnerCommandResult:
        """Claim a link code, so this chat account speaks as its owner from now on."""
        from deeptutor.services.partners.interaction import actor_for_account
        from deeptutor.services.partners.links import redeem_link_code

        if msg.channel == "web":
            return PartnerCommandResult("You're already signed in here — nothing to link.")
        if (msg.metadata or {}).get("is_group"):
            return PartnerCommandResult(
                "Send /link in a direct message instead — group chats stay shared, "
                "and a code posted in one would be visible to everyone."
            )
        if not args:
            return PartnerCommandResult(
                "Usage: /link <code>. Open this partner in DeepTutor and choose "
                "“Link this chat account” to get a code."
            )
        user_id = redeem_link_code(
            self.partner_id, args[0], channel=msg.channel, sender_id=msg.sender_id
        )
        if not user_id:
            return PartnerCommandResult(
                "That code is not valid — it may have expired or already been used. "
                "Generate a fresh one in DeepTutor and try again."
            )
        actor = actor_for_account(user_id)
        if actor is None:
            return PartnerCommandResult("That code belongs to an account that no longer exists.")
        return PartnerCommandResult(
            f"Linked — I'll talk to you as {actor.username} from now on. "
            "This conversation is private to your account, and I can reach your "
            "library and notes here just like in the app."
        )

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

    def _model(self, msg: InboundMessage, args: list[str]) -> PartnerCommandResult:
        """List catalog models or persist a validated partner-level selection."""
        if (msg.metadata or {}).get("is_group") or (msg.metadata or {}).get("chat_type") == "group":
            return PartnerCommandResult(
                "Use /model in a linked direct message to manage this partner's model."
            )
        # Model names and profile wiring are part of partner configuration,
        # not the permissions granted to everyone who may chat with it.
        if msg.actor is None and msg.channel != "web":
            return PartnerCommandResult(
                "Link this chat to the partner owner or an admin with /link before managing models."
            )
        if not can_manage_partner(self.partner_id, msg.actor):
            return PartnerCommandResult("You cannot manage this partner's models.")

        try:
            catalog = get_model_catalog_service().load()
            all_options = list_llm_options(catalog)
            options = all_options["options"]
            if msg.actor is not None and not msg.actor.is_admin:
                with user_context(msg.actor):
                    allowed = {
                        (row["profile_id"], row["model_id"])
                        for row in allowed_llm_options()["options"]
                    }
                options = [
                    row for row in options if (row["profile_id"], row["model_id"]) in allowed
                ]
        except Exception as exc:
            return PartnerCommandResult(f"Could not list models: {exc}")

        configured_selection = getattr(self.config, "llm_selection", None)
        legacy_model = (
            str(getattr(self.config, "model", "") or "").strip() if not configured_selection else ""
        )
        active = configured_selection or all_options["active"] or {}
        if legacy_model:
            legacy_option = next((row for row in options if row["model"] == legacy_model), None)
            active = (
                {
                    "profile_id": legacy_option["profile_id"],
                    "model_id": legacy_option["model_id"],
                }
                if legacy_option
                else {}
            )
        current = next(
            (
                row
                for row in options
                if row["profile_id"] == active.get("profile_id")
                and row["model_id"] == active.get("model_id")
            ),
            None,
        )
        name_counts: dict[str, int] = {}
        for row in options:
            key = row["model_name"].casefold()
            name_counts[key] = name_counts.get(key, 0) + 1

        def option_label(row: dict[str, Any]) -> str:
            label = f"{row['provider_label']} · {row['model_name']}"
            if name_counts[row["model_name"].casefold()] > 1:
                label += f" ({row['model']})"
            return label

        if not args:
            if not options:
                return PartnerCommandResult("No chat models are configured for this account.")
            lines = ["Available models:"]
            for index, row in enumerate(options, 1):
                selected = " (current)" if row is current else ""
                lines.append(f"{index}. {option_label(row)}{selected}")
            lines.append("Use /model <number> or /model <wire model name> to switch.")
            providers: list[dict[str, str]] = []
            seen_profiles: set[str] = set()
            for row in options:
                profile_id = row["profile_id"]
                if profile_id in seen_profiles:
                    continue
                seen_profiles.add(profile_id)
                providers.append(
                    {
                        "profile_id": profile_id,
                        "provider_label": row["provider_label"],
                        "profile_name": row["profile_name"],
                    }
                )
            metadata = (
                {
                    "_feishu_model_options": options,
                    "_feishu_model_providers": providers,
                    "_feishu_model_current": active,
                }
                if msg.channel == "feishu" and (msg.metadata or {}).get("chat_type") == "p2p"
                else None
            )
            return PartnerCommandResult("\n".join(lines), metadata)

        choice: dict[str, Any] | None = None
        if len(args) == 1 and args[0].isdigit():
            index = int(args[0]) - 1
            if 0 <= index < len(options):
                choice = options[index]
        elif len(args) == 2:
            profile_options = [row for row in options if row["profile_id"] == args[0]]
            if msg.channel == "feishu" and (msg.metadata or {}).get("_feishu_model_picker_id"):
                # The callback selected a server-owned option by its stable ID.
                # Recheck that ID against today's visible catalog, since wire
                # names can occur more than once within one profile.
                choice = next((row for row in profile_options if row["model_id"] == args[1]), None)
            else:
                wire_matches = [row for row in profile_options if row["model"] == args[1]]
                if len(wire_matches) > 1:
                    return PartnerCommandResult(
                        "That wire model name is ambiguous. Use its /model number."
                    )
                if wire_matches:
                    choice = wire_matches[0]
                else:
                    choice = next(
                        (row for row in profile_options if row["model_id"] == args[1]), None
                    )
        if choice is None and not (len(args) == 1 and args[0].isdigit()):
            requested_name = " ".join(args)
            matches = [
                row for row in options if row["model"].casefold() == requested_name.casefold()
            ]
            if not matches:
                matches = [
                    row
                    for row in options
                    if row["model_name"].casefold() == requested_name.casefold()
                ]
            if len(matches) == 1:
                choice = matches[0]
            elif len(matches) > 1:
                return PartnerCommandResult(
                    "That model name is ambiguous. Use its /model number or wire model name."
                )
        if choice is None:
            return PartnerCommandResult("Unknown model. Use /model to see available numbers.")

        selection = {"profile_id": choice["profile_id"], "model_id": choice["model_id"]}
        try:
            apply_llm_selection_to_catalog(catalog, selection)
            if msg.actor is not None and not msg.actor.is_admin:
                with user_context(msg.actor):
                    apply_allowed_llm_selection(selection)
        except (PermissionError, ValueError) as exc:
            return PartnerCommandResult(str(exc))

        selected_label = option_label(choice)
        if selection == configured_selection and not legacy_model:
            return PartnerCommandResult(
                f"✅ Already using {selected_label}.", {"_feishu_model_switch_success": True}
            )
        previous_label = (
            legacy_model if legacy_model else option_label(current) if current else "default"
        )
        old_selection = getattr(self.config, "llm_selection", None)
        old_legacy_model = getattr(self.config, "model", None)
        self.config.llm_selection = selection
        self.config.model = None
        try:
            self._persist_config()
        except Exception as exc:
            self.config.llm_selection = old_selection
            self.config.model = old_legacy_model
            return PartnerCommandResult(f"Could not switch model: {exc}")
        return PartnerCommandResult(
            f"✅ Switched model: {previous_label} → {selected_label}.",
            {"_feishu_model_switch_success": True},
        )

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
