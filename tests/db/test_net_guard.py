"""SSRF: the address is checked, not the string.

Acceptance criterion from the roadmap: tests for localhost, private IP, the
metadata endpoint, and redirects. A check that reads the URL as text fails all
of these, because `127.1`, `0x7f000001` and `[::ffff:127.0.0.1]` are the same
destination with different spellings.
"""

from __future__ import annotations

import pytest

from deeptutor.services import net_guard as G


def _rule(url, **kwargs):
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_url(url, **kwargs)
    return exc.value.rule


# ---------------------------------------------------------------------------
# The four cases the roadmap names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/v1", "http://127.0.0.1:8080/v1", "http://localhost/v1", "http://[::1]/v1"],
)
def test_localhost_is_blocked(url):
    assert _rule(url) == "loopback"


@pytest.mark.parametrize("url", ["http://10.0.0.5/v1", "http://192.168.1.10/v1", "http://172.16.0.1/v1"])
def test_private_ranges_are_blocked(url):
    assert _rule(url) == "private_range"


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://169.254.170.2/v2/credentials",
        "http://100.100.100.200/latest/meta-data/",
        "http://[fd00:ec2::254]/latest/meta-data/",
    ],
)
def test_cloud_metadata_is_blocked(url):
    """The highest-value SSRF target: it hands out instance credentials."""
    assert _rule(url) == "metadata_endpoint"


def test_a_forbidden_address_beats_a_friendly_scheme():
    """https to the metadata service is still the metadata service."""
    assert _rule("https://169.254.169.254/") == "metadata_endpoint"


# ---------------------------------------------------------------------------
# Spellings of the same destination
# ---------------------------------------------------------------------------


def test_ipv4_mapped_ipv6_loopback_is_blocked():
    """`::ffff:127.0.0.1` is loopback wearing a different hat."""
    assert _rule("http://[::ffff:127.0.0.1]/v1") == "loopback"


def test_link_local_is_blocked():
    assert _rule("http://169.254.1.1/v1") in {"link_local", "metadata_endpoint"}


def test_unspecified_address_is_blocked():
    assert _rule("http://0.0.0.0/v1") in {"unspecified", "loopback", "private_range"}


# ---------------------------------------------------------------------------
# Schemes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com/", "ftp://example.com/"])
def test_non_http_schemes_are_blocked(url):
    assert _rule(url) == "forbidden_scheme"


def test_an_empty_url_is_refused():
    assert _rule("") == "empty_url"
    assert _rule("   ") == "empty_url"


def test_a_url_with_no_host_is_refused():
    assert _rule("http:///v1") == "no_host"


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_an_unresolvable_name_is_refused():
    """A name that does not resolve now cannot be validated for later."""
    assert _rule("http://nonexistent.invalid/v1") == "unresolvable"


# ---------------------------------------------------------------------------
# Allow-list
# ---------------------------------------------------------------------------


def test_an_allow_list_refuses_anything_off_it():
    assert _rule("https://openrouter.ai/api/v1", allow_hosts=frozenset({"other.example"})) == (
        "host_not_allowed"
    )


def test_a_public_host_passes():
    resolution = G.check_url("https://openrouter.ai/api/v1")
    assert resolution.host == "openrouter.ai"
    assert resolution.port == 443
    assert resolution.addresses, "the checked addresses must be returned"


def test_the_port_defaults_by_scheme():
    assert G.check_url("https://openrouter.ai/").port == 443
    assert G.check_url("http://example.com/").port == 80


def test_an_explicit_port_is_kept():
    assert G.check_url("https://example.com:8443/v1").port == 8443


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------


def test_a_redirect_to_metadata_is_blocked():
    """The second hop is a destination nobody vetted."""
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_redirect("http://169.254.169.254/latest/", original="https://api.example.com/x")
    assert exc.value.rule == "metadata_endpoint"


def test_a_redirect_to_loopback_is_blocked():
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_redirect("http://127.0.0.1:6379/", original="https://api.example.com/x")
    assert exc.value.rule == "loopback"


def test_a_redirect_is_checked_as_strictly_as_the_original():
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_redirect(
            "https://evil.example/", original="https://ok.example/", allow_hosts=frozenset({"ok.example"})
        )
    assert exc.value.rule == "host_not_allowed"


def test_a_relative_redirect_is_refused_rather_than_guessed():
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_redirect("/latest/meta-data/", original="https://api.example.com/x")
    assert exc.value.rule == "relative_redirect"


def test_an_empty_redirect_is_refused():
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_redirect("", original="https://api.example.com/x")
    assert exc.value.rule == "empty_redirect"


# ---------------------------------------------------------------------------
# The refusal is explainable
# ---------------------------------------------------------------------------


def test_a_refusal_says_which_rule_and_which_target():
    with pytest.raises(G.BlockedTarget) as exc:
        G.check_url("http://169.254.169.254/")
    detail = exc.value.as_dict()
    assert detail["rule"] == "metadata_endpoint"
    assert "169.254.169.254" in detail["message"]
    assert detail["target"] == "http://169.254.169.254/"
