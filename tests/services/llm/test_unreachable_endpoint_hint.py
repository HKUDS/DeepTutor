"""A refused connection to a self-hosted model must name its own cause.

"Unable to reach the model provider. Please retry." plus an ``httpcore
.ConnectError`` traceback is everything a local-Ollama user was told, and it
does not distinguish "the server is not running" from "you are in a container,
where localhost is the container".
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm import utils as llm_utils
from deeptutor.services.llm.utils import unreachable_endpoint_hint


@pytest.mark.parametrize(
    "base_url",
    ["https://api.openai.com/v1", "https://api.deepseek.com", "", None],
)
def test_cloud_and_missing_endpoints_get_no_hint(base_url: str | None) -> None:
    assert unreachable_endpoint_hint(base_url) == ""


def test_local_endpoint_outside_a_container_points_at_the_server(monkeypatch) -> None:
    monkeypatch.setattr(llm_utils, "running_in_container", lambda: False)

    hint = unreachable_endpoint_hint("http://localhost:11434/v1")

    assert "localhost:11434" in hint
    assert "ollama serve" in hint
    assert "host.docker.internal" not in hint


def test_loopback_inside_a_container_points_at_the_host(monkeypatch) -> None:
    monkeypatch.setattr(llm_utils, "running_in_container", lambda: True)

    hint = unreachable_endpoint_hint("http://127.0.0.1:11434/v1")

    assert "host.docker.internal:11434" in hint


def test_a_host_gateway_url_is_not_told_to_use_the_gateway(monkeypatch) -> None:
    """Already on ``host.docker.internal``: the container advice is wrong here."""
    monkeypatch.setattr(llm_utils, "running_in_container", lambda: True)

    hint = unreachable_endpoint_hint("http://host.docker.internal:11434/v1")

    assert "host.docker.internal:11434" in hint
    assert "container itself" not in hint
