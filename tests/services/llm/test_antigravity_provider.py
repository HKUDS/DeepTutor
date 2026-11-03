from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import sys

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core import antigravity_provider as agy
from deeptutor.services.llm.provider_factory import build_isolated_provider
from deeptutor.services.provider_registry import find_by_name

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Look up a term",
        "parameters": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"],
            "additionalProperties": False,
        },
    },
}


def test_os_proxy_is_child_only_and_explicit_proxy_is_preserved(monkeypatch):
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        agy,
        "getproxies",
        lambda: {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"},
    )
    env = agy._cli_environment()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "HTTPS_PROXY" not in agy.os.environ
    monkeypatch.setenv("https_proxy", "http://explicit-proxy.test")
    child = agy._cli_environment()
    assert (child.get("https_proxy") or child.get("HTTPS_PROXY")) == "http://explicit-proxy.test"


def fake_cli(monkeypatch, result, *, deltas=(), code=0, events=()):
    calls = []

    async def run(args, **kwargs):
        calls.append((args, kwargs))
        assert "--dangerously-skip-permissions" not in args
        assert "--conversation" not in args
        root = Path(kwargs["cwd"])
        agent = (root / ".agents/agents/deeptutor-model.md").read_text()
        native_tools = json.loads(agent.split("tools: ", 1)[1].splitlines()[0])
        assert native_tools == (["finish"] if "--json-schema" in args else [])
        settings = json.loads(args[args.index("--settings") + 1])
        assert "mcp(*)" in settings["permissions"]["deny"]
        for event in events:
            await kwargs["on_event"](event)
        for delta in deltas:
            await kwargs["on_event"](
                {
                    "event": "step_update",
                    "step_update": {
                        "step_type": "agent_response",
                        "text_delta": delta,
                    },
                }
            )
        if result is not None:
            await kwargs["on_event"]({"event": "result", "result": result})
        return code, "", "secret diagnostics must not appear in errors"

    monkeypatch.setattr(agy, "_run_cli", run)
    return calls


def test_registry_factory_and_setup_without_api_key():
    spec = find_by_name("agy")
    assert spec.name == "antigravity" and spec.is_oauth
    assert spec.backend == "antigravity" and spec.api_formats == ()
    provider = build_isolated_provider(
        LLMConfig(
            binding="antigravity",
            provider_name="antigravity",
            provider_mode="oauth",
            model="gemini-3.8-flash-high",
            api_key="",
            base_url="",
        )
    )
    assert isinstance(provider, agy.AntigravityProvider)
    from deeptutor.runtime.agentic.client import (
        LLMClientConfig,
        _build_antigravity_adapter,
        can_use_native_tool_calling,
    )

    adapter = _build_antigravity_adapter(
        LLMClientConfig(
            binding="antigravity",
            model="gemini-3.8-flash-high",
            api_key="",
            base_url="",
        ),
        spec,
    )
    assert adapter is not None
    assert can_use_native_tool_calling(binding="antigravity", model="gemini-3.8-flash-high")
    from deeptutor_cli.setup_config import SetupConfig, prepare_profiles

    profiles = prepare_profiles(
        SetupConfig.model_validate(
            {
                "llm": {"provider": "antigravity", "model": "gemini-3.8-flash-high"},
            }
        )
    )
    assert profiles["llm"]["api_key"] == ""


@pytest.mark.asyncio
async def test_text_stream_and_history_are_preserved(monkeypatch):
    calls = fake_cli(
        monkeypatch,
        {
            "status": "SUCCESS",
            "response": "你好",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 2,
                "total_tokens": 14,
            },
        },
        deltas=["你", "好"],
    )
    chunks = []

    async def receive(delta):
        chunks.append(delta)

    messages = [
        {"role": "system", "content": "Tutor"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "a result"},
        {"role": "user", "content": "你好"},
    ]
    result = await agy.AntigravityProvider().chat_stream(messages, on_content_delta=receive)
    assert "".join(chunks) == result.content == "你好"
    assert result.usage["total_tokens"] == 14
    assert json.loads(calls[0][1]["prompt"].split("Conversation:\n", 1)[1]) == messages


