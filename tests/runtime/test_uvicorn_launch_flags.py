"""Guards that every uvicorn launch point wires the shared serving flags.

The browser never reaches the backend directly: the SPA server rewrites
``/api/*`` and forwards over httpx, which reaps idle pooled sockets on its own
timer. uvicorn's ``timeout_keep_alive`` must stay well above that pool so both
ends do not race to close the same socket. A FIN landing on a socket the pool
was handing to a new request used to kill it with ``ECONNRESET``, which the
proxy turned into a 500 ("Failed to load sessions" in the UI).
``--timeout-keep-alive`` fixes it, and ``--ws-max-size`` has the same shape:
correct only if *every* launch point passes it, and DeepTutor has five (two
Dockerfile stages, the ``deeptutor start`` launcher, the CLI, run_server). A
launch point that forgets one reintroduces the bug for whoever starts the
backend that way, which no per-module test would catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# (path, marker anchoring the uvicorn invocation, flag spellings for this style)
_PYTHON_FLAGS = ("ws_max_size", "timeout_keep_alive")
_CLI_FLAGS = ("--ws-max-size", "--timeout-keep-alive")
_LAUNCH_POINTS = [
    ("deeptutor/runtime/launcher.py", '"uvicorn",', _CLI_FLAGS),
    ("deeptutor/api/run_server.py", "uvicorn.run(", _PYTHON_FLAGS),
    ("deeptutor_cli/main.py", "uvicorn.run(", _PYTHON_FLAGS),
]


@pytest.mark.parametrize(("relpath", "marker", "flags"), _LAUNCH_POINTS)
def test_python_launch_point_wires_serving_flags(
    relpath: str, marker: str, flags: tuple[str, ...]
) -> None:
    source = (_REPO / relpath).read_text(encoding="utf-8")
    assert marker in source, f"{relpath} no longer launches uvicorn as expected"
    for flag in flags:
        assert flag in source, f"{relpath} launches uvicorn without {flag}"


def test_dockerfile_launch_points_wire_serving_flags() -> None:
    """Both container stages (production entrypoint + dev supervisord)."""
    lines = [
        line
        for line in (_REPO / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if "-m uvicorn deeptutor.api.main:app" in line
    ]
    assert len(lines) == 2, f"expected 2 Dockerfile uvicorn launches, found {len(lines)}"
    for line in lines:
        for flag in _CLI_FLAGS:
            assert flag in line, f"Dockerfile launches uvicorn without {flag}: {line.strip()[:80]}"


def test_keep_alive_outlasts_the_proxy_socket_reaper() -> None:
    """Must stay clear of the frontend proxy's idle socket reaper.

    Matching it is what caused the collision, so a value anywhere near the
    proxy pool timeout puts the two timers back in contention.
    """
    from deeptutor.services.config import HTTP_KEEP_ALIVE_TIMEOUT

    assert HTTP_KEEP_ALIVE_TIMEOUT >= 60, "too close to the proxy's 5s socket reaper"
