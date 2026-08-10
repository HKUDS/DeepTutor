# Deep Research Protocol Fidelity and Recovery Design

**Status:** Approved design direction; awaiting approval of this committed document
**Baseline:** `deep-research-recovery-v1`

## 1. Problem Statement

A Deep Research session selected an explicit OpenAI Responses profile for
`gpt-5.6-sol` with `xhigh` reasoning, but completed in about 13 seconds with a
report containing only its Markdown title. The session recorded eleven model
calls, 4,838 prompt tokens, zero completion tokens, one failed research block,
and still surfaced a successful terminal state.

The failure has two independent causes:

1. The shared agentic client reduces the request-scoped `LLMConfig` to an
   `LLMClientConfig` that omits `api_protocol`, `strict_protocol`, provider
   identity, and the effective URL. An explicit `openai_responses` selection
   consequently creates a plain `AsyncOpenAI` Chat Completions client.
2. Deep Research treats empty planning, zero completed blocks, and a title-only
   report as recoverable partial output, then the session orchestrator marks the
   turn completed because the pipeline did not raise an error.

This is not a model-specific text-format problem. A controlled call through the
repository's existing `UnifiedLLMAdapter`, using the same model, reasoning
effort, research prompt, and tool schema, returned a valid labeled response.
A two-turn function-call continuation also completed normally.

