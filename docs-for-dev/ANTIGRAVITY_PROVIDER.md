# Antigravity CLI model provider

The `antigravity` LLM binding uses an installed `agy` CLI and its own local
Google login. It can be selected as the default conversation or task model;
the existing Antigravity **connected agent** is a separate feature.

## Setup

1. Install Antigravity CLI and run `agy` interactively to sign in.
2. Run `deeptutor provider login antigravity` to validate the local login by
   listing models. This does not start a model turn or copy any credentials.
3. In Settings → Providers, add **Antigravity CLI** and click **Refresh models**.
   The provider card lists models from the local CLI account. No API URL or API
   key is needed. Choose one and click **Use as default conversation model**.
4. Apply settings using the existing global toolbar, then test a chat turn.
   All discovered models also appear in the chat model picker, where they can
   be selected for an individual conversation just like other LLM providers.

Refreshing adds models to the shared settings draft and preserves existing model
IDs, custom models, overrides, the current default, and unrelated pending edits.
It never changes the running model until settings are applied. Choosing a new
default updates only the conversation service, leaving task model overrides alone.

For non-interactive setup in the same `DEEPTUTOR_HOME`:

```json
{
  "llm": {
    "provider": "antigravity",
    "model": "YOUR_MODEL_ID_FROM_AGY_MODELS"
  }
}
```

```bash
deeptutor config apply setup.json --check
deeptutor config apply setup.json
deeptutor doctor --online --format json
```

The CLI must be on the backend process's PATH. Restart the backend after
installing it. In a container, a CLI installed only on the host is insufficient.
Authentication and model availability come from `agy models`, not a hardcoded
catalog. The default model constant is only a fallback for direct SDK calls.

## Adapter behavior

- Every request replays the supplied system messages, conversation, tool calls,
  and tool results into a new CLI conversation. This preserves branches and
  avoids sharing hidden conversation state across DeepTutor sessions.
- Prompts go through JSONL stdin, avoiding shell interpolation and Windows
  command-line length limits. Literal `@` in message data is JSON-escaped to
  avoid the CLI's file-mention expansion. Slash command expansion is disabled.
- Child processes honor explicit proxy environment variables, then the OS proxy
  (including Windows system proxy settings). Loopback traffic bypasses proxies.
  Neither the parent environment nor global proxy settings are changed.
- The CLI runs in a temporary workspace with a custom agent with no task tools
  and session-only deny rules for command, write, browser, and MCP actions.
  Text requests also deny file reads. Image requests permit `view_file` only
  for images materialized from inline data in that request's private workspace;
  outside-workspace access stays disabled. Every image must have a successful
  read event before a response can be returned. Structured replies use the
  CLI's internal `finish` serializer.
  It is never launched with permission bypass. An unexpected native tool event
  fails the model request rather than reporting a successful DeepTutor tool run.
- DeepTutor tool schemas are translated into a structured response envelope.
  Tool names and arguments are validated before returning `ToolCallRequest` to
  DeepTutor's dispatcher. The adapter does not execute these tools itself.
- Plain text streams as CLI text deltas. When tools are offered, output is
  buffered until the structured envelope has been validated, so raw JSON never
  appears in the chat reply. Usage is mapped from the CLI's terminal result.
- Failure, malformed output, missing terminal results, empty answers, timeout,
  and cancellation are errors. Exit status alone is insufficient. Owned child
  process trees are cleaned up on timeout, cancellation, and provider shutdown.

Text and inline PNG, JPEG, WebP, and GIF images are supported, including images
in earlier messages and tool results. Remote image URLs and local paths are not
fetched by the adapter; DeepTutor's shared attachment preparation can resolve
its own attachment URLs into inline data first. Image inputs are bounded to
20 MiB per image, 64 MiB total, and 64 images per request. They use structured
output and are buffered until image-read and output validation finish. Audio
and video content is rejected explicitly. PDFs continue through DeepTutor's
existing parsing and page-image pipeline; the CLI is not given arbitrary PDF
file access. The CLI controls sampling and generation limits;
DeepTutor's `temperature` and `max_tokens` are not forwarded as unsupported CLI
flags. Fresh CLI startup and full-history replay add latency. The default
request deadline is 180 seconds; the provider constructor accepts `timeout`.
Local CLI settings, hooks, and credentials remain owned by Antigravity.

The implementation targets the headless/JSONL protocol documented in the
[official CLI guide](https://antigravity.google/docs/cli/headless/) and the
[session settings and permission rules](https://antigravity.google/docs/settings?tab=cli).
It has been manually exercised with Antigravity CLI 1.4.12 on Windows.

## Validation

```bash
python -m pytest tests/services/llm/test_antigravity_provider.py
cd web
npm run test:unit -- tests/provider-registry-workflow.spec.tsx tests/model-settings-workflow.spec.tsx
npm run typecheck
```

Real-provider acceptance must additionally check model discovery, a completed
WebSocket chat turn, history continuation, and a tool-call/result round trip.
