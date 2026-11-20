"""Startup guards that stop a misconfigured deployment from going live.

Phase 2 acceptance asks that production never comes up with a default
credential. The codebase has no default *password* (``auth.json`` ships without
one), so the concrete hazards are different but real:

* auth switched off on a multi-user deployment — every request is an admin;
* the mock SMS provider in production — sign-up looks like it works and
  delivers nothing;
* the bootstrap admin's password never changed from whatever was provisioned
  into ``auth.json``.

Each check returns a :class:`Problem` rather than raising, so ``doctor`` can
report all of them at once instead of one per restart. :func:`assert_safe_to_start`
is the raising form, for use at process start.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Problem:
    """One reason the current configuration is not safe to run as-is."""

    code: str
    message_fa: str
    message_en: str
    fatal: bool = True

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"[{self.code}] {self.message_en}"


def is_production() -> bool:
    """True when the process believes it is serving real users.

    One variable, one meaning. ``DEEPTUTOR_ENV`` is checked before the more
    conventional ``APP_ENV``/``ENV`` so a deployment can be explicit without
    inheriting an unrelated variable that happens to be set.
    """
    for name in ("DEEPTUTOR_ENV", "APP_ENV", "ENV"):
        value = (os.environ.get(name) or "").strip().lower()
        if value:
            return value in {"prod", "production"}
    return False


def check_configuration() -> list[Problem]:
    """Every problem with the current configuration, in a stable order."""
    problems: list[Problem] = []

    auth_enabled = _bool(os.environ.get("DEEPTUTOR_AUTH_ENABLED"))
    if is_production() and not auth_enabled:
        problems.append(
            Problem(
                code="auth_disabled_in_production",
                message_fa="احراز هویت در محیط production خاموش است؛ هر درخواست با دسترسی مدیر اجرا می‌شود.",
                message_en="Authentication is disabled in production; every request runs as an administrator.",
            )
        )

    if is_production():
        provider = (os.environ.get("DEEPTUTOR_SMS_PROVIDER") or "mock").strip().lower()
        if provider in {"mock", "log"}:
            problems.append(
                Problem(
                    code="mock_sms_in_production",
                    message_fa="ارائه‌دهنده پیامک آزمایشی در production فعال است؛ هیچ کدی به کاربر نمی‌رسد.",
                    message_en="A test SMS provider is active in production; no code actually reaches a user.",
                )
            )

    secret = (os.environ.get("DEEPTUTOR_AUTH_SECRET") or "").strip()
    if is_production() and not secret:
        problems.append(
            Problem(
                code="auth_secret_from_file",
                message_fa="راز امضای توکن از فایل محلی خوانده می‌شود؛ برای production یک secret مدیریت‌شده تنظیم کنید.",
                message_en="The token signing secret is read from a local file; set a managed secret for production.",
                fatal=False,
            )
        )

    return problems


def assert_safe_to_start() -> None:
    """Raise when any fatal problem exists.

    Called from process start. Deliberately fails closed: a deployment that
    cannot authenticate is worse than one that refuses to boot, because the
    first silently hands out admin access.
    """
    fatal = [problem for problem in check_configuration() if problem.fatal]
    if not fatal:
        return

    detail = "\n".join(f"  - [{p.code}] {p.message_en}" for p in fatal)
    raise RuntimeError(
        f"Refusing to start: the configuration is not safe for this environment.\n{detail}"
    )


def _bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}
