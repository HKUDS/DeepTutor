"""Contract tests for the shared once-per-stream usage recorder.

``record_streamed_usage`` is the single seam used by ``run_labeled_step``,
chat's ``_call_llm``, and the question pipeline's tool summarizer after
PR #617 unified their triplicated post-stream accounting.
"""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.core.agentic.usage import (
    UsageTracker,
    message_content_chars,
    record_streamed_usage,
)


def _frame(prompt: int, completion: int) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def test_records_frame_exactly_once() -> None:
    tracker = UsageTracker()
    record_streamed_usage(tracker, _frame(100, 20), input_chars=9999, output_chars=9999)

    assert tracker.calls == 1
    assert tracker.prompt_tokens == 100
    assert tracker.completion_tokens == 20


def test_falls_back_to_estimate_without_frame() -> None:
    tracker = UsageTracker()
    record_streamed_usage(tracker, None, input_chars=35, output_chars=70)

    assert tracker.calls == 1
    assert tracker.prompt_tokens == 10  # 35 / 3.5
    assert tracker.completion_tokens == 20


def test_zero_chars_skip_the_fallback() -> None:
    tracker = UsageTracker()
    record_streamed_usage(tracker, None)

    assert tracker.calls == 0


def test_none_tracker_is_a_noop() -> None:
    record_streamed_usage(None, _frame(1, 1))  # must not raise


def test_accounting_errors_never_propagate() -> None:
    tracker = UsageTracker()
    malformed = SimpleNamespace(prompt_tokens="not-a-number", completion_tokens=None)

    record_streamed_usage(tracker, malformed, input_chars=10, output_chars=10)  # must not raise

    assert tracker.calls == 0


def test_message_content_chars_handles_all_shapes() -> None:
    assert message_content_chars({"content": "hello"}) == 5
    assert message_content_chars({"content": None}) == 0
    assert (
        message_content_chars(
            {"content": [{"type": "text", "text": "ab"}, "cd", {"type": "image_url"}]}
        )
        == 4
    )
    assert message_content_chars({"content": 1234}) == 4  # len(str(content))
