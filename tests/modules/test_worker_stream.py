"""A real worker must yield before exit and be reaped when the turn stops."""

import asyncio
import os
from pathlib import Path
import sys

import pytest

from deeptutor.plugins.runtime import _WorkerClient


def worker(tmp_path, source):
    package = tmp_path / "fixture_worker"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "entry.py").write_text(source)
    return _WorkerClient(
        python_path=Path(sys.executable),
        venv_path=tmp_path,
        module="fixture_worker.entry",
        permissions={},
    )


@pytest.mark.asyncio
async def test_events_are_live_and_cancel_reaps_worker(tmp_path):
    client = worker(
        tmp_path,
        """import json,os,sys,time
json.loads(sys.stdin.read())
print(json.dumps({"kind":"event","event":{"type":"content","content":str(os.getpid())}}),flush=True)
time.sleep(60)
""",
    )
    stream = client.stream("run_capability", {})
    event = await asyncio.wait_for(anext(stream), timeout=5)
    pid = int(event["content"])
    os.kill(pid, 0)
    await asyncio.wait_for(stream.aclose(), timeout=5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_complete_stream_and_guard_rechecked(tmp_path):
    client = worker(
        tmp_path,
        """import json,sys
json.loads(sys.stdin.read())
print(json.dumps({"kind":"event","event":{"type":"content","content":"hello"}}),flush=True)
print(json.dumps({"kind":"complete"}),flush=True)
""",
    )
    checked = []
    client.guard = lambda: checked.append(True)
    assert [row["content"] async for row in client.stream("run_capability", {})] == ["hello"]
    assert len(checked) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output", ["", "not-json", "{}", '{"kind":"event","event":{}}', '{"kind":"complete"}\n{}']
)
async def test_malformed_or_truncated_stream_fails(tmp_path, output):
    ready = tmp_path / "pid"
    client = worker(
        tmp_path,
        f"import os,sys\nfrom pathlib import Path\nsys.stdin.read()\n"
        f"Path({str(ready)!r}).write_text(str(os.getpid()))\nprint({output!r},flush=True)\n",
    )
    with pytest.raises(ExceptionGroup):
        async with asyncio.timeout(5):
            async for _ in client.stream("run_capability", {}):
                pass
    with pytest.raises(ProcessLookupError):
        os.kill(int(ready.read_text()), 0)


@pytest.mark.asyncio
async def test_legacy_buffered_worker_cancellation_reaps_process(tmp_path):
    ready = tmp_path / "pid"
    client = worker(
        tmp_path,
        f"""import json,os,sys,time
from pathlib import Path
json.loads(sys.stdin.read())
Path({str(ready)!r}).write_text(str(os.getpid()))
time.sleep(60)
""",
    )
    task = asyncio.create_task(client.request_async("run_capability", {}))
    async with asyncio.timeout(5):
        while not ready.exists():
            await asyncio.sleep(0.01)
    pid = int(ready.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