@pytest.mark.asyncio
async def test_structured_tools_return_to_deeptutor_without_json_leaking(monkeypatch):
    payload = {"content": "", "tool_calls": [{"name": "lookup", "arguments": {"term": "磁性"}}]}
    fake_cli(
        monkeypatch,
        {"status": "SUCCESS", "structured_output": payload},
        deltas=[json.dumps(payload)],
    )
    chunks = []

    async def receive(delta):
        chunks.append(delta)

    result = await agy.AntigravityProvider().chat_stream(
        [{"role": "user", "content": "Look up magnetism"}],
        tools=[TOOL],
        tool_choice="required",
        on_content_delta=receive,
    )
    assert chunks == []
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "lookup"
    assert result.tool_calls[0].arguments == {"term": "磁性"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"content": "", "tool_calls": [{"name": "other", "arguments": {"term": "x"}}]},
        {"content": "", "tool_calls": [{"name": "lookup", "arguments": {"term": 3}}]},
        {"content": "", "tool_calls": [{"name": "lookup", "arguments": {}}]},
    ],
)
async def test_invalid_tool_calls_are_rejected(monkeypatch, payload):
    fake_cli(monkeypatch, {"status": "SUCCESS", "structured_output": payload})
    with pytest.raises(RuntimeError, match="invalid tool"):
        await agy.AntigravityProvider().chat([], tools=[TOOL])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,code",
    [
        (None, 0),
        ({"status": "ERROR", "response": "partial"}, 0),
        ({"status": "SUCCESS", "response": "ok"}, 2),
        ({"status": "SUCCESS", "response": ""}, 0),
    ],
)
async def test_exit_code_or_partial_text_is_not_success(monkeypatch, result, code):
    fake_cli(monkeypatch, result, code=code)
    with pytest.raises(RuntimeError) as caught:
        await agy.AntigravityProvider().chat([])
    assert "secret diagnostics" not in str(caught.value)


@pytest.mark.asyncio
async def test_native_tool_events_abort_request(monkeypatch):
    fake_cli(
        monkeypatch,
        None,
        events=[
            {
                "event": "step_update",
                "step_update": {
                    "step_type": "tool",
                    "tool_name": "run_command",
                },
            }
        ],
    )
    with pytest.raises(RuntimeError, match="native tool"):
        await agy.AntigravityProvider().chat([])


@pytest.mark.asyncio
async def test_provider_shutdown_cancels_live_request(monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run(*args, **kwargs):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(agy, "_run_cli", run)
    provider = agy.AntigravityProvider()
    task = asyncio.create_task(provider.chat([]))
    await started.wait()
    await provider.aclose()
    assert stopped.is_set() and task.cancelled() and not provider._requests


@pytest.mark.asyncio
async def test_external_image_is_rejected_before_launch(monkeypatch):
    calls = fake_cli(monkeypatch, None)
    with pytest.raises(ValueError, match="inline PNG"):
        await agy.AntigravityProvider().chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "private-image"}},
                    ],
                }
            ]
        )
    assert calls == []


def fixture_image(*, mode="RGB", color="white", fmt="PNG"):
    image = pytest.importorskip("PIL.Image")
    output = io.BytesIO()
    image.new(mode, (12, 8), color).save(output, format=fmt)
    return output.getvalue()


