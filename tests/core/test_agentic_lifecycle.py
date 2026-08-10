from deeptutor.core.agentic.labeled_step import LabeledStepResult, _lifecycle_error


def _result(status: str, *, text: str = "answer", tools: list[dict] | None = None) -> LabeledStepResult:
    return LabeledStepResult(
        label="FINISH", text=text, tool_calls=tools or [],
        termination={"provider_status": status, "incomplete_details": {"reason": "max_output_tokens"}},
        continuation_items=[{"type": "reasoning", "encrypted_content": "opaque"}],
    )


def test_lifecycle_completed_visible_output_is_normal() -> None:
    assert _lifecycle_error(_result("completed"), {"total_tokens": 3}) is None


def test_lifecycle_terminal_failures_are_typed_and_preserve_diagnostics() -> None:
    expected = {
        "incomplete": ("model_output_incomplete", True),
        "failed": ("model_provider_failed", False),
        "cancelled": ("model_provider_cancelled", False),
    }
    for status, (code, retryable) in expected.items():
        err = _lifecycle_error(_result(status, tools=[{"name": "never_dispatch"}]), {"total_tokens": 3})
        assert err is not None
        assert (err.code, err.retryable) == (code, retryable)
        assert err.normalized_result["tool_calls"] == [{"name": "never_dispatch"}]
        assert err.normalized_result["continuation_items"]


def test_lifecycle_empty_completed_is_typed_nonretryable() -> None:
    err = _lifecycle_error(_result("completed", text=""), {})
    assert err is not None
    assert (err.code, err.retryable) == ("model_output_empty", False)
