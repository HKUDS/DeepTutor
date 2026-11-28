"""The SSRF policy knobs: declared Fake-IP ranges and the private-layer switch."""

from __future__ import annotations

import ipaddress

import pytest

from deeptutor.services import net_policy


@pytest.fixture(autouse=True)
def _isolated_policy(monkeypatch):
    """No real settings file, no inherited deployment env."""
    for name in (
        net_policy.SYNTHETIC_RANGES_ENV,
        net_policy.PROTECTION_ENABLED_ENV,
        *net_policy.COMPATIBLE_ENV_NAMES,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(net_policy, "_settings", lambda: {})


def test_parse_ranges_accepts_comma_string_and_lists() -> None:
    assert net_policy.parse_ranges("fd27:712::/32, 198.18.0.0/15") == (
        ipaddress.ip_network("fd27:712::/32"),
        ipaddress.ip_network("198.18.0.0/15"),
    )
    assert net_policy.parse_ranges(["10.0.0.0/8", ["192.168.0.0/16"]]) == (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    # Semicolons and newlines are separators too, because both are easy to
    # produce when hand-editing a settings file.
    assert net_policy.parse_ranges("10.0.0.0/8;\n172.16.0.0/12") == (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
    )


def test_parse_ranges_skips_junk_and_duplicates() -> None:
    assert net_policy.parse_ranges(["not-a-cidr", "10.0.0.0/8", "10.0.0.0/8", ""]) == (
        ipaddress.ip_network("10.0.0.0/8"),
    )
    assert net_policy.parse_ranges(None) == ()
    assert net_policy.parse_ranges("") == ()


def test_parse_ranges_keeps_host_bits_and_normalizes() -> None:
    # strict=False so ``10.1.2.3/8`` behaves like ``10.0.0.0/8`` instead of
    # raising on an operator's shorthand.
    assert net_policy.parse_ranges("10.1.2.3/8") == (ipaddress.ip_network("10.0.0.0/8"),)


def test_parse_bool_keeps_default_on_junk() -> None:
    assert net_policy.parse_bool("0", True) is False
    assert net_policy.parse_bool("false", True) is False
    assert net_policy.parse_bool("TRUE", False) is True
    assert net_policy.parse_bool("maybe", True) is True
    assert net_policy.parse_bool(None, True) is True


def test_is_ip_literal_and_normalize() -> None:
    assert net_policy.is_ip_literal("127.0.0.1")
    assert net_policy.is_ip_literal("[fd27:712::1]")
    assert not net_policy.is_ip_literal("gitmcp.io")
    assert net_policy.normalize_addr(ipaddress.ip_address("::ffff:10.0.0.1")) == (
        ipaddress.ip_address("10.0.0.1")
    )


def test_policy_defaults_leave_every_guard_unchanged() -> None:
    policy = net_policy.current_policy()

    assert policy.protection_enabled is True
    assert policy.synthetic == ()
    assert policy.allows_private() is False


def test_declared_ranges_come_from_env_and_the_legacy_name(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")
    assert net_policy.current_policy().synthetic == (ipaddress.ip_network("fd27:712::/32"),)

    monkeypatch.delenv(net_policy.SYNTHETIC_RANGES_ENV)
    monkeypatch.setenv(net_policy.COMPATIBLE_ENV_NAMES[0], "198.18.0.0/15")
    assert net_policy.current_policy().synthetic == (ipaddress.ip_network("198.18.0.0/15"),)


def test_protection_switch_reads_env(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "false")
    policy = net_policy.current_policy()

    assert policy.protection_enabled is False
    assert policy.allows_private() is True


def test_settings_are_used_when_env_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(
        net_policy,
        "_settings",
        lambda: {
            net_policy.PROTECTION_ENABLED_SETTING_KEY: False,
            net_policy.SETTING_KEY: ["fd27:712::/32"],
        },
    )
    policy = net_policy.current_policy()

    assert policy.protection_enabled is False
    assert policy.synthetic == (ipaddress.ip_network("fd27:712::/32"),)


def test_env_beats_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        net_policy,
        "_settings",
        lambda: {net_policy.PROTECTION_ENABLED_SETTING_KEY: False},
    )
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "1")

    assert net_policy.current_policy().protection_enabled is True


def test_unreadable_settings_never_break_a_guard(monkeypatch) -> None:
    import deeptutor.services.config.runtime_settings as runtime_settings

    def _explode():
        raise RuntimeError("settings service is not initialised")

    # The real ``_settings`` (not the autouse stub) must swallow the failure.
    monkeypatch.undo()
    monkeypatch.setattr(runtime_settings, "load_system_settings", _explode)

    policy = net_policy.current_policy()
    assert policy.protection_enabled is True
    assert policy.synthetic == ()


def test_always_refused_answers() -> None:
    for raw in (
        "127.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "169.254.169.254",
        "fd00:ec2::254",
        "100.100.100.200",
        "0.0.0.0",
        "fe80::1",
    ):
        assert net_policy.is_always_refused(ipaddress.ip_address(raw)), raw
    # Private-but-routable answers are a policy question, not a hard refusal.
    assert not net_policy.is_always_refused(ipaddress.ip_address("10.1.2.3"))
    assert not net_policy.is_always_refused(ipaddress.ip_address("fd27:712::1"))


def test_synthetic_answer_requires_a_hostname(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")

    assert net_policy.is_synthetic_answer(
        ipaddress.ip_address("fd27:712::c600:116b"), host="gitmcp.io"
    )
    # An IP literal never came from a resolver, so no proxy synthesised it.
    assert not net_policy.is_synthetic_answer(
        ipaddress.ip_address("fd27:712::c600:116b"), host="fd27:712::c600:116b"
    )


def test_synthetic_answer_never_covers_always_refused(monkeypatch) -> None:
    # Declaring the whole ULA block must not re-open loopback or metadata.
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fc00::/7,127.0.0.0/8")

    assert not net_policy.is_synthetic_answer(ipaddress.ip_address("::1"), host="x.example")
    assert not net_policy.is_synthetic_answer(ipaddress.ip_address("127.0.0.5"), host="x.example")
    assert net_policy.is_synthetic_answer(ipaddress.ip_address("fd00:abcd::1"), host="x.example")


def test_no_declared_range_means_no_exemption(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "198.18.0.0/15")

    assert not net_policy.is_synthetic_answer(ipaddress.ip_address("fd27:712::1"), host="gitmcp.io")
    assert net_policy.is_synthetic_answer(ipaddress.ip_address("198.18.0.1"), host="gitmcp.io")
