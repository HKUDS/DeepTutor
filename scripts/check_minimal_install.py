#!/usr/bin/env python3
"""Exercise core chat, SQLite persistence and replay with a local model fixture.

Run outside the checkout with an interpreter containing only the core wheel.
--source-core additionally blocks optional source imports for fast development.
No provider credentials or external network calls are used.
"""

import argparse
import asyncio
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-core", action="store_true")
parser.add_argument("--capability", default="chat")
parser.add_argument("--home", type=Path)
parser.add_argument("--full", action="store_true", help="Allow the full application's capabilities")
parser.add_argument("--save-replay", type=Path, help="Save a durable turn to verify after upgrade")
parser.add_argument("--verify-replay", type=Path, help="Replay a turn saved before the upgrade")
args = parser.parse_args()
runtime_home = tempfile.TemporaryDirectory(prefix="deeptutor-core-smoke-")
os.environ["DEEPTUTOR_HOME"] = str(args.home) if args.home else runtime_home.name
if args.source_core:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if args.source_core:
    from deeptutor.modules import catalog

    catalog.installed = lambda name: name == "core"

    class BlockOptional(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(("deeptutor.", "deeptutor_cli.")):
                relative = fullname.replace(".", "/")
                owner = catalog.module_for_path(relative + ".py")
                if not (Path(__file__).resolve().parents[1] / (relative + ".py")).is_file():
                    owner = catalog.module_for_path(relative + "/__init__.py")
                if owner != "core":
                    # Wheels retain namespace parents for core-owned shared metadata,
                    # without shipping the optional application's __init__.py.
                    if any(
                        item.startswith(relative + "/")
                        for item in catalog.manifests()["core"]["paths"]
                    ):
                        spec = importlib.machinery.ModuleSpec(
                            fullname, loader=None, is_package=True
                        )
                        spec.submodule_search_locations = [
                            str(Path(__file__).resolve().parents[1] / relative)
                        ]
                        return spec
                    raise ModuleNotFoundError(f"Absent module {owner}: {fullname}", name=fullname)

    sys.meta_path.insert(0, BlockOptional())
from deeptutor.app import DeepTutorApp


async def main():
    app = DeepTutorApp()
    try:
        if args.verify_replay:
            saved = json.loads(args.verify_replay.read_text())
            assert await app.get_session(saved["session_id"]) is not None
            replay = [item async for item in app.stream_turn(saved["turn_id"])]
            assert [
                [e["seq"], e["type"], e["content"]]
                for e in replay
                if e["seq"] <= saved["terminal_seq"]
            ] == saved["events"]
            print("Pre-upgrade session and durable turn replay: OK")
        contracts = {row["name"] for row in app.get_capability_contracts()}
        assert {"chat", "ask_questions", args.capability} <= contracts
        if args.capability == "chat" and not args.full:
            assert contracts == {"chat", "ask_questions"}, contracts
        session, turn = await app.start_turn(
            {"content": "Hello", "capability": args.capability, "tools": []}
        )
        events = [item async for item in app.stream_turn(turn["id"])]
        assert not [event for event in events if event["type"] == "error"], events
        assert any(
            event["type"] == "content" and "minimal core" in event["content"] for event in events
        ), events
        terminal = next(event for event in events if event["type"] == "done")
        assert terminal["metadata"]["status"] == "completed", events
        assert await app.get_session(session["id"]) is not None
        await app.container.close()
        from deeptutor.app.container import set_application_container

        set_application_container(None)
        app = DeepTutorApp()
        replay = [item async for item in app.stream_turn(turn["id"])]
        assert [
            (e["seq"], e["type"], e["content"]) for e in replay if e["seq"] <= terminal["seq"]
        ] == [(e["seq"], e["type"], e["content"]) for e in events if e["seq"] <= terminal["seq"]]
        if args.save_replay:
            args.save_replay.write_text(
                json.dumps(
                    {
                        "session_id": session["id"],
                        "turn_id": turn["id"],
                        "terminal_seq": terminal["seq"],
                        "events": [
                            [e["seq"], e["type"], e["content"]]
                            for e in events
                            if e["seq"] <= terminal["seq"]
                        ],
                    }
                )
            )
        print("Core chat, durable session and replay: OK")
    finally:
        await app.container.close()


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream" if body.get("stream") else "application/json"
        )
        self.end_headers()
        if body.get("stream"):
            for delta, finish in [
                ({"content": "Hello from the minimal core."}, None),
                ({}, "stop"),
            ]:
                value = {
                    "id": "smoke",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "smoke",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(
                json.dumps(
                    {
                        "id": "smoke",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "smoke",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "Hello from the minimal core.",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                ).encode()
            )


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
import deeptutor.services.llm.config as config

config._LLM_CONFIG_CACHE = config.LLMConfig(
    model="smoke",
    api_key="local-test",
    base_url=f"http://127.0.0.1:{server.server_port}/v1",
    wire_api="chat_completions",
)
try:
    asyncio.run(asyncio.wait_for(main(), timeout=30))
finally:
    server.shutdown()
    runtime_home.cleanup()
