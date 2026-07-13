"""Tests for the Deep Solve loop capability: capability hooks, owned tools, session."""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.solve import SOLVE_TOOL_NAMES, SolveLoopCapability
from deeptutor.capabilities.solve.session import SolveSession, get_session
from deeptutor.capabilities.solve.tools import (
    SolveFinishStepTool,
    SolvePlanTool,
    SolveReplanTool,
)
from deeptutor.core.context import UnifiedContext


def _solve_context(session_id: str = "t1") -> UnifiedContext:
    return UnifiedContext(
        user_message="solve it",
        metadata={"solve_mode": True, "solve_session_id": session_id},
    )


# ---- capability hooks ---------------------------------------------------------


def test_plugin_inactive_outside_solve_mode() -> None:
    plugin = SolveLoopCapability()
    ctx = UnifiedContext(user_message="hi")
    assert plugin.is_active(ctx) is False
    assert plugin.system_block(ctx, language="en", prompts={}) is None


def test_plugin_declares_owned_tools_and_playbook() -> None:
    plugin = SolveLoopCapability()
    ctx = _solve_context()
    assert plugin.is_active(ctx) is True
    # The plugin contributes only its own tools; it reuses chat's full built-in
    # surface (no curated builtin list).
    assert tuple(plugin.owned_tools) == SOLVE_TOOL_NAMES
    block = plugin.system_block(ctx, language="en", prompts={})
    assert block is not None and "solve_plan" in block.content


def test_plugin_augments_session_id_only_for_solve_tools() -> None:
    plugin = SolveLoopCapability()
    ctx = _solve_context("turn-9")
    assert plugin.augment_kwargs("solve_plan", {}, ctx)["_solve_session_id"] == "turn-9"
    # A reused built-in is left untouched (no private kwarg leak).
    assert "_solve_session_id" not in plugin.augment_kwargs("rag", {}, ctx)


# ---- owned tools ----------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_then_finish_steps_advances_and_folds() -> None:
    sid = "test-plan-1"
    plan = await SolvePlanTool().execute(
        _solve_session_id=sid,
        analysis="factor it",
        steps=[{"goal": "factor"}, {"goal": "solve roots"}],
    )
    assert plan.success
    payload = json.loads(plan.content)
    assert payload["status"] == "planned"
    assert payload["next"]["id"] == "S1"
    assert [s["id"] for s in payload["steps"]] == ["S1", "S2"]

    fin = await SolveFinishStepTool().execute(
        _solve_session_id=sid, step_id="S1", summary="x^2-4=(x-2)(x+2)"
    )
    assert fin.success
    # The checkpoint summary is what the loop folds the step's chatter into.
    assert "S1" in fin.metadata["_context_checkpoint"]["summary"]
    fp = json.loads(fin.content)
    assert fp["next"]["id"] == "S2"
    assert fp["all_done"] is False

    fin2 = await SolveFinishStepTool().execute(_solve_session_id=sid, step_id="S2", summary="x=±2")
    fp2 = json.loads(fin2.content)
    assert fp2["next"] is None
    assert fp2["all_done"] is True


@pytest.mark.asyncio
async def test_finish_unknown_step_is_rejected() -> None:
    sid = "test-plan-2"
    await SolvePlanTool().execute(_solve_session_id=sid, analysis="a", steps=[{"goal": "g1"}])
    res = await SolveFinishStepTool().execute(_solve_session_id=sid, step_id="S99", summary="x")
    assert res.success is False


@pytest.mark.asyncio
async def test_replan_is_budget_limited() -> None:
    sid = "test-replan-1"
    await SolvePlanTool().execute(_solve_session_id=sid, analysis="a", steps=[{"goal": "g1"}])
    get_session(sid).max_replans = 1

    ok = await SolveReplanTool().execute(
        _solve_session_id=sid, reason="wrong", steps=[{"goal": "g2"}]
    )
    assert ok.success is True
    refused = await SolveReplanTool().execute(
        _solve_session_id=sid, reason="again", steps=[{"goal": "g3"}]
    )
    assert refused.success is False
    assert "budget_exhausted" in refused.content


@pytest.mark.asyncio
async def test_tools_require_a_session_id() -> None:
    res = await SolvePlanTool().execute(analysis="a", steps=[{"goal": "g"}])
    assert res.success is False


# ---- session --------------------------------------------------------------


def test_session_replan_resets_steps_and_counts() -> None:
    session = SolveSession(session_id="x", max_replans=2)
    session.set_plan("a", [("S1", "g1")])
    assert session.replan("redo", [("S1", "g2")]) is True
    assert session.replans == 1
    assert session.next_step().goal == "g2"
    assert session.all_done() is False
