"""What an account may do, decided from its plan and its plan's expiry.

Why this module exists
----------------------
Phase 8 left `require_entitlement` as a parameter on `submit` that no caller
ever populated, and a `plan_expires_at` column that was written and never read.
The combination is a security-shaped hole rather than a missing feature: an
account whose plan expired ninety days ago was indistinguishable from one that
paid this morning, because nothing consulted the plan at all.

The rule this module enforces is the one that was missing: **entitlement is
closed by default**. An account with no plan, an unknown plan, or an expired
plan gets the base tier. It does not get everything because nobody said
otherwise.

Why a plan is a set of capabilities, not a label
------------------------------------------------
`plan_code` on the wallet was a free string. Anything could be written there and
anything would be believed. A plan that is a *label* cannot answer "may this
account render video?", so the answer was always yes; a plan that is a *set* can
answer it, and the answer is sometimes no.

Expiry is evaluated, not stored
-------------------------------
`plan_expires_at` in the past means the plan is over. This is computed at read
time from the timestamp and the clock rather than being flipped by a background
job, because a job that has not run yet must not grant access, and a row that
says "active" while its date has passed is a lie in the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from deeptutor.db.connection import Database

#: Capabilities a plan can grant. Named as surfaces rather than as job kinds so
#: a new media kind does not silently require a new capability; the mapping from
#: kind to capability lives in one place (`CAPABILITY_FOR_KIND`).
CAP_STUDIO = "studio"
CAP_MEDIA_VIDEO = "media.video"
CAP_MEDIA_AUDIO = "media.audio"
CAP_KNOWLEDGE_WRITE = "knowledge.write"
CAP_EXAM = "exam"
CAP_PARTNERS = "partners"

#: Which capability a media kind requires. Anything not listed needs CAP_STUDIO,
#: so adding a kind is a deliberate act rather than an accidental grant.
CAPABILITY_FOR_KIND: dict[str, str] = {
    "video_lesson": CAP_MEDIA_VIDEO,
    "audio_overview": CAP_MEDIA_AUDIO,
}

#: The base tier: what an account gets with no plan at all. This is the value
#: that must be conservative -- every account passes through it.
BASE_CAPABILITIES: frozenset[str] = frozenset({CAP_STUDIO})


def capability_for_kind(kind: str) -> str:
    """The capability a media kind needs. Unknown kinds need the base surface."""
    return CAPABILITY_FOR_KIND.get(str(kind or "").strip(), CAP_STUDIO)


@dataclass(frozen=True)
class Entitlement:
    """The account's effective rights, and how they were decided."""

    user_id: str
    plan_code: str
    capabilities: frozenset[str]
    #: "active" | "expired" | "missing_plan" | "unknown_plan" | "no_expiry"
    reason: str
    expires_at: datetime | None = None

    @property
    def is_paid(self) -> bool:
        return self.reason == "active"

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "plan_code": self.plan_code,
            "capabilities": sorted(self.capabilities),
            "reason": self.reason,
            "is_paid": self.is_paid,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True)
class Plan:
    """A purchasable plan, as stored."""

    code: str
    name: str
    capabilities: frozenset[str]
    duration_days: int
    token_quota: int
    price_toman: int = 0
    is_active: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "duration_days": self.duration_days,
            "token_quota": self.token_quota,
            "price_toman": self.price_toman,
            "is_active": self.is_active,
        }


