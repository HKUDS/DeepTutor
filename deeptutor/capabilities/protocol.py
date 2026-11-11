"""Protocol shared by the chat loop and its loop capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from deeptutor.core.context import UnifiedContext

# ── Legacy completion keys ──────────────────────────────────────────────────────────
#
# New capabilities use the typed ``interaction`` and ``capability_output``
# fields. These names remain for one-version compatibility with extensions that
# still publish completion values through serializable metadata.

#: Set truthy during ``on_user_resume`` to end the turn without another LLM
#: round — the capability owns the final message from that point on. The user's
#: reply still reaches the transcript; only feeding it back to the model stops.
END_LOOP = "end_loop"

#: The body to publish as ``agent_output`` on the turn's CAPABILITY_COMPLETE
#: event.
AGENT_OUTPUT = "agent_output"

#: A dict of extras to publish alongside it. Only this sub-dict is forwarded,
#: so a capability states exactly what may leave the turn.
EVENT_METADATA = "event_metadata"


@dataclass(frozen=True, slots=True)
class PromptBlock:
    """One named prompt fragment contributed to the loop system prompt."""

    name: str
    content: str


class LoopExtension(Protocol):
    """Optional per-turn extension point for the chat agent loop.

    A loop capability reuses the *full* chat tool surface — every built-in,
    with the user's composer toggles respected exactly as in plain chat — and
    adds its own :attr:`owned_tools` on top when active. It does not curate or
    suppress the reused surface: a solve / mastery turn sees the same built-ins
    a chat turn would, plus the capability's own tools.

    The exception is the *knowledge* category (:class:`KnowledgeCapability`),
    which sets :attr:`exclusive_tools` and replaces the surface instead of
    augmenting it. Plain capabilities leave the attribute absent (read with a
    ``getattr(cap, "exclusive_tools", False)`` default) so this default — and
    the augment-don't-suppress invariant above — stays true for them.

    Optional async ``pre_loop`` hook
    --------------------------------
    A capability MAY define::

        async def pre_loop(
            self, context, stream, *, usage=None
        ) -> PromptBlock | None: ...

    which the chat pipeline awaits **once, before the answer loop's first LLM
    call**, when the capability is active. Its returned block is folded into
    the loop's user-message seed (alongside the KB seed) so the answer loop
    treats it as grounding context for the turn. Use it for a bounded
    pre-pass that produces context the loop should have up front — e.g.
    :class:`~deeptutor.capabilities.explore_context.ExploreContextCapability`
    briefs the turn's attached sources objectively before the model answers.

    This hook is **optional** and not part of the required structural surface:
    the pipeline reads it with a ``getattr(cap, "pre_loop", None)`` default
    (mirroring :attr:`exclusive_tools`), so plain capabilities that omit it are
    unaffected. ``usage`` is the turn's token tracker, passed so a pre-pass can
    fold its own LLM cost into the turn total.

    Capabilities that own a durable user interaction MAY also define async
    ``on_user_pause(context, ask_user)`` and ``on_user_resume(context,
    ask_user, *, reply_text, answers)`` hooks.  The pipeline invokes them on
    the two sides of an ``ask_user`` wait so state can be committed before a
    disconnect or another LLM round.

    A capability whose tools can repoint the turn at a different target MAY
    declare those tool names as ``rebinding_tools: tuple[str, ...]`` (read with
    a ``getattr`` default, like ``pre_loop``). The dispatcher runs them before
    the round's other calls and re-binds those calls afterwards, so a switch
    and a write issued in the same round cannot land on different targets.

    A capability MAY also define ``finish_instruction(context, final_text)``.
    It is called after a tool-less LLM round and may return a short protocol
    instruction when that round must not finalize the turn. The answer loop
    gives the model one additional round with tools still mounted; capability
    implementations are responsible for keeping the check narrow and bounded.

    A capability MAY define ``settlement_recovery(context)`` returning
    ``(instruction, allowed_tool_names)`` when a successful preparation receipt
    leaves one required delivery action at the settlement limit. The loop uses
    its existing final slot for one restricted tool round instead of tool-less
    salvage. The hook must validate fresh state and must not initiate unrelated
    work; the loop enforces the tool allowlist before dispatch and never grants
    a second recovery round.

    A finish-guard capability whose private decision may share a round with a
    tool call MAY additionally define ``tool_round_output_policy(context,
    final_text, tool_names)`` (``"publish"`` / ``"discard"``) and
    ``final_text_override(context, final_text)``. These hooks let it preserve a
    previously accepted public answer while keeping protocol-only prose private.
    """

    name: str
    # Tools this capability registers and contributes when active (added on top
    # of chat's standard composition). Static — so the settings UI can group
    # them under their owning capability without a turn context.
    owned_tools: tuple[str, ...]

    def is_active(self, context: UnifiedContext) -> bool:
        """Whether this capability participates in the current turn."""

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        """Optional system prompt block contributed by the capability."""

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        """Inject server-owned private kwargs for this capability's tools."""

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        """Optional text appended to the initial user message seed."""


