# -*- coding: utf-8 -*-
"""
ReAct Runner
=============

General-purpose ReAct loop that supports **parallel tool calls** per
round.  Designed for the memory agents but could be reused elsewhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agents.base_agent import BaseAgent

from .trace_tools import TOOL_NAMES, TraceToolkit

logger = logging.getLogger(__name__)


class ReActRunner:
    """Execute a ReAct loop on behalf of a memory agent.

    Each round the agent returns JSON with ``thought``, ``actions`` (a
    list of tool calls), and ``done`` (bool).  When ``done`` is true the
    loop terminates after executing the final actions.

    Parameters
    ----------
    agent:
        A :class:`BaseAgent` subclass used to call the LLM.
    toolkit:
        A :class:`TraceToolkit` instance whose tools are available to
        the agent.
    max_rounds:
        Safety cap on the number of think-act-observe iterations.
    log_dir:
        Directory to write per-run log files.  If ``None``, no log file
        is written.
    """

    def __init__(
        self,
        agent: BaseAgent,
        toolkit: TraceToolkit,
        max_rounds: int = 6,
        log_dir: Path | None = None,
    ) -> None:
        self._agent = agent
        self._toolkit = toolkit
        self._max_rounds = max(1, max_rounds)
        self._log_dir = log_dir

    async def run(
        self,
        system_prompt: str,
        initial_context: str,
    ) -> None:
        """Execute the full ReAct loop.

        The agent is expected to call ``write_document`` as part of its
        actions to persist its output.  This method does not return the
        written content explicitly — it is saved by the tool itself.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_context},
        ]

        log_entries: list[str] = []
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        agent_name = self._agent.agent_name

        _log_header(log_entries, agent_name, run_ts, system_prompt, initial_context)

        for round_num in range(1, self._max_rounds + 1):
            logger.info(
                "[ReAct] %s round %d/%d",
                agent_name, round_num, self._max_rounds,
            )

            response = await self._agent.call_llm(
                user_prompt="",
                system_prompt="",
                messages=messages,
                response_format={"type": "json_object"},
                verbose=False,
                stage=f"react_round_{round_num}",
            )

            parsed = _parse_react_json(response)
            thought = parsed.get("thought", "")
            actions = parsed.get("actions", [])
            done = parsed.get("done", False)

            logger.info(
                "[ReAct] %s thought: %s | actions: %d | done: %s",
                agent_name,
                thought[:120],
                len(actions),
                done,
            )

            _log_round(log_entries, round_num, thought, actions, response, done)

            messages.append({"role": "assistant", "content": response})

            if not actions:
                if done:
                    break
                messages.append({
                    "role": "user",
                    "content": "No actions provided. Please specify at least one action.",
                })
                log_entries.append("  (no actions — prompting agent to retry)\n")
                continue

            observations = await self._execute_actions(actions)
            obs_text = _format_observations(observations)

            _log_observations(log_entries, observations)

            if done:
                logger.info("[ReAct] %s finished after round %d", agent_name, round_num)
                break

            messages.append({"role": "user", "content": obs_text})

        else:
            logger.warning(
                "[ReAct] %s reached max_rounds (%d) without finishing",
                agent_name, self._max_rounds,
            )
            log_entries.append(
                f"\n!! REACHED MAX ROUNDS ({self._max_rounds}) WITHOUT FINISHING !!\n"
            )

        self._write_log(agent_name, run_ts, log_entries)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_actions(
        self,
        actions: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """Execute tool calls (in parallel) and return (tool, observation) pairs."""
        if not actions:
            return []

        async def _call_one(action: dict[str, Any]) -> tuple[str, str]:
            tool = str(action.get("tool", ""))
            params = action.get("input", {})
            if not isinstance(params, dict):
                params = {}
            if tool not in TOOL_NAMES:
                return tool, f"[error] Unknown tool: {tool}"
            obs = await self._toolkit.call(tool, params)
            return tool, obs

        results = await asyncio.gather(*[_call_one(a) for a in actions])
        return list(results)

    def _write_log(
        self,
        agent_name: str,
        run_ts: str,
        entries: list[str],
    ) -> None:
        """Append the full ReAct trace to the agent's persistent log file."""
        if self._log_dir is None:
            return
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{agent_name}.log"
            path = self._log_dir / filename
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(entries))
                f.write("\n\n")
            logger.info("[ReAct] Log appended → %s", path)
        except Exception as exc:
            logger.warning("[ReAct] Failed to write log file: %s", exc)


