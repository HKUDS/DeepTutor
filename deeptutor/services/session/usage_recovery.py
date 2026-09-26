"""Recover historical model attribution from recorded evidence, never current defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def model_evidence(
    events: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    model_turn = (metadata or {}).get("model_turn")
    route = model_turn.get("route") if isinstance(model_turn, dict) else {}
    if isinstance(route, dict) and route.get("model"):
        found.add((str(route.get("provider") or ""), str(route["model"])))
    for event in events:
        meta = event.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        # Tool/search model metadata is not the model that generated this reply.
        if meta.get("model") and (
            meta.get("call_kind") == "llm"
            or meta.get("trace_kind") in {"llm_call", "llm_output", "call_status"}
            or meta.get("event") == "llm_call"
        ):
            found.add((str(meta.get("provider") or ""), str(meta["model"])))
        payload = meta.get("metadata") or {}
        if isinstance(payload, dict):
            scopes = [payload]
            loop = payload.get("loop")
            if isinstance(loop, dict) and isinstance(loop.get("metadata"), dict):
                scopes.append(loop["metadata"])
            for scope in scopes:
                budget = scope.get("context_budget") or {}
                if isinstance(budget, dict) and budget.get("model"):
                    found.add(("", str(budget["model"])))
    return found


def recover_summary(
    summary: dict[str, Any], events: list[dict[str, Any]], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    if summary.get("call_details") or summary.get("model") or summary.get("by_model"):
        return summary
    evidence = model_evidence(events, metadata)
    models = {model for _, model in evidence}
    # A recorded output directory can retain the original per-model token report.
    # Only read this account's files, and only accept a report matching the summary.
    for event in events:
        meta = event.get("metadata") or {}
        payload = meta.get("metadata") if isinstance(meta, dict) else None
        output = payload.get("output_dir") if isinstance(payload, dict) else None
        if not isinstance(output, str):
            continue
        from deeptutor.multi_user.paths import get_current_path_service

        root = get_current_path_service().get_user_root().resolve()
        directory = Path(output).resolve()
        if not directory.is_relative_to(root):
            continue
        for filename in ("cost_report.json", "token_cost_summary.json"):
            path = (directory / filename).resolve()
            if not path.is_relative_to(root):
                continue
            try:
                data = json.loads(path.read_text())
                report = data.get("summary", data)
                by_model = report.get("by_model")
                if (
                    isinstance(by_model, dict)
                    and by_model
                    and int(report.get("total_tokens", -1)) == int(summary.get("total_tokens", 0))
                ):
                    return {
                        **summary,
                        "by_model": by_model,
                        "prompt_tokens": report.get(
                            "prompt_tokens",
                            report.get(
                                "total_prompt_tokens",
                                sum(v.get("prompt_tokens", 0) for v in by_model.values()),
                            ),
                        ),
                        "completion_tokens": report.get(
                            "completion_tokens",
                            report.get(
                                "total_completion_tokens",
                                sum(v.get("completion_tokens", 0) for v in by_model.values()),
                            ),
                        ),
                    }
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    if len(models) == 1:
        model = next(iter(models))
        providers = {provider for provider, _ in evidence if provider}
        return {
            **summary,
            "model": model,
            "provider": next(iter(providers)) if len(providers) == 1 else "",
        }
    return summary