OpenAI Responses still requires lifecycle-aware handling: output is a list of
typed items; `incomplete`, `failed`, and `cancelled` are not successful answers;
and a reasoning model can exhaust `max_output_tokens` before producing visible
text. See the official [Responses API reference](https://platform.openai.com/docs/api-reference/responses)
and [reasoning token guidance](https://developers.openai.com/api/docs/guides/reasoning#allocating-space-for-reasoning).

## 2. Goals

- Honor the exact LLM profile, model, protocol, and strictness selected for an
  agentic turn.
- Normalize Responses lifecycle and termination data without special-casing a
  model name.
- Never report a zero-evidence or title-only research result as complete.
- Show a useful failure reason and select a retry strategy from that reason.
- Preserve successful research work and previous attempt history across retries.
- Cover every current consumer of the shared agentic client: Chat, Question,
  Explore Context, and Deep Research.
- Deploy an immutable fork revision without replacing the persistent data volume.

## 3. Non-Goals

- Silently switching models, reasoning effort, providers, or wire protocols.
- Rewriting the entire agentic engine around a new event API.
- Treating reasoning summaries or encrypted reasoning payloads as final answers.
- Retrofitting old completed session records in place. Retrying an old session
  creates a new linked attempt.
- Adding a new page or redesigning the research workspace.

## 4. Approved User-Story Baseline

**Revision:** `deep-research-recovery-v1`
**Approval evidence:** the user replied `确认` immediately after this baseline
was presented in the current task. The Chinese text below is the authoritative,
unchanged approved baseline; later architectural constraints do not rewrite it.

<!-- baseline:start -->
### DRR-01: 协议一致性

**Given** 用户选择显式 `openai_responses` profile，**When** 任意 agentic
流程调用模型，**Then** 必须走 Responses 接口；不得静默切换 Chat
Completions、Anthropic 或其他模型。

### DRR-02: 返回状态处理

Responses 的 `completed`、`incomplete`、`failed`、`cancelled`、
`incomplete_details`、可见文本、工具调用和 token 使用量必须被完整解析。
推理内容不能冒充最终答案。

### DRR-03: 结果判定

全部研究块成功且报告有实质正文才显示绿色“完成”；至少一个块成功则显示
琥珀色“部分完成”；0 块成功或只有标题则显示红色“研究失败”。

### DRR-04: 失败原因

页面显示可读原因，并可展开查看模型、profile、协议、失败阶段、终止状态、
token、调用次数等诊断信息，但不暴露密钥。

### DRR-05: 针对性重试

网络/限流采用有界退避；token 不足提高预算重试一次；工具失败只重试失败块；
报告失败只重写报告；协议/配置错误不盲目循环。所有重试保留原尝试记录。

### DRR-06: 部署验收

修复提交并推送到 fork，从精确 commit 构建部署，保留现有数据卷；真实
`gpt-5.6-sol/xhigh` 完成 Deep Research E2E，并保留旧镜像回滚能力。
<!-- baseline:end -->

**Canonical baseline content ID (`git hash-object --stdin`):**
`6a8d5828f90f80a02382a7869cc7c17ec71bf349`

Approach B additionally requires Chat Completions and Anthropic Messages
regression coverage because they share the changed client factory. That is an
implementation boundary and regression constraint, not an expansion of DRR-01.

## 5. Approach Decision

Three approaches were considered:

1. Patch only the Deep Research pipeline. This is small, but leaves the same
   protocol-loss defect in Chat, Question, and Explore Context.
2. Make the shared agentic client protocol-aware, then add research-specific
   outcome and retry semantics. This fixes the ownership boundary while keeping
   the current agentic APIs. **Selected.**
3. Rewrite all agentic consumers to use native unified response events. This is
   architecturally clean but has an unnecessarily large migration and regression
   surface for this incident.

## 6. Model Routing Design

### 6.1 Preserve the resolved selection

`LLMClientConfig` will carry the fields needed to reproduce a request-scoped
selection:

- binding, provider name, and provider mode;
- model and reasoning effort;
- base URL and effective URL;
- API version and extra headers;
- requested and resolved API protocol;
- strict-protocol flag.

A `from_llm_config()` constructor will be the single conversion used by all
agentic pipelines. The client pool key will include provider identity, effective
URL, protocol, strictness, model, headers, and credential fingerprint so clients
from incompatible wire contracts cannot be reused. Reasoning effort remains a
per-request generation parameter and does not create another transport pool.

### 6.2 Route explicit protocols through the unified provider

For an explicit protocol, `build_openai_client()` will obtain the existing
services-layer runtime provider and expose it through the existing OpenAI-style
agentic facade. This keeps `run_labeled_step()` and the loop host contracts
stable while ensuring the provider sends the selected wire format.

Legacy `api_protocol=auto` configurations retain their existing provider
resolution behavior. A strict explicit profile fails closed if its protocol
cannot be built or called.

The expected flow is:

```text
turn selection
  -> resolved LLMConfig
  -> complete LLMClientConfig
  -> runtime provider for the explicit protocol
  -> OpenAI-style agentic facade
  -> labeled agentic loop
```

## 7. Response and Error Design

### 7.1 Normalized response and error envelope

Every provider call produces one normalized result before the agentic layer
decides whether it may continue:

```json
{
  "content": "partial visible text",
  "tool_calls": [],
  "usage": {
    "prompt_tokens": 1200,
    "completion_tokens": 6000,
    "reasoning_tokens": 5800,
    "total_tokens": 7200
  },
  "termination": {
    "protocol": "openai_responses",
    "provider_status": "incomplete",
    "finish_reason": "length",
    "incomplete_details": {
      "reason": "max_output_tokens"
    },
    "response_id": "resp_..."
  },
  "continuation_items": []
}
```

`LLMResponse` gains structured termination metadata and an explicit
`continuation_items` carrier. The final facade stream chunk exposes the same
fields, and `LabeledStepResult` preserves them for the owning loop. The
Responses parser recognizes all terminal event shapes, including
`response.completed`, `response.incomplete`, `response.failed`, and
`response.cancelled`, rather than assuming every terminal payload arrives in a
`response.completed` event.

An `AgenticModelError` contains the error code, safe message, retryability, and
the complete normalized result. Thus partial text, completed tool calls, usage,
and `incomplete_details` remain available for traces, persistence, and
diagnostics, but the failed result cannot be dispatched as a normal agentic
step. An incomplete tool call is retained for diagnosis but is never executed.

### 7.2 Error taxonomy

The shared layer will emit typed errors rather than relying on message matching:

| Code | Meaning | Default action |
|---|---|---|
| `model_protocol_error` | Explicit protocol could not be used | Fail; configuration action |
| `model_output_incomplete` | Provider ended before a complete output | Reason-aware retry |
| `model_output_empty` | Completed with neither visible text nor tool call | Fail; no blind loop |
| `model_provider_failed` | Provider lifecycle ended failed | Retry only if transient |
| `model_provider_cancelled` | Provider cancelled the response | User-initiated retry |
| `model_transport_transient` | Timeout, rate limit, or retryable 5xx | Bounded backoff |
| `tool_stage_failed` | A research tool or block failed | Retry failed block |
| `research_all_blocks_failed` | No block supplied usable evidence | Fail before reporting |
| `report_generation_failed` | Evidence exists but report is unusable | Retry reporting only |

Non-empty output with a missing action label remains a label-protocol violation
and uses the existing bounded repair path. Empty, incomplete, failed, or
cancelled provider output bypasses label repair and follows the typed error path.

### 7.3 Reasoning continuation

Visible reasoning summaries may be streamed to the existing reasoning trace but
never copied into formal answer text. Responses output items needed for a
stateless tool continuation use an explicit, per-request carrier:

1. the Responses parser extracts only the ordered reasoning and function-call
   items required for continuation into `LLMResponse.continuation_items`;
2. the facade copies that value to the final stream chunk and
   `LabeledStepResult`;
3. the owning loop attaches it to that loop's next assistant message as
   `responses_continuation_items`;
4. the Responses request builder uses those items, followed by the matching
   function output, instead of reconstructing or reordering them.

The pooled client and provider remain stateless. Each parallel research block
owns a separate message list, so continuation state cannot cross turns, blocks,
or concurrent requests. Continuation items are in-memory only, are ignored by
non-Responses protocols, and are never rendered, logged, or persisted in the
research checkpoint.

## 8. Research Outcome State Machine

The research pipeline will classify its domain result separately from the
session's storage status:

```text
all blocks complete + substantive report -> outcome=completed, session=completed
some blocks complete + substantive report -> outcome=partial,   session=completed
zero blocks complete                    -> outcome=failed,    session=failed
evidence exists + report not substantive -> outcome=failed,    session=failed
```

`partial` remains a successful transport/session completion because it contains
usable user content, but the domain outcome is explicit and the UI must not call
it complete.

Planning and reporting use these guards:

- Empty rephrase/decompose output receives the existing bounded repair attempt;
  if it remains empty, planning fails instead of fabricating a one-item outline.
- Reporting is skipped when zero research blocks complete.
- A successful block must reach protocol `FINISH`, have `TopicStatus.COMPLETED`,
  and contain at least 80 non-whitespace characters after protocol markers and
  known fallback/error notices are removed.
- A substantive report must contain at least 200 non-whitespace body characters
  after the H1 title, citation-only lines, and known fallback/error notices are
  removed. A Markdown title or one-line error never passes.
- A partial report identifies failed block titles and retains every successful
  block and citation.

The 80/200 character gates are fixed domain constants with boundary tests, not
new user configuration. A block that fails its content gate is classified as a
failed block even if its loop set `TopicStatus.COMPLETED`.

The result event metadata will include:

```json
{
  "outcome": "failed",
  "attempt_id": "attempt_...",
  "retry_of_attempt_id": null,
  "successful_block_count": 0,
  "failed_block_count": 1,
  "failure": {
    "code": "research_all_blocks_failed",
    "stage": "researching",
    "summary": "No research block produced usable evidence.",
    "retry_strategy": "failed_blocks"
  },
  "model_snapshot": {
    "profile_id": "...",
    "model_id": "...",
    "model": "...",
    "protocol": "openai_responses",
    "reasoning_effort": "xhigh"
  }
}
```

Secrets, authorization headers, opaque reasoning content, and raw provider
payloads are never included.

### 8.1 Terminal event protocol

Failed research uses one deterministic event sequence:

```text
RESULT(outcome=failed, public failure metadata)
ERROR(turn_terminal=true, status=failed, same failure code and attempt_id)
DONE(status=failed)
```

The pipeline raises a typed `ResearchTerminalError` containing the already-built
public result and checkpoint. It does not emit its current generic failure card.
The orchestrator catches this type, emits the single terminal `ERROR`, and then
the normal `DONE(failed)`. Other exceptions retain the generic orchestrator
path. This avoids duplicate errors while ensuring `_resolve_turn_outcome()`
persists a failed turn.

The turn runtime persists a terminal assistant message for failed turns before
updating the turn status. That message includes all events received before the
exception, any partial visible content, the public result summary, and the
research checkpoint. Reloading a failed session therefore shows the same reason
and retry action rather than relying on an in-memory WebSocket event.

### 8.2 Durable attempt checkpoint

The authority for retry is `assistant_message.metadata.research_attempt`, stored
by both existing session backends. It is versioned and immutable after terminal
persistence:

```json
{
  "schema_version": 1,
  "attempt_id": "attempt_...",
  "retry_of_attempt_id": null,
  "retry_request_id": null,
  "source_user_message_id": 42,
  "strategy": "full_research",
  "input": {
    "topic": "...",
    "confirmed_outline": [],
    "research_config": {}
  },
  "model_snapshot": {
    "profile_id": "...",
    "model_id": "...",
    "model": "...",
    "protocol": "openai_responses",
    "reasoning_effort": "xhigh"
  },
  "blocks": [
    {
      "id": "block_1",
      "title": "...",
      "overview": "...",
      "status": "completed",
      "knowledge": "...",
      "citation_ids": [1],
      "failure": null
    }
  ],
  "citations": [],
  "report": {
    "outcome": "partial",
    "content": "..."
  },
  "failure": null,
  "checkpoint_hash": "sha256:..."
}
```

The profile and model IDs come from the turn boundary's
`context.metadata.llm_selection`; they are not inferred from `LLMConfig`.
`checkpoint_hash` covers the canonical checkpoint excluding the hash field.
Continuation/reasoning items and credentials are excluded.

After hashing, the pipeline places the checkpoint in the private in-process
`context.metadata["_research_attempt_checkpoint"]` slot. The turn runtime
uses the same `UnifiedContext` instance after the orchestrator finishes; the
typed-error catch must not clone, replace, or clear that slot. For every
confirmed-outline terminal outcome (`completed`, `partial`, or `failed`), the
turn runtime passes
`metadata={"research_attempt": checkpoint}` to `add_message()` on both normal
and exception persistence paths, then removes the private slot only after the
message write succeeds. It is never attached to a stream event or the public
result envelope. The public `RESULT` contains only outcome, counts, safe failure
details, model snapshot, attempt IDs, and retry strategy.

Retry lookup is scoped by session, source user message, and attempt ID. The
runtime verifies the checkpoint version and hash before reuse. A retry writes a
new checkpoint and lineage link; it never mutates its parent. The same
`retry_request_id` plus the same source attempt and strategy replays the existing
child attempt, while reuse with different parameters returns an idempotency
conflict.

## 9. Retry Design

Automatic retries occur inside one attempt and are recorded in trace metadata:

- Retryable transport errors use bounded exponential backoff.
- `incomplete_reason=max_output_tokens` raises the same stage's output budget
  once to `min(current_budget * 2, model_or_profile_limit)`. If that value is not
  greater than the current budget, the call fails without another request. The
  original and retry budgets are recorded.
- An empty completed output is not automatically repeated because an endpoint,
  model, or protocol mismatch will otherwise waste calls.

User-triggered retries create a new linked attempt:

- `failed_blocks` reuses the confirmed outline and successful block evidence,
  then runs only failed blocks and rebuilds the affected report.
- `report_only` reuses all collected evidence and reruns reporting.
- `full_research` reuses the user topic and configuration snapshot but starts
  research work again.
- The default model selection is the failed attempt's immutable snapshot. A
  model change is explicit and is recorded on the new attempt.

A `retry_research_attempt` turn message carries session ID, source attempt ID,
strategy, idempotency key, and optional explicit model override. It uses the
existing turn runner but does not call the current delete-style
`regenerate_last_turn()`. The previous assistant message remains persisted. On
the SQLite branch model, the new assistant is a sibling response to the same
source user message; on storage backends without branch projection, lineage
metadata still preserves and exposes both attempts without deleting either.

## 10. Frontend Design

The existing research status surface gains three outcome presentations:

- green success treatment: `Research complete`;
- amber warning treatment: `Partially complete`, failed-part count, and
  `Retry failed parts` action;
- red error treatment: `Research failed`, concise reason, and retry action.

An expandable technical-details region shows safe model and termination
metadata. The primary content remains visible for partial results. Retry buttons
use the existing icon library and stable button dimensions. Existing responsive
layout and status components are reused; no new page, nested cards, or separate
visual mockup is required.

The server sends stable error codes and safe data, while the frontend owns
Chinese and English user-facing translations. The CTA is selected by code:

| Failure/outcome | Primary CTA |
|---|---|
| `partial` or `tool_stage_failed` | Retry failed parts |
| `report_generation_failed` | Retry report |
| `model_output_incomplete` | Retry with recorded higher budget |
| retryable transport/provider failure | Retry research |
| `model_protocol_error` | Open model settings; no unchanged retry |
| `model_output_empty` | Review model settings, then allow explicit retry |
| `research_all_blocks_failed` | Retry research |

The technical-details disclosure never substitutes a raw exception string for a
localized failure summary.

## 11. Observability

Structured logs and trace events will include attempt ID, selected profile/model,
resolved protocol, stage, finish reason, provider status, incomplete reason,
retry index, token budget, token usage, and block outcome. Sensitive headers,
keys, and reasoning payloads are excluded.

A successful deployment E2E must make it possible to answer:

- which protocol was actually called;
- why a call stopped;
- why the research outcome was classified completed, partial, or failed;
- what a retry changed.

## 12. Verification Plan

### Backend unit and integration tests

- An explicit Responses selection reaches `/v1/responses`, never
  `/chat/completions`.
- An explicit Anthropic selection reaches the Messages adapter and stays strict.
- Agentic client pool entries differ by protocol, strictness, and effective URL.
- Responses parsing covers completed text, tool calls, incomplete details,
  failed, cancelled, empty completed output, usage, and reasoning-token details.
- A tool continuation replays provider-required reasoning items when present.
- Labeled steps distinguish missing labels from incomplete/empty provider output.
- Research outcome tests cover full success, partial success, zero successful
  blocks, the 80-character block boundary, the 200-character report boundary,
  title-only reporting, and reporting failure.
- Retry tests verify budget escalation occurs once and block/report retries do
  not discard successful evidence.
- Checkpoint tests cover canonical hashing, tamper rejection, lineage,
  idempotent replay, conflicting idempotency reuse, and both session stores.
- Completed, partial, and failed checkpoint tests each persist through
  `add_message(metadata=...)`, reload from session history, and reproduce the
  same public outcome and retry strategy.
- Terminal tests assert exactly `RESULT -> ERROR -> DONE(failed)`, persisted
  failed assistant history, and no duplicate generic error.

### Frontend tests

- Completed, partial, and failed states use distinct semantics and colors.
- Failure summary, technical details, and appropriate retry action render from
  result metadata.
- A legacy result without `outcome` continues to render safely.
- Narrow and desktop layouts do not overlap or resize when status changes.

### Real-model E2E

Using the configured `gpt-5.6-sol/xhigh` Responses profile:

1. create a new Deep Research session;
2. confirm the generated outline;
3. require every planned research block to pass its success gate;
4. require a substantive report, `outcome=completed`, and the green completed UI;
5. verify non-zero completion tokens and recorded `openai_responses` protocol;
6. exercise one controlled failure fixture to verify reason, persistence, and
   targeted retry rendering.

Chat, Question, and Explore Context receive focused regression tests because the
shared client construction changes for all four capabilities.

## 13. Deployment and Rollback

Deployment uses one reviewed script that performs:

1. preflight checks for a clean committed fork revision, required environment,
   persistent volume, ports, current rollback image, and proof that the exact
   deployment SHA exists on the fork remote;
2. an immutable image build tagged with the exact Git SHA;
3. test and image smoke checks;
4. container replacement while preserving the existing data volume;
5. health, readiness, UI, API, protocol-routing, and real-model E2E checks;
6. receipt generation with fork remote, commit, image digest and commit label,
   deployed container image, volume, checks, and rollback image.

If a post-deploy check fails, the script restores the previous immutable image
against the same persistent volume and reruns health/readiness checks. It does
not delete or recreate user data.

## 14. Baseline Playback and Acceptance Mapping

| Baseline | User path and observable result | Boundary/non-goal | Primary evidence |
|---|---|---|---|
| DRR-01 | Select Responses, run research, observe recorded Responses protocol | No silent model or protocol fallback | `/v1/responses` wire test plus real E2E |
| DRR-02 | Receive any terminal lifecycle and see correct success/failure behavior | Reasoning and partial output never become a successful answer | Parser, facade, continuation, and labeled-step tests |
| DRR-03 | Open completed, partial, and failed attempts and see distinct color/status | Partial remains usable; title-only is never complete | Outcome matrix and frontend state tests |
| DRR-04 | Expand a failure and see safe model/stage/termination diagnostics | No credentials, raw payloads, or reasoning items | API/result fixture, localization, and secret-redaction tests |
| DRR-05 | Retry the offered scope and retain the parent attempt and successful work | No destructive regenerate or implicit model change | Checkpoint, lineage, idempotency, and targeted-retry E2E |
| DRR-06 | Deploy the pushed SHA, pass a fully completed real-model E2E, retain rollback | No data-volume replacement; partial E2E cannot pass | Deployment receipt, remote-SHA proof, health, and rollback proof |

No baseline item is satisfied by a capability probe alone. Completion requires
behavioral evidence from the actual agentic path and the deployed application.
