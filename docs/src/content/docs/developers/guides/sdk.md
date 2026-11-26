---
title: Python SDK
description: Call one DeepTutor turn from an async Python program and read the answer as it streams.
quadrant: tutorial
---

`DeepTutorApp` is the Python entry point that runs inside your process. A turn is one request and the events that come back until it finishes. The SDK uses the same turn payload the CLI uses. It does not start the CLI, and it does not send the request over HTTP. Use it when your program is already Python and you want the events, the session, or a notebook in the same process.

## Prerequisites

Use Python 3.11–3.14, install DeepTutor, and initialize the same runtime workspace you would use for the CLI:

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --home /path/to/workspace
```

Run your program with `DEEPTUTOR_HOME=/path/to/workspace`. If that variable is unset, DeepTutor uses the current working directory. The SDK reads the same provider and runtime files under `data/user/settings/` as `deeptutor chat` and `deeptutor run`. Configure a working model before you start a turn, or the call has no model to answer with.

## Run one turn

```python
import asyncio

from deeptutor.app import DeepTutorApp, TurnRequest


async def main() -> None:
    app = DeepTutorApp()
    session, turn = await app.start_turn(
        TurnRequest(
            content="Explain the Fourier transform in one paragraph.",
            capability="chat",
        )
    )

    answer = ""
    async for event in app.stream_turn(turn["id"]):
        if event["type"] == "result":
            answer = (event.get("metadata") or {}).get("response", "")

    print(answer)
    print("session:", session["id"])


asyncio.run(main())
```

When this finishes, the terminal prints the paragraph and a session id. That id is the conversation you can open again.

`TurnRequest` also accepts a session ID, enabled tools, knowledge bases, language, capability configuration, notebook/history references, partner-group references, attachments, and skills. A capability here is the named workflow for the turn, such as `chat`.

## Available operations

| Area | Methods |
| --- | --- |
| Turn lifecycle | `start_turn()`, `stream_turn()`, `cancel_turn()`, `submit_user_reply()`, `regenerate_last_turn()` |
| Sessions | `list_sessions()`, `get_session()`, `rename_session()`, `delete_session()`, `get_active_turn()` |
| Capabilities | `resolve_capability()`, `get_capability_contract()`, `get_capability_contracts()`, `get_capability_availability()` |
| Notebooks | `list_notebooks()`, `create_notebook()`, `get_notebook()`, and record add/update/remove/reference methods |

Turn and session methods are async. You await them. Capability discovery and notebook methods return immediately.

## SDK, CLI, or API?

`deeptutor run --format json` creates the same `DeepTutorApp` and `TurnRequest`, then writes each `stream_turn()` item as one NDJSON line. If the turn pauses on `ask_user`, that headless command sends an empty reply for you. In the SDK, you choose when to call `submit_user_reply()`.

Use the **CLI** for a shell pipeline or to hand the stream to another agent. Use the **Python SDK** when the call stays inside your Python process. Use the **HTTP / WebSocket API** when DeepTutor runs as its own service, or when the caller is not Python.

## See also

- [Agent Handoff](/developers/guides/agent-handoff/) — consume the same stream as NDJSON
- [Server API](/developers/reference/http-api/) — connect across a process or network boundary
- [Command Reference](/developers/reference/cli/) — configure and inspect the shared workspace
