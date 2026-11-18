"""Resolving a caller's enrolment, so no endpoint has to trust a query string.

The problem this exists to prevent
----------------------------------
Phase 4 and Phase 5 established a hard rule: retrieval is scoped to an
enrolment the *server* resolved, and there is no parameter that widens it
(D-031). The examination endpoints broke that rule in a quieter way -- they took
`grade_number` and `major_code` from the request and used them directly, so a
grade-7 student could sit a grade-12 exam simply by passing 12. The docstrings
claimed the auth layer supplied those values, but nothing checked, and a comment
is not an access control.

The fix is not "validate the grade against the user" scattered across handlers.
It is one function that every scoped endpoint calls, so that "the scope came
from somewhere trustworthy" is a property of the code path rather than a
convention a future handler can forget.

How the enrolment is resolved
-----------------------------
When authentication is enabled, the caller's identity comes from the session and
the enrolment from their stored profile. When it is disabled -- the local
development configuration, `AUTH_ENABLED=false` -- there is no session to read,
and the caller may supply the enrolment explicitly. That is a real dev
affordance, but it must not be invisible: `resolve_enrolment` reports which mode
it used, and endpoints that receive an unverified scope are marked as such in
their response so nobody mistakes a dev bypass for production behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from deeptutor.db.connection import Database


class ScopeError(RuntimeError):
    """The caller's scope could not be established, or does not reach the target."""

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


@dataclass(frozen=True)
class Enrolment:
    """Who the caller is and what they are allowed to see."""

    user_id: str
    grade_number: int | None
    major_code: str | None
    #: True when the values were supplied by the client because authentication
    #: is off. Never true in production; surfaced in responses so a dev
    #: deployment cannot be mistaken for a scoped one.
    unverified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "grade_number": self.grade_number,
            "major_code": self.major_code,
            "unverified": self.unverified,
        }


def _auth_enabled() -> bool:
    """Whether real authentication is on.

    Reads the same ``AUTH_ENABLED`` setting the auth router uses, so there is
    one answer to "is this deployment authenticated" rather than two that can
    disagree. Imported lazily: this module is used by the repository layer too,
    which must not pull the FastAPI router graph in.
    """
    try:
        from deeptutor.services.config import load_auth_settings

        return bool(load_auth_settings().get("enabled"))
    except Exception:  # pragma: no cover - settings service unavailable
        return False


def caller_id(supplied: str | None = None) -> str:
    """The authoritative user id for this request.

    With authentication on, identity comes from the session and a supplied id is
    **discarded** -- accepting it would let any logged-in student act as any
    other by changing one field, which is the entire bug class this module
    exists to close.

    With authentication off there is no session, so the supplied id is all there
    is. That is the documented single-operator dev mode (``require_admin``
    already treats every request as admin in it), not a claim about production.
    """
    if not _auth_enabled():
        return str(supplied or "")

    try:
        from deeptutor.multi_user.context import get_current_user

        current = get_current_user()
    except Exception:  # pragma: no cover - no multi-user layer available
        return str(supplied or "")
    return str(current.id or "")


def resolve_enrolment(
    db: Database,
    *,
    user_id: str | None,
    grade_number: int | None = None,
    major_code: str | None = None,
) -> Enrolment:
    """Establish the caller's enrolment, in that order of authority.

    1. **The stored profile wins, always.** If the account has a grade on
       record, that grade is the enrolment -- authentication on or off, and a
       ``grade_number`` in the request is ignored. This is what makes the
       original hole impossible rather than merely unlikely: ``grade7_student``
       cannot be graded on a grade-12 paper by asking for it, because the
       number in the request is never read.
    2. **No profile, authentication on.** Refuse. A scoped endpoint with no
       verifiable scope has nothing to enforce, so it must not run.
    3. **No profile, authentication off.** This is the single-operator local
       configuration. The supplied values are used and the result is marked
       ``unverified`` so it travels with the response.

    Note what step 1 means for a claim: the client's value is *not compared*
    against the profile. A comparison would turn a useless field into an error,
    and callers would learn to keep sending it. It is discarded.
    """
    if not user_id:
        raise ScopeError("missing_user", "a user_id is required", field="user_id")

    stored = _stored_enrolment(db, str(user_id))
    if stored is not None:
        return stored

    if _auth_enabled():
        raise ScopeError(
            "missing_enrolment",
            "این حساب پایهٔ تحصیلی ثبت‌شده ندارد؛ ابتدا پروفایل را تکمیل کنید",
            field="grade_number",
        )
    return Enrolment(
        user_id=str(user_id),
        grade_number=int(grade_number) if grade_number is not None else None,
        major_code=major_code or None,
        unverified=True,
    )


def _stored_enrolment(db: Database, user_id: str) -> Enrolment | None:
    """The enrolment recorded on the account, or ``None`` if there is none."""
    from deeptutor.db.repositories.identity import IdentityRepository

    try:
        found = IdentityRepository(db).get_by_id(user_id)
    except Exception:  # pragma: no cover - no identity schema in this database
        return None
    if found is None:
        return None
    _key, record = found
    profile = record.get("learner_profile") or {}
    if isinstance(profile, str):
        import json

        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            return None
    if not isinstance(profile, dict) or profile.get("grade_number") is None:
        return None
    try:
        grade = int(profile["grade_number"])
    except (TypeError, ValueError) as exc:
        raise ScopeError(
            "invalid_enrolment",
            f"the stored grade {profile['grade_number']!r} is not a number",
            field="grade_number",
        ) from exc
    return Enrolment(
        user_id=user_id,
        grade_number=grade,
        major_code=profile.get("major_code") or None,
        unverified=False,
    )


def require_scope_reaches(
    enrolment: Enrolment,
    *,
    grade_number: int | None,
    major_code: str | None,
    what: str = "این آزمون",
) -> None:
    """Refuse when a scoped object is outside the caller's enrolment.

    Two rules, and the second is the one that is easy to get wrong:

    * a grade-scoped object must match the caller's grade exactly;
    * a major-scoped object is visible when the caller has no major *only if the
      object has no major either*. An exam restricted to ریاضی‌فیزیک is not
      open to a grade-7 student just because grade 7 has no tracks -- that
      reading is how a scope filter becomes decorative.
    """
    if grade_number is not None:
        if enrolment.grade_number is None:
            raise ScopeError(
                "scope_unverifiable",
                f"{what} برای پایهٔ {grade_number} است و پایهٔ شما مشخص نیست",
                field="grade_number",
            )
        if int(grade_number) != enrolment.grade_number:
            raise ScopeError(
                "scope_mismatch",
                f"{what} برای پایهٔ {grade_number} است و شما پایهٔ {enrolment.grade_number} هستید",
                field="grade_number",
            )
    if major_code is not None:
        if enrolment.major_code is None or major_code != enrolment.major_code:
            raise ScopeError(
                "scope_mismatch",
                f"{what} برای رشتهٔ {major_code} است و با رشتهٔ شما هم‌خوان نیست",
                field="major_code",
            )


def as_http(exc: ScopeError) -> HTTPException:
    """Map a scope failure to a 403.

    Not 404: the object is not secret -- it is listed publicly -- it is simply
    not open to this caller. A 404 here would be a lie that makes a scoping bug
    harder to diagnose.
    """
    return HTTPException(
        status_code=403,
        detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
    )
