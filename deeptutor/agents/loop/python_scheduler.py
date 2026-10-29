"""Reference scheduler for installs without Node; effects live in loop_host.

Keep this small control flow aligned with packages/chat-engine/src/core/run-loop.ts.
The existing behavior suite exercises both backends against the same adapters.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.capability_protocol import CapabilityPrerequisiteError
from deeptutor.services.llm import LLMProviderTransportError


async def run_loop(host: Any, config: dict[str, int]) -> dict[str, int]:
    state = dict(
        rounds=0,
        exploration_rounds=0,
        settlement_rounds=0,
        tool_steps=0,
        reasoning_budget_recoveries=0,
    )
    settlement_started = False
    empty_recoveries = 0
    finish_redirect_used = False
    recovery_used = False

    async def invoke(operation: str, **args: Any) -> Any:
        return await host.invoke(operation, args, dict(state))

    async def force_finish(reason: str = "budget", error: str = "") -> dict[str, int]:
        result = await invoke("forced_finish", reason=reason, error=error)
        state["rounds"] += result["extraRounds"]
        return state

    while True:
        settling = state["exploration_rounds"] >= config["explorationBudget"]
        if settling:
            if state["settlement_rounds"] >= config["settlementBudget"]:
                if recovery_used:
                    await invoke("reject_finish")
                    return state
                recovery = await invoke("prepare_recovery")
                if recovery["rejected"]:
                    await invoke("reject_finish")
                    return state
                if not recovery["available"]:
                    return await force_finish()
                recovery_used = True
            if not settlement_started:
                await invoke("begin_settlement")
                settlement_started = True
        try:
            result = await invoke("call_round", settling=settling, first=state["rounds"] == 0)
        except Exception as exc:
            if (
                isinstance(exc, CapabilityPrerequisiteError)
                or state["rounds"] == 0
                or (isinstance(exc, LLMProviderTransportError) and exc.partial_response)
            ):
                raise
            return await force_finish("error", str(exc))
        state["rounds"] += 1
        state["settlement_rounds" if settling else "exploration_rounds"] += 1
        if result.get("recoveryRejected"):
            await invoke("reject_finish")
            return state
        if not result["hasTools"]:
            if result["truncated"] or result["reasoningBudgetExhausted"]:
                if result["reasoningBudgetExhausted"]:
                    if state["reasoning_budget_recoveries"] >= 1:
                        await invoke("raise_reasoning_budget")
                    state["reasoning_budget_recoveries"] += 1
                await invoke("continue_truncated")
                continue
            if not result["hasText"]:
                empty_recoveries += 1
                force = empty_recoveries >= config["emptyRecoveryBudget"]
                await invoke("recover_empty", force=force)
                if force:
                    return await force_finish()
                continue
            decision = await invoke("check_finish")
            if decision["redirect"]:
                if finish_redirect_used:
                    await invoke("reject_finish")
                    return state
                finish_redirect_used = True
                await invoke("redirect_finish")
                continue
            await invoke("finish", override=decision["override"])
            return state

        dispatch = await invoke("dispatch_tools")
        state["tool_steps"] += 1
        if dispatch["pause"]:
            if await invoke("resolve_pause"):
                continue
            return state
        decision = await invoke("after_tools")
        if decision["override"]:
            await invoke("finish", override=True)
            return state
        if decision["terminate"]:
            await invoke("terminate")
            return state