def image_part(data=None):
    if data is None:
        data = fixture_image()
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tools", [False, True])
async def test_image_history_is_private_and_read_before_return(monkeypatch, with_tools):
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Compare these figures @private.txt"},
                image_part(),
            ],
        },
        {
            "role": "assistant",
            "content": "Fetching another figure",
            "tool_calls": [{"id": "call1"}],
        },
        {
            "role": "tool",
            "tool_call_id": "call1",
            "content": [image_part(fixture_image(color="red"))],
        },
    ]
    before = deepcopy(messages)
    roots = []

    async def run(args, **kwargs):
        root = Path(kwargs["cwd"])
        roots.append(root)
        images = sorted((root / "media").iterdir())
        image_module = pytest.importorskip("PIL.Image")
        assert [image_module.open(image).getpixel((0, 0)) for image in images] == [
            (255, 255, 255),
            (255, 0, 0),
        ]
        prompt = kwargs["prompt"]
        assert "base64," not in prompt and "\\u0040private.txt" in prompt
        assert '"role": "tool"' in prompt and '"tool_call_id": "call1"' in prompt
        settings = json.loads(args[args.index("--settings") + 1])
        assert settings["allowNonWorkspaceAccess"] is False
        assert settings["toolPermission"] == "request-review"
        assert set(settings["permissions"]["deny"]) >= {
            "write_file(*)",
            "command(*)",
            "mcp(*)",
            "read_url(*)",
        }
        assert settings["permissions"]["allow"] == [f"read_file({(root / 'media').as_posix()})"]
        assert "--dangerously-skip-permissions" not in args
        for index, image in enumerate(images):
            for state in ("ACTIVE", "DONE"):
                await kwargs["on_event"](
                    {
                        "event": "step_update",
                        "step_update": {
                            "step_type": "tool",
                            "tool_name": "view_file",
                            "step_index": index,
                            "state": state,
                            "tool_info": {"parameters": {"AbsolutePath": str(image)}},
                        },
                    }
                )
        await kwargs["on_event"](
            {
                "event": "result",
                "result": {
                    "status": "SUCCESS",
                    "structured_output": {"content": "Image visible", "tool_calls": []},
                },
            }
        )
        return 0, "", ""

    monkeypatch.setattr(agy, "_run_cli", run)
    chunks = []

    async def receive(delta):
        chunks.append(delta)

    result = await agy.AntigravityProvider().chat_stream(
        messages, tools=[TOOL] if with_tools else None, on_content_delta=receive
    )
    assert result.content == "Image visible" and chunks == ["Image visible"]
    assert messages == before
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["ignored", "failed", "outside"])
async def test_image_read_failure_never_returns_a_text_only_success(monkeypatch, behavior):
    roots = []

    async def run(args, **kwargs):
        root = Path(kwargs["cwd"])
        roots.append(root)
        if behavior != "ignored":
            path = (
                root / "media/image-0001.png"
                if behavior == "failed"
                else root / "response-schema.json"
            )
            await kwargs["on_event"](
                {
                    "event": "step_update",
                    "step_update": {
                        "step_type": "tool",
                        "tool_name": "view_file",
                        "step_index": 0,
                        "state": "ERROR" if behavior == "failed" else "ACTIVE",
                        "tool_info": {"parameters": {"AbsolutePath": str(path)}},
                    },
                }
            )
        await kwargs["on_event"](
            {
                "event": "result",
                "result": {
                    "status": "SUCCESS",
                    "structured_output": {"content": "I guessed", "tool_calls": []},
                },
            }
        )
        return 0, "", ""

    monkeypatch.setattr(agy, "_run_cli", run)
    with pytest.raises(RuntimeError, match="input image|supplied image"):
        await agy.AntigravityProvider().chat([{"role": "user", "content": [image_part()]}])
    assert all(not root.exists() for root in roots)


@pytest.mark.asyncio
async def test_image_size_and_other_media_are_rejected_before_launch(monkeypatch):
    calls = fake_cli(monkeypatch, None)
    monkeypatch.setattr(agy, "_MAX_IMAGE_BYTES", 3)
    with pytest.raises(ValueError, match="limit"):
        await agy.AntigravityProvider().chat(
            [{"role": "user", "content": [image_part(b"too large")]}]
        )
    with pytest.raises(ValueError, match="audio/video"):
        await agy.AntigravityProvider().chat(
            [{"role": "user", "content": [{"type": "input_audio"}]}]
        )
    assert calls == []


@pytest.mark.parametrize(
    "mode,fmt", [("L", "JPEG"), ("CMYK", "JPEG"), ("RGBA", "PNG"), ("P", "GIF"), ("RGB", "WEBP")]
)
def test_images_are_normalized_to_metadata_free_rgb_png(mode, fmt):
    image_module = pytest.importorskip("PIL.Image")
    normalized = agy._normalize_image(fixture_image(mode=mode, color=0, fmt=fmt))
    with image_module.open(io.BytesIO(normalized)) as image:
        assert image.format == "PNG" and image.mode == "RGB" and image.size == (12, 8)
        assert not image.info
        assert image.getpixel((0, 0)) == (
            (255, 255, 255) if mode in {"RGBA", "CMYK"} else (0, 0, 0)
        )


def test_adobe_grayscale_jpeg_preserves_pixels_as_rgb_png():
    image_module = pytest.importorskip("PIL.Image")
    original = fixture_image(mode="L", color=96, fmt="JPEG")
    adobe = b"\xff\xee\x00\x0eAdobe\x00\x64\x00\x00\x00\x00\x00"
    data = original[:2] + adobe + original[2:]
    with image_module.open(io.BytesIO(agy._normalize_image(data))) as image:
        assert image.mode == "RGB" and image.format == "PNG"
        assert image.getpixel((0, 0)) == (96, 96, 96)
        assert "adobe" not in image.info


