"""MCP credentials: stored apart from the config, never echoed, resolved late."""

from __future__ import annotations

from pathlib import Path
import stat
import sys

import pytest

from deeptutor.services.mcp.secrets import (
    configured_fields,
    delete_secrets,
    resolve_references,
    resolve_url_references,
    secret_reference,
    store_secrets,
)


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    return root


def _secret_files(system_root: Path) -> list[Path]:
    return [p for p in system_root.rglob("*.json") if p.is_file()]


def test_values_land_outside_every_sandbox_mounted_tree(system_root: Path) -> None:
    store_secrets("u_ada", "notion", {"api_key": "sk-live-1"})
    files = _secret_files(system_root)
    assert files, "a secret must be written somewhere"
    for path in files:
        assert "users" not in path.parts
        assert "workspace" not in path.parts


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_secrets_file_is_owner_only(system_root: Path) -> None:
    store_secrets("u_ada", "notion", {"api_key": "sk-live-1"})
    path = _secret_files(system_root)[0]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_configured_fields_reports_presence_not_values(system_root: Path) -> None:
    store_secrets("u_ada", "notion", {"api_key": "sk-live-1", "workspace": "w1"})
    assert configured_fields("u_ada", "notion") == {"api_key", "workspace"}


def test_a_partial_edit_does_not_clear_the_other_fields(system_root: Path) -> None:
    """Rotating one key of three must not silently drop the rest."""
    store_secrets("u_ada", "svc", {"a": "1", "b": "2"})
    store_secrets("u_ada", "svc", {"a": "9"})
    assert configured_fields("u_ada", "svc") == {"a", "b"}
    assert resolve_references("u_ada", secret_reference("svc", "a")) == "9"
    assert resolve_references("u_ada", secret_reference("svc", "b")) == "2"


def test_an_empty_string_clears_a_field(system_root: Path) -> None:
    store_secrets("u_ada", "svc", {"a": "1", "b": "2"})
    store_secrets("u_ada", "svc", {"a": ""})
    assert configured_fields("u_ada", "svc") == {"b"}


def test_references_resolve_at_every_depth_a_credential_is_injected(system_root: Path) -> None:
    """env, headers, args and a url query parameter are all real injection sites."""
    store_secrets("u_ada", "svc", {"key": "sk-1"})
    payload = {
        "env": {"API_KEY": secret_reference("svc", "key")},
        "headers": {"Authorization": secret_reference("svc", "key")},
        "args": ["--token", secret_reference("svc", "key")],
        "url": "https://x.example/mcp",
        "tool_timeout": 30,
    }

    resolved = resolve_references("u_ada", payload)

    assert resolved["env"]["API_KEY"] == "sk-1"
    assert resolved["headers"]["Authorization"] == "sk-1"
    assert resolved["args"] == ["--token", "sk-1"]
    assert resolved["url"] == "https://x.example/mcp"
    assert resolved["tool_timeout"] == 30


def test_one_owners_reference_cannot_read_anothers_value(system_root: Path) -> None:
    store_secrets("u_victim", "svc", {"key": "victim-token"})
    resolved = resolve_references("u_attacker", secret_reference("svc", "key"))
    assert resolved == ""


def test_a_missing_value_resolves_empty_rather_than_leaking_the_reference(
    system_root: Path,
) -> None:
    """Sending the literal ``${secret:...}`` upstream would be worse.

    The server then fails its own authentication with a message the user can act
    on, instead of a provider logging a string that looks like a template bug.
    """
    assert resolve_references("u_ada", secret_reference("svc", "absent")) == ""


def test_non_reference_strings_pass_through_untouched(system_root: Path) -> None:
    """A reference inside arbitrary text is deliberately not substituted.

    A partial match has no defensible boundary, so "is this value a credential?"
    would stop being answerable. The URL case, where the boundary *is* defined,
    has its own entry point — see the tests below.
    """
    for value in ("plain", "${secret:}", "${secret:svc}", "prefix ${secret:svc/key}"):
        assert resolve_references("u_ada", value) == value


def test_a_query_parameter_credential_resolves(system_root: Path) -> None:
    """Several hosted services authenticate by query parameter, not header.

    Their stored url is ``…?apiKey=${secret:…}``, which is not a whole-value
    reference — so without component-wise resolution the literal
    ``${secret:...}`` would be transmitted to the vendor, which is precisely the
    outcome this module exists to prevent.
    """
    store_secrets("u_ada", "tavily", {"api_key": "tvly-1"})
    url = f"https://mcp.tavily.com/mcp/?tavilyApiKey={secret_reference('tavily', 'api_key')}"

    resolved = resolve_url_references("u_ada", url)

    assert "${secret:" not in resolved
    assert "tavilyApiKey=tvly-1" in resolved


def test_url_resolution_preserves_the_other_query_parameters(system_root: Path) -> None:
    store_secrets("u_ada", "svc", {"key": "k1"})
    url = f"https://h.example/mcp?a=1&key={secret_reference('svc', 'key')}&b=2"

    resolved = resolve_url_references("u_ada", url)

    assert "a=1" in resolved and "b=2" in resolved
    assert "key=k1" in resolved


def test_a_token_needing_escaping_is_encoded_into_the_query(system_root: Path) -> None:
    store_secrets("u_ada", "svc", {"key": "a b&c=d"})
    url = f"https://h.example/mcp?key={secret_reference('svc', 'key')}"

    resolved = resolve_url_references("u_ada", url)

    # Re-encoded, so a token containing separators cannot forge extra parameters.
    assert "a+b%26c%3Dd" in resolved
    from urllib.parse import parse_qsl, urlsplit

    assert dict(parse_qsl(urlsplit(resolved).query)) == {"key": "a b&c=d"}


def test_a_url_without_references_is_returned_unchanged(system_root: Path) -> None:
    url = "https://h.example/mcp?a=1"
    assert resolve_url_references("u_ada", url) is url


def test_a_url_reference_cannot_read_another_owners_value(system_root: Path) -> None:
    store_secrets("u_victim", "svc", {"key": "victim-token"})
    url = f"https://h.example/mcp?key={secret_reference('svc', 'key')}"
    assert "victim-token" not in resolve_url_references("u_attacker", url)


def test_delete_removes_the_whole_store(system_root: Path) -> None:
    store_secrets("u_ada", "svc", {"key": "sk-1"})
    delete_secrets("u_ada", "svc")
    assert configured_fields("u_ada", "svc") == set()


def test_an_unsafe_server_name_cannot_escape_the_secrets_directory(system_root: Path) -> None:
    with pytest.raises(ValueError):
        store_secrets("u_ada", "../../escape", {"key": "x"})
