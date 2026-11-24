---
title: Python SDK
description: Embed DeepTutor's turn, session, capability, and notebook runtime directly in an async Python application.
quadrant: tutorial
---

`DeepTutorApp` is DeepTutor's stable, in-process Python facade. It exposes the same turn payload and runtime contracts used by the CLI, without spawning the CLI or sending requests through the HTTP API. Use it when your application already runs in Python and needs native access to streamed events, sessions, capability metadata, or notebooks.

## Prerequisites

Use Python 3.11–3.14, install DeepTutor, and initialize the same runtime workspace you would use for the CLI:

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --home /path/to/workspace
```

Run your program with `DEEPTUTOR_HOME=/path/to/workspace`. If that variable is unset, DeepTutor uses the current working directory. The SDK reads the same provider and runtime files under `data/user/settings/` as `deeptutor chat` and `deeptutor run`, so configure a working model before starting a turn.

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

`TurnRequest` also accepts a session ID, enabled tools, knowledge bases, language, capability configuration, notebook/history references, partner-group references, attachments, and skills.

## Available operations

| Area | Methods |
| --- | --- |
| Turn lifecycle | `start_turn()`, `stream_turn()`, `cancel_turn()`, `submit_user_reply()`, `regenerate_last_turn()` |
| Sessions | `list_sessions()`, `get_session()`, `rename_session()`, `delete_session()`, `get_active_turn()` |
| Capabilities | `resolve_capability()`, `get_capability_contract()`, `get_capability_contracts()`, `get_capability_availability()` |
| Notebooks | `list_notebooks()`, `create_notebook()`, `get_notebook()`, and record add/update/remove/reference methods |

Turn and session methods are async; capability discovery and notebook methods are synchronous.

## SDK, CLI, or API?

`deeptutor run --format json` creates the same `DeepTutorApp` and `TurnRequest`, then serializes each `stream_turn()` item as one NDJSON line. Its headless mode automatically answers an `ask_user` pause with an empty reply; SDK callers instead decide when to call `submit_user_reply()`.

Use the **CLI** for shell pipelines and agent handoff, the **Python SDK** for an in-process async integration, and the **HTTP / WebSocket API** when DeepTutor must run as a separate service or serve non-Python clients.

## See also

- [Agent Handoff](/cli/agent-handoff/) — consume the same stream as NDJSON
- [Server API](/cli/server-api/) — connect across a process or network boundary
- [Command Reference](/cli/commands/) — configure and inspect the shared workspace
