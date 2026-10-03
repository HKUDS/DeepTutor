# PR: fix(llm): warn when CodeBuddy tool-call interrupt or drain fails

## Summary

- When a CodeBuddy response carries tool calls, `deeptutor/services/llm/provider_core/codebuddy_provider.py` interrupts the in-flight SDK generation (`interrupt()`) and drains the remaining messages. Both steps were wrapped in a bare `except Exception: pass`, so a failed interrupt (e.g. the CLI pipe already closed) left the SDK generating in the background — silently consuming quota with no log trail.
- This PR logs a warning for both interrupt and drain failures (exception type + a 200-char-truncated reason; no prompts or credentials) and only drains after a successful interrupt, preserving the original short-circuit semantics and the `finish_reason="tool_calls"` return value.
- Adds a regression test that mocks a raising `interrupt()` and asserts the warning while the tool-call response still returns normally.

## Root cause

In `_consume_messages`, the `await interrupt(); await _drain_interrupted_response(...)` sequence after receiving tool calls was wrapped in a silent `except Exception: pass`. When the SDK's `interrupt()` raised (for example the CLI pipe was already closed), the exception was swallowed: the background generation kept running and kept consuming quota, with nothing in the logs to explain the drain. `_drain_interrupted_response` had its own silent `except Exception: return`, hiding drain failures that can let stale SDK messages surface in the next turn.

## Changes

- `deeptutor/services/llm/provider_core/codebuddy_provider.py` (+26/−4):
  - Add a module-level stdlib logger and `_short_exception()` (exception type + reason truncated to 200 chars — never prompt bodies or credentials).
  - `_consume_messages`: a failed `interrupt()` now logs a warning ("background generation may keep running"); draining happens only after a successful interrupt (`else` clause), matching the original short-circuit behavior. The returned `LLMResponse` keeps `finish_reason="tool_calls"` and the collected tool calls.
  - `_drain_interrupted_response`: drain failures log a warning ("stale SDK messages may surface in the next turn") instead of returning silently.
- `tests/services/llm/test_codebuddy_provider.py` (+91): new test `test_codebuddy_interrupt_failure_after_tool_calls_logs_warning` — a FakeClient whose `interrupt()` raises `RuntimeError`; asserts via `caplog` that a warning from `deeptutor.services.llm.provider_core.codebuddy_provider` naming `RuntimeError` is emitted, that `interrupt()` was called exactly once, and that the response still returns `finish_reason="tool_calls"` with the tool call attached.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/llm/test_codebuddy_provider.py -q` → **11 passed** (10 pre-existing + 1 new)
- `python -m pytest tests/services/llm/test_codebuddy_http_provider.py -q` → **9 passed** (sibling HTTP provider, unaffected)
- `python -m pytest tests/services/llm/ -q` → **469 passed, 0 failed** (full LLM subsystem, no cross-test pollution)
- Red-green check (from the original development run): with the product-code change reverted, the new test fails (1 failed, 10 passed), confirming it pins the fix.
- `ruff check deeptutor/services/llm/provider_core/codebuddy_provider.py tests/services/llm/test_codebuddy_provider.py` → All checks passed

## Related issue

None — found during an internal error-handling audit of silent `except: pass` sites in the LLM provider layer. Related to the CodeBuddy provider introduced in #780.
