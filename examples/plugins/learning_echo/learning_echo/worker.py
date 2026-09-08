"""JSON worker protocol for the Learning Echo example.

The host launches this module with the plugin venv interpreter. It reads one
request, returns one JSON response, and never imports DeepTutor host modules.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def main() -> None:
    request = json.loads(sys.stdin.read())
    operation = request.get("operation")
    if operation == "describe_tool":
        response = describe_tool()
    elif operation == "execute_tool":
        response = execute_tool(request.get("arguments") or {})
    elif operation == "describe_capability":
        response = describe_capability()
    elif operation == "run_capability":
        response = run_capability(request.get("context") or {})
    else:
        response = {"error": f"unknown operation: {operation}"}
    print(json.dumps(response, ensure_ascii=False))


def describe_tool() -> dict[str, Any]:
    return {
        "permissions": {},
        "definition": {
            "name": "learning_echo",
            "description": "Echo a learning prompt back with a stable prefix.",
            "parameters": [
                {
                    "name": "message",
                    "type": "string",
                    "description": "Text to echo",
                    "required": True,
                }
            ],
        },
    }


def execute_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    message = str(arguments.get("message", "")).strip()
    if not message:
        return {"result": {"content": "message is required", "success": False}}
    return {"result": {"content": f"learning echo: {message}", "success": True}}


def describe_capability() -> dict[str, Any]:
    return {
        "permissions": {},
        "capability": {
            "name": "learning_echo_capability",
            "description": "Emit a one-event learning echo capability result.",
            "stages": ["responding"],
        },
    }


def run_capability(context: dict[str, Any]) -> dict[str, Any]:
    message = str(context.get("user_message", "")).strip() or "empty learning turn"
    return {
        "permissions": {},
        "events": [
            {
                "type": "content",
                "stage": "responding",
                "content": f"learning capability echo: {message}",
            }
        ],
    }


if __name__ == "__main__":
    main()
