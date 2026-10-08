"""Native subprocess output must survive large, message-granular frames."""

import asyncio
import sys

import pytest

from deeptutor.services.subagent.openclaw import OpenClawBackend
from deeptutor.services.subagent.process import stream_process_lines


@pytest.mark.asyncio
async def test_large_native_lines_preserve_both_channels_and_final_fragment():
    text = "学习" * 40000
    script = (
        "import sys; "
        "sys.stdout.buffer.write(('学习' * 40000 + '\\n').encode()); "
        "sys.stdout.flush(); sys.stderr.write('diagnostic\\n'); "
        "sys.stderr.flush(); sys.stdout.buffer.write('尾部'.encode()); sys.stdout.flush()"
    )

    async def collect():
        return [item async for item in stream_process_lines([sys.executable, "-c", script])]

    # The unfixed reader can stop draining and leave the child blocked on its pipe.
    output = await asyncio.wait_for(collect(), timeout=5)
    assert [line for channel, line in output if channel == "stdout"] == [text, "尾部"]
    assert ("stderr", "diagnostic") in output
    assert output[-1] == ("exit", "0")


@pytest.mark.asyncio
async def test_openclaw_receives_large_native_json_answer(monkeypatch):
    answer = "x" * 100000
    script = (
        "import json; print(json.dumps({'status': 'ok', "
        "'result': {'payloads': [{'text': 'x' * 100000}]}}))"
    )
    backend = OpenClawBackend()
    monkeypatch.setattr(
        backend,
        "_build_command",
        lambda *args, **kwargs: [sys.executable, "-c", script],
    )
    events = []

    async def on_event(event):
        events.append(event)

    result = await asyncio.wait_for(backend.consult("question", on_event=on_event), timeout=5)
    assert result.success, result.error
    assert result.final_text == answer
    assert any(event.text == answer for event in events)