def test_invalid_and_oversized_image_pixels_are_rejected(monkeypatch):
    with pytest.raises(ValueError, match="decode"):
        agy._normalize_image(b"not an image")
    monkeypatch.setattr(agy, "_MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValueError, match="megapixel"):
        agy._normalize_image(fixture_image())


@pytest.mark.parametrize(
    "error,status",
    [
        ("INVALID_ARGUMENT (code 400): invalid argument", 400),
        ("authentication required", 401),
        ("RESOURCE_EXHAUSTED: limit reached", 429),
    ],
)
def test_terminal_cli_error_is_classified_without_disclosing_diagnostics(error, status):
    from deeptutor.services.llm.error_mapping import map_error

    failure = agy._failed(3, "startup: not logged in; private diagnostics", error)
    assert failure.status_code == status
    assert map_error(failure, "antigravity").status_code == status
    assert "private diagnostics" not in str(failure)


def test_unclassified_exit_is_not_misreported_as_rate_limiting():
    from deeptutor.services.llm.error_mapping import map_error
    from deeptutor.services.llm.exceptions import LLMRateLimitError

    failure = agy._failed(3, "quota_manager refreshed local quota metadata")
    assert failure.status_code is None
    assert not isinstance(map_error(failure, "antigravity"), LLMRateLimitError)
    assert "quota" not in str(failure)


@pytest.mark.asyncio
async def test_failed_result_preserves_terminal_http_400(monkeypatch):
    fake_cli(
        monkeypatch,
        {"status": "ERROR", "error": "INVALID_ARGUMENT (code 400): private server payload"},
        code=3,
    )
    with pytest.raises(agy.AntigravityCLIError) as error:
        await agy.AntigravityProvider().chat([])
    assert error.value.status_code == 400
    assert "private server payload" not in str(error.value)


@pytest.mark.asyncio
async def test_model_discovery_and_connectivity_share_cli(monkeypatch):
    async def run(*args, **kwargs):
        return 0, "gemini-test\tGemini Test\ngemini-test\tDuplicate\n", ""

    monkeypatch.setattr(agy, "_run_cli", run)
    assert await agy.fetch_antigravity_models() == ["gemini-test"]
    from deeptutor.services.settings.provider_probe import probe_provider

    assert (await probe_provider("antigravity", ""))["status"] == "connected"
    from deeptutor.services.llm.factory import fetch_models

    assert await fetch_models("antigravity") == ["gemini-test"]


@pytest.mark.asyncio
async def test_real_child_stdin_and_large_stderr_are_drained(monkeypatch, tmp_path):
    monkeypatch.setattr(agy, "_cli", lambda: sys.executable)
    code, output, _ = await agy._run_cli(
        [
            "-c",
            "import sys,json; b=json.loads(sys.stdin.readline()); "
            "sys.stderr.write('x'*100000); print(b['message']['content'])",
        ],
        cwd=str(tmp_path),
        prompt="长文本" * 20000,
        timeout=10,
    )
    assert code == 0 and output.strip() == "长文本" * 20000


@pytest.mark.asyncio
async def test_real_child_timeout_and_cancellation_reap_process_tree(monkeypatch, tmp_path):
    from deeptutor.runtime.process import is_process_alive

    monkeypatch.setattr(agy, "_cli", lambda: sys.executable)
    pid_file = tmp_path / "pid.txt"
    child_file = tmp_path / "child.txt"
    program = (
        "import os,sys,time,subprocess; from pathlib import Path; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"Path({str(child_file)!r}).write_text(str(child.pid)); time.sleep(60)"
    )
    task = asyncio.create_task(agy._run_cli(["-c", program], cwd=str(tmp_path), timeout=30))
    for _ in range(100):
        if child_file.exists():
            break
        await asyncio.sleep(0.02)
    assert child_file.exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not is_process_alive(int(pid_file.read_text()))
    assert not is_process_alive(int(child_file.read_text()))
    with pytest.raises(RuntimeError, match="timed out"):
        await agy._run_cli(["-c", "import time; time.sleep(60)"], cwd=str(tmp_path), timeout=0.1)
