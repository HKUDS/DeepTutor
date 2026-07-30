"""Running a command as an argument vector rather than as a shell string.

A CLI app's arguments come from the model, so the program is fixed and the
arguments are not — the one exec path where a shell buys nothing and costs
everything. Two properties are pinned here:

* ``argv`` and ``command`` always describe the same execution, enforced at
  construction so no caller can set one and forget the other;
* every backend honours ``argv``, and the shell string that travels alongside it
  (for a runner image that predates the field) is quoted such that a hostile
  argument is still just an argument.
"""

from __future__ import annotations

import asyncio
import shlex

import pytest

from deeptutor.services.sandbox.backends import (
    BwrapBackend,
    RestrictedSubprocessBackend,
    RunnerSidecarBackend,
)
from deeptutor.services.sandbox.runner import server as runner_server
from deeptutor.services.sandbox.spec import ExecRequest

#: Arguments that would each do something different if a shell saw them.
HOSTILE_ARGS = [
    "; rm -rf /",
    "$(whoami)",
    "`id`",
    "a b c",
    "--flag=value with spaces",
    "'quoted'",
    '"double"',
    "back\\slash",
    "new\nline",
    "$HOME",
    "&& touch /tmp/pwned",
    "|tee /tmp/pwned",
]


def test_of_argv_derives_the_shell_form() -> None:
    request = ExecRequest.of_argv(["/bin/echo", "a b", "c;d"])
    assert request.argv == ("/bin/echo", "a b", "c;d")
    assert request.command == shlex.join(["/bin/echo", "a b", "c;d"])


def test_the_two_spellings_cannot_be_made_to_disagree() -> None:
    """Setting one and forgetting the other would run different things on
    different runner images — silently, and only during a rolling deploy."""
    with pytest.raises(ValueError, match="of_argv"):
        ExecRequest(command="echo hello", argv=("echo", "goodbye"))


def test_an_empty_vector_is_refused() -> None:
    with pytest.raises(ValueError):
        ExecRequest.of_argv([])


def test_a_plain_shell_request_still_works() -> None:
    request = ExecRequest(command="echo hi")
    assert request.argv == ()


# ── the backends ──────────────────────────────────────────────────────────


def test_bwrap_execs_the_vector_with_no_shell_between() -> None:
    backend = BwrapBackend()
    argv = backend._build_argv(ExecRequest.of_argv(["/app/bin/tool", "sub", "; rm -rf /"]))

    assert "/bin/sh" not in argv
    assert argv[-3:] == ["/app/bin/tool", "sub", "; rm -rf /"]
    assert argv[-4] == "--", "bwrap needs the separator or it would parse the argv as its own flags"


def test_bwrap_keeps_using_a_shell_for_a_shell_request() -> None:
    backend = BwrapBackend()
    argv = backend._build_argv(ExecRequest(command="ls | wc -l"))
    assert argv[-3:] == ["/bin/sh", "-c", "ls | wc -l"]


def test_the_sidecar_sends_both_spellings() -> None:
    """An older runner ignores ``argv``; a newer one prefers it. Both must be
    present or the protocol only works in one deploy direction."""
    captured: dict[str, object] = {}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def post(self, url: str, json: dict) -> object:
            captured.update(json)

            class _Response:
                @staticmethod
                def raise_for_status() -> None:
                    return None

                @staticmethod
                def json() -> dict:
                    return {"stdout": "", "stderr": "", "exit_code": 0}

            return _Response()

    backend = RunnerSidecarBackend("http://runner:8900")
    import deeptutor.services.sandbox.backends as backends_module

    original = backends_module.httpx.AsyncClient
    backends_module.httpx.AsyncClient = lambda **_kwargs: _Client()  # type: ignore[assignment]
    try:
        asyncio.run(backend.exec(ExecRequest.of_argv(["/bin/echo", "a b"])))
    finally:
        backends_module.httpx.AsyncClient = original  # type: ignore[assignment]

    assert captured["argv"] == ["/bin/echo", "a b"]
    assert captured["command"] == shlex.join(["/bin/echo", "a b"])


@pytest.mark.parametrize("argument", HOSTILE_ARGS)
def test_the_local_backend_passes_a_hostile_argument_through_untouched(argument: str) -> None:
    """The argument arrives as data. Nothing expands, splits, or executes."""
    backend = RestrictedSubprocessBackend()
    request = ExecRequest.of_argv(
        ["/usr/bin/env", "python3", "-c", "import sys; print(sys.argv[1], end='')", argument]
    )
    result = asyncio.run(backend.exec(request))

    assert result.error == ""
    assert result.stdout == argument


@pytest.mark.parametrize("argument", HOSTILE_ARGS)
def test_the_shell_fallback_is_quoted_well_enough_to_be_equivalent(argument: str) -> None:
    """The compatibility path has to be *correct*, not merely present: on an old
    runner image this string is what actually executes."""
    request = ExecRequest.of_argv(
        ["/usr/bin/env", "python3", "-c", "import sys; print(sys.argv[1], end='')", argument]
    )
    # Exactly what a pre-argv runner does with the payload: shell out to it.
    backend = RestrictedSubprocessBackend()
    via_shell = asyncio.run(backend.exec(ExecRequest(command=request.command)))

    assert via_shell.error == ""
    assert via_shell.stdout == argument


# ── the runner's own end of the wire ──────────────────────────────────────


def test_the_runner_prefers_argv_over_the_shell_string() -> None:
    """Sent both, it must run the vector — that is what makes the arguments data."""
    result = runner_server.execute(
        {
            "command": "/bin/echo shell-form",
            "argv": ["/bin/echo", "argv-form"],
            "limits": {"timeout_s": 10},
        }
    )
    assert result["error"] == ""
    assert result["stdout"].strip() == "argv-form"


def test_the_runner_runs_the_shell_string_when_no_argv_is_sent() -> None:
    result = runner_server.execute({"command": "echo a && echo b", "limits": {"timeout_s": 10}})
    assert result["stdout"].split() == ["a", "b"]


def test_the_runner_does_not_expand_a_hostile_argv_element() -> None:
    result = runner_server.execute(
        {
            "command": "unused",
            "argv": ["/bin/echo", "$HOME; rm -rf /"],
            "limits": {"timeout_s": 10},
        }
    )
    assert result["stdout"].strip() == "$HOME; rm -rf /"


@pytest.mark.parametrize("bad", [{"argv": "echo hi"}, {"argv": ["ok", 7]}])
def test_the_runner_refuses_a_malformed_argv(bad: dict) -> None:
    result = runner_server.execute({"command": "echo hi", **bad, "limits": {"timeout_s": 5}})
    assert "argv" in result["error"]