class KnowledgeCapability:
    """Base for capabilities bound to an agentic knowledge base.

    Unlike a plain :class:`LoopExtension` (which augments chat's full tool
    surface), a knowledge capability *owns the turn*: when active it replaces
    the surface with its own :attr:`owned_tools` plus the ``ask_user`` floor —
    no chat built-ins, no user composer toggles. Its retrieval/authoring is the
    model reasoning over the KB through these tools, not a fixed pipeline.

    The exclusivity is decided by **category membership**, not a per-instance
    knob: subclassing this sets :attr:`exclusive_tools`. Subclasses still
    satisfy :class:`LoopExtension` structurally (``name`` / ``owned_tools`` /
    ``is_active`` / ``system_block`` / ``augment_kwargs`` / ``pre_loop_seed``).
    """

    exclusive_tools: bool = True

    #: Chat built-ins that stay mounted alongside :attr:`owned_tools` when this
    #: capability owns the turn. Exclusivity is the capability's policy, so the
    #: exceptions are declared here rather than hardcoded in the pipeline
    #: (issue #2612, mirroring the KB coexistence of issue #650). Each name
    #: still passes its usual gate in
    #: :func:`~deeptutor.agents._shared.tool_composition.compose_enabled_tools`
    #: — the user's composer toggle (``web_search``), the always-on rule
    #: (``web_fetch``) — and the partner ``builtin_whitelist``. Default: none.
    coexisting_tools: tuple[str, ...] = ()

    def owned_kbs(self, context: UnifiedContext) -> set[str]:
        """Selected KB refs this capability consumes through its own tools.

        Returned refs are excluded from the ``rag`` surface so that co-selected
        KBs the capability does NOT own (e.g. plain LlamaIndex KBs alongside an
        Obsidian vault) stay reachable via ``rag`` instead of being silently
        dropped when the capability owns the turn (issue #650). Default: none.
        """
        _ = context
        return set()

    def coexisting_tools_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        mounted_tools: Iterable[str],
    ) -> PromptBlock | None:
        """System block naming the :attr:`coexisting_tools` that actually mounted.

        The pipeline calls this with the turn's composed tool list, so the
        mention can never advertise a tool that failed its gate (a
        ``web_search`` the user toggled off). Returns ``None`` when nothing
        declared mounted. Mounting without mentioning leaves the model
        assuming the turn has no web access (issue #2612), so the two halves
        are a pair. Copy is inline bilingual, like the subagent system block.
        """
        _ = context
        mounted = [
            str(name).strip()
            for name in self.coexisting_tools
            if str(name).strip() and str(name).strip() in set(mounted_tools)
        ]
        if not mounted:
            return None
        listed = ", ".join(f"`{name}`" for name in mounted)
        if str(language or "en").lower().startswith("zh"):
            content = (
                f"除本能力自己的工具外，本轮还保留了这些聊天工具：{listed}。"
                "当回答需要它们各自的用途时（例如一般主题搜索、读取用户给出的具体链接），照常使用。"
            )
        else:
            content = (
                f"Alongside this capability's own tools, these chat tools are "
                f"also mounted this turn: {listed}. Use them as usual when the "
                "answer calls for what they each do (e.g. a general topic "
                "search, or reading a specific URL the user shared)."
            )
        return PromptBlock(f"{self.name}_coexisting_tools", content)


__all__ = [
    "AGENT_OUTPUT",
    "END_LOOP",
    "EVENT_METADATA",
    "KnowledgeCapability",
    "LoopExtension",
    "PromptBlock",
]


def __getattr__(name: str):
    if name == "LoopCapability":
        import warnings

        warnings.warn(
            "LoopCapability is deprecated; use LoopExtension. It will be removed in v3.",
            DeprecationWarning,
            stacklevel=2,
        )
        return LoopExtension
    raise AttributeError(name)