# ======================================================================
# Log formatting helpers
# ======================================================================


def _log_header(
    entries: list[str],
    agent_name: str,
    run_ts: str,
    system_prompt: str,
    initial_context: str,
) -> None:
    """Write the log header with system prompt and initial context."""
    entries.append(f"# {agent_name} — {run_ts}\n")
    entries.append("## System Prompt\n")
    entries.append(f"```\n{system_prompt}\n```\n")
    entries.append("## Initial Context\n")
    entries.append(f"```\n{initial_context}\n```\n")
    entries.append("---\n")


def _log_round(
    entries: list[str],
    round_num: int,
    thought: str,
    actions: list[dict[str, Any]],
    raw_response: str,
    done: bool,
) -> None:
    """Log one ReAct round: thought, actions requested, and raw LLM output."""
    entries.append(f"## Round {round_num}{' (final)' if done else ''}\n")
    entries.append(f"### Thought\n\n{thought}\n")
    if actions:
        entries.append("### Actions\n")
        for i, act in enumerate(actions, 1):
            tool = act.get("tool", "?")
            params = act.get("input", {})
            entries.append(f"**{i}. {tool}**")
            entries.append(f"```json\n{json.dumps(params, ensure_ascii=False, indent=2)}\n```\n")
    entries.append("### Raw LLM Response\n")
    entries.append(f"```json\n{raw_response}\n```\n")


def _log_observations(
    entries: list[str],
    observations: list[tuple[str, str]],
) -> None:
    """Log tool observations returned to the agent."""
    entries.append("### Observations\n")
    for tool, obs in observations:
        entries.append(f"**[{tool}]**\n")
        entries.append(f"```\n{obs}\n```\n")
    entries.append("---\n")


# ======================================================================
# Parsing helpers
# ======================================================================

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _normalize_text(text: str) -> str:
    """Strip BOM / NUL and normalize smart quotes."""
    text = text.lstrip("\ufeff\x00").strip()
    for lq, rq in [("\u201c", '"'), ("\u201d", '"'), ("\u2018", "'"), ("\u2019", "'")]:
        text = text.replace(lq, rq)
    return text


def _try_parse(candidate: str) -> dict[str, Any] | None:
    """Attempt JSON parse with trailing-comma cleanup."""
    for txt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
        try:
            data = json.loads(txt)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _repair_truncated(text: str) -> dict[str, Any] | None:
    """Try to recover a usable dict from JSON truncated by max_tokens.

    Strategy: close any open braces/brackets and re-parse. Then ensure the
    required keys exist so the ReAct loop can continue.
    """
    open_b = text.count("{") - text.count("}")
    open_s = text.count("[") - text.count("]")
    if open_b <= 0 and open_s <= 0:
        return None
    patched = text.rstrip(", \t\n")
    patched += "]" * max(open_s, 0)
    patched += "}" * max(open_b, 0)
    return _try_parse(patched)


def _parse_react_json(text: str) -> dict[str, Any]:
    """Best-effort parse of the agent's JSON response.

    Tries, in order:
      1. Direct parse (optionally from a ```json``` fenced block).
      2. Extract outermost ``{…}`` substring and parse.
      3. Repair truncated JSON by closing open braces/brackets.
      4. Fallback: treat entire text as thought, no actions, done=True.
    """
    text = _normalize_text(text)

    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group(1).strip()

    # --- strategy 1: direct parse ---
    result = _try_parse(text)
    if result is not None:
        return result

    # --- strategy 2: outermost { … } ---
    start = text.find("{")
    if start >= 0:
        end = text.rfind("}")
        if end > start:
            result = _try_parse(text[start : end + 1])
            if result is not None:
                return result

        # --- strategy 3: truncated JSON repair (from first '{' onward) ---
        result = _repair_truncated(text[start:])
        if result is not None:
            logger.debug("[ReAct] Recovered truncated JSON (%d open braces closed)", 
                         text[start:].count("{") - text[start:].count("}"))
            return result

    logger.warning("[ReAct] Failed to parse JSON response: %s", text[:200])
    return {"thought": text[:500], "actions": [], "done": True}


def _format_observations(results: list[tuple[str, str]]) -> str:
    """Format tool observations into a user message."""
    if not results:
        return "(no observations)"
    parts: list[str] = ["Observations:"]
    for tool, obs in results:
        header = f"[{tool}]"
        parts.append(f"{header}\n{obs}")
    return "\n\n".join(parts)
