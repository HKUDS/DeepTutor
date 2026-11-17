"""Production guards (Phase 2 acceptance: no unsafe defaults in production).

The roadmap's phrase is «Production با default credential بالا نمی‌آید». The
codebase ships no default password, so the equivalent hazards are the ones in
``guards.py``: auth off, a mock SMS provider, and an unmanaged signing secret.

Each is tested in both environments, because a guard that fires in development
would make the product unusable and a guard that never fires protects nothing.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user.guards import (
    Problem,
    assert_safe_to_start,
    check_configuration,
    is_production,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start every test from a known environment."""
    for name in ("DEEPTUTOR_ENV", "APP_ENV", "ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DEEPTUTOR_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("DEEPTUTOR_SMS_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPTUTOR_AUTH_SECRET", raising=False)


def codes(problems: list[Problem]) -> set[str]:
    return {problem.code for problem in problems}


# ------------------------------------------------------------ environment


def test_unset_environment_is_not_production() -> None:
    assert is_production() is False


@pytest.mark.parametrize("value", ["production", "prod", "PRODUCTION", " Prod "])
def test_production_spellings_are_recognised(monkeypatch, value: str) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", value)
    assert is_production() is True


@pytest.mark.parametrize("value", ["development", "dev", "staging", "test"])
def test_non_production_environments(monkeypatch, value: str) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", value)
    assert is_production() is False


def test_deeptutor_env_wins_over_the_generic_name(monkeypatch) -> None:
    """An unrelated ``ENV`` in the shell must not decide our posture."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_ENV", "development")
    assert is_production() is False


# --------------------------------------------------------------- the guards


def test_production_with_auth_off_is_a_fatal_problem(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "false")
    assert "auth_disabled_in_production" in codes(check_configuration())


def test_production_with_auth_on_clears_that_problem(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "kavenegar")
    assert "auth_disabled_in_production" not in codes(check_configuration())


def test_production_with_mock_sms_is_a_fatal_problem(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "mock")
    assert "mock_sms_in_production" in codes(check_configuration())


def test_missing_provider_defaults_to_the_mock_and_is_caught(monkeypatch) -> None:
    """The default is the dangerous value, so it must be the one checked."""
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "true")
    assert "mock_sms_in_production" in codes(check_configuration())


def test_development_reports_nothing(monkeypatch) -> None:
    """A guard that blocks local development would be switched off entirely."""
    monkeypatch.setenv("DEEPTUTOR_ENV", "development")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "false")
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "mock")
    assert check_configuration() == []


# -------------------------------------------------------------- the start-up


def test_assert_raises_on_a_fatal_problem(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "false")

    with pytest.raises(RuntimeError) as exc:
        assert_safe_to_start()

    # The message has to name the problem and the variable, or an operator
    # reads a stack trace and learns nothing.
    assert "auth_disabled_in_production" in str(exc.value)


def test_assert_lists_every_fatal_problem_at_once(monkeypatch) -> None:
    """One restart per problem is how deployments take all afternoon."""
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "false")
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "mock")

    with pytest.raises(RuntimeError) as exc:
        assert_safe_to_start()

    message = str(exc.value)
    assert "auth_disabled_in_production" in message
    assert "mock_sms_in_production" in message


def test_non_fatal_problems_do_not_block_start(monkeypatch) -> None:
    """The secret-from-file warning is advice, not a reason to refuse."""
    monkeypatch.setenv("DEEPTUTOR_ENV", "production")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "kavenegar")

    assert_safe_to_start()  # must not raise


def test_assert_passes_in_development(monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_ENV", "development")
    assert_safe_to_start()