def _parse_moment(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _capabilities_from(value: Any) -> frozenset[str]:
    """Parse the stored capability list, refusing anything unrecognised.

    A typo in a plan's capability list must not silently grant a surface, so
    unknown names are dropped rather than passed through. Dropping is the safe
    direction: the plan grants less than written, which is visible, rather than
    more, which is not.
    """
    if not value:
        return frozenset()
    if isinstance(value, str):
        items: Iterable[str] = (part.strip() for part in value.split(","))
    else:
        items = (str(part).strip() for part in value)
    known = {
        CAP_STUDIO,
        CAP_MEDIA_VIDEO,
        CAP_MEDIA_AUDIO,
        CAP_KNOWLEDGE_WRITE,
        CAP_EXAM,
        CAP_PARTNERS,
    }
    return frozenset(item for item in items if item in known)


def resolve(db: Database, user_id: str, *, now: datetime | None = None) -> Entitlement:
    """Decide what this account may do, right now.

    Reads the plan row and the wallet's expiry, and returns the effective set.
    Every failure mode degrades to :data:`BASE_CAPABILITIES` with a reason that
    says which one it was, so a support question has an answer.
    """
    moment = now or datetime.now(timezone.utc)
    with db.read() as conn:
        wallet = conn.query_one(
            "SELECT plan_code, plan_expires_at FROM user_wallets WHERE user_id = ?",
            (user_id,),
        )
        plan_row = None
        if wallet and wallet.get("plan_code"):
            plan_row = conn.query_one(
                "SELECT * FROM plans WHERE code = ?", (str(wallet["plan_code"]),)
            )

    if not wallet:
        return Entitlement(user_id, "", BASE_CAPABILITIES, "no_wallet")

    plan_code = str(wallet.get("plan_code") or "")
    if not plan_code:
        return Entitlement(user_id, "", BASE_CAPABILITIES, "missing_plan")

    if plan_row is None:
        return Entitlement(user_id, plan_code, BASE_CAPABILITIES, "unknown_plan")

    if not int(plan_row.get("is_active") or 0):
        # A retired plan stops granting. The account keeps the base tier, which
        # is honest: we withdrew the product, not the account's access to us.
        return Entitlement(user_id, plan_code, BASE_CAPABILITIES, "plan_retired")

    expires = _parse_moment(wallet.get("plan_expires_at"))
    if expires is None:
        return Entitlement(user_id, plan_code, BASE_CAPABILITIES, "no_expiry")

    if expires <= moment:
        return Entitlement(
            user_id, plan_code, BASE_CAPABILITIES, "expired", expires_at=expires
        )

    granted = _capabilities_from(plan_row.get("capabilities"))
    # A plan without a capability list would otherwise grant nothing paid, which
    # is correct but surprising; BASE is unioned in so the base surface is never
    # lost by buying something.
    return Entitlement(
        user_id,
        plan_code,
        granted | BASE_CAPABILITIES,
        "active",
        expires_at=expires,
    )


def allows(
    db: Database,
    user_id: str,
    capability: str,
    *,
    now: datetime | None = None,
    record: bool = False,
) -> bool:
    """The single question the studio's `require_entitlement` hook asks.

    ``record`` writes the decision to `entitlement_decisions`. It is off by
    default because entitlement is checked on paths that must stay cheap, and
    on for the gate that admits paid work: "why was this account allowed to
    render video" has to be answerable after the plan row has been edited.
    """
    entitlement = resolve(db, user_id, now=now)
    allowed = entitlement.allows(capability)
    if record:
        _record_decision(db, entitlement, capability, allowed, now=now)
    return allowed


def _record_decision(
    db: Database,
    entitlement: Entitlement,
    capability: str,
    allowed: bool,
    *,
    now: datetime | None = None,
) -> None:
    import uuid

    moment = (now or datetime.now(timezone.utc)).isoformat()
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO entitlement_decisions "
                "(id, user_id, plan_code, capability, allowed, reason, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ent_{uuid.uuid4().hex}",
                    entitlement.user_id,
                    entitlement.plan_code,
                    capability,
                    1 if allowed else 0,
                    entitlement.reason,
                    moment,
                ),
            )
    except Exception:  # noqa: BLE001
        # An audit write must never turn a permitted action into a failed one.
        # Losing the record is bad; refusing a paying user because the log is
        # locked is worse, and both are better than an unhandled exception in
        # the admission path.
        pass


def require(db: Database, user_id: str, capability: str, *, now: datetime | None = None) -> Entitlement:
    """Raise unless the account holds the capability. Returns the entitlement."""
    entitlement = resolve(db, user_id, now=now)
    if not entitlement.allows(capability):
        from deeptutor.services.studio.jobs import StudioError

        raise StudioError(
            "not_entitled",
            f"{capability} is not included in this account's plan "
            f"({entitlement.reason})",
            field="kind",
        )
    return entitlement


def studio_gate(db: Database):
    """The `require_entitlement` callable that `jobs.submit` expects.

    Returned rather than imported into `jobs` so the studio keeps no dependency
    on billing: the dependency runs the other way, which is what keeps `jobs`
    testable without a plan table.
    """

    def _gate(user_id: str, kind: str) -> bool:
        return allows(db, user_id, capability_for_kind(kind), record=True)

    return _gate


def grant_plan(
    db: Database,
    *,
    user_id: str,
    plan_code: str,
    now: datetime | None = None,
    extend: bool = True,
) -> Entitlement:
    """Put an account on a plan, starting now or extending the current one.

    ``extend`` adds the plan's duration to an existing unexpired window rather
    than truncating it: a user who renews early must not lose the days they
    already paid for. Extending an *expired* window starts fresh from now,
    because adding to a past date would leave the account expired after paying.
    """
    moment = now or datetime.now(timezone.utc)
    with db.transaction() as conn:
        plan_row = conn.query_one("SELECT * FROM plans WHERE code = ?", (plan_code,))
        if plan_row is None:
            from deeptutor.services.studio.jobs import StudioError

            raise StudioError(
                "unknown_plan", f"{plan_code!r} is not a known plan", field="plan_code"
            )
        if not int(plan_row.get("is_active") or 0):
            from deeptutor.services.studio.jobs import StudioError

            raise StudioError(
                "plan_retired", f"{plan_code!r} is no longer sold", field="plan_code"
            )

        duration = int(plan_row.get("duration_days") or 0)
        wallet = conn.query_one(
            "SELECT plan_expires_at FROM user_wallets WHERE user_id = ?", (user_id,)
        )
        current = _parse_moment((wallet or {}).get("plan_expires_at"))
        start = moment
        if extend and current is not None and current > moment:
            start = current
        from datetime import timedelta

        expires = start + timedelta(days=duration)

        conn.execute(
            "UPDATE user_wallets SET plan_code = ?, plan_started_at = ?, "
            "plan_expires_at = ?, updated_at = ? WHERE user_id = ?",
            (
                plan_code,
                moment.isoformat(),
                expires.isoformat(),
                moment.isoformat(),
                user_id,
            ),
        )
    return resolve(db, user_id, now=moment)


def list_plans(db: Database, *, include_inactive: bool = False) -> list[Plan]:
    """The purchasable plans, cheapest surface last."""
    sql = "SELECT * FROM plans"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY sort_order, price_toman"
    with db.read() as conn:
        rows = list(conn.query(sql))
    return [
        Plan(
            code=str(row["code"]),
            name=str(row["name"]),
            capabilities=_capabilities_from(row.get("capabilities")),
            duration_days=int(row.get("duration_days") or 0),
            token_quota=int(row.get("token_quota") or 0),
            price_toman=int(row.get("price_toman") or 0),
            is_active=bool(int(row.get("is_active") or 0)),
        )
        for row in rows
    ]


__all__ = [
    "BASE_CAPABILITIES",
    "CAPABILITY_FOR_KIND",
    "CAP_EXAM",
    "CAP_KNOWLEDGE_WRITE",
    "CAP_MEDIA_AUDIO",
    "CAP_MEDIA_VIDEO",
    "CAP_PARTNERS",
    "CAP_STUDIO",
    "Entitlement",
    "Plan",
    "PlanPrice",
    "allows",
    "capability_for_kind",
    "grant_plan",
    "list_plans",
    "price_at",
    "price_history",
    "require",
    "resolve",
    "set_price",
    "studio_gate",
]


# ---------------------------------------------------------------------------
# Versioned prices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanPrice:
    """What a plan cost from a given moment. History, not current state."""

    plan_code: str
    price_toman: int
    token_quota: int
    duration_days: int
    effective_from: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_code": self.plan_code,
            "price_toman": self.price_toman,
            "token_quota": self.token_quota,
            "duration_days": self.duration_days,
            "effective_from": self.effective_from,
        }


def set_price(
    db: Database,
    *,
    plan_code: str,
    price_toman: int,
    token_quota: int,
    duration_days: int,
    effective_from: datetime | None = None,
) -> PlanPrice:
    """Record a new price, keeping every earlier one.

    An UPDATE would rewrite history: last month's invoice could no longer be
    explained, and a cost recorded under the old price would silently become
    wrong. A price is a fact about a moment, so each one is a row with its own
    moment and the newest effective row is the current price.

    ``effective_from`` may be in the future, which is how an increase is
    scheduled without changing what anyone is charged today.
    """
    moment = (effective_from or datetime.now(timezone.utc)).isoformat()
    if price_toman < 0 or token_quota < 0 or duration_days <= 0:
        from deeptutor.services.studio.jobs import StudioError

        raise StudioError(
            "invalid_price",
            "price and quota cannot be negative, and duration must be positive",
            field="price_toman",
        )
    import uuid

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO plan_prices (id, plan_code, price_toman, token_quota, "
            "duration_days, effective_from, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"pp_{uuid.uuid4().hex}",
                plan_code,
                price_toman,
                token_quota,
                duration_days,
                moment,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return PlanPrice(plan_code, price_toman, token_quota, duration_days, moment)


def price_at(
    db: Database, plan_code: str, *, at: datetime | None = None
) -> PlanPrice | None:
    """What this plan cost at a given moment.

    Asked with a past moment, this is how an old invoice is explained: the
    answer comes from the row that was in force then, not from today's price
    projected backwards.
    """
    moment = (at or datetime.now(timezone.utc)).isoformat()
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM plan_prices WHERE plan_code = ? AND effective_from <= ? "
            "ORDER BY effective_from DESC LIMIT 1",
            (plan_code, moment),
        )
    if row is None:
        return None
    return PlanPrice(
        plan_code=str(row["plan_code"]),
        price_toman=int(row["price_toman"]),
        token_quota=int(row["token_quota"]),
        duration_days=int(row["duration_days"]),
        effective_from=str(row["effective_from"]),
    )


def price_history(db: Database, plan_code: str) -> list[PlanPrice]:
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM plan_prices WHERE plan_code = ? ORDER BY effective_from",
                (plan_code,),
            )
        )
    return [
        PlanPrice(
            str(row["plan_code"]),
            int(row["price_toman"]),
            int(row["token_quota"]),
            int(row["duration_days"]),
            str(row["effective_from"]),
        )
        for row in rows
    ]
