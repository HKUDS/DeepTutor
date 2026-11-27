"""Stable identity grammar shared by the host and channel adapters."""

PARTNER_USER_PREFIX = "partner_"


def partner_user_id(partner_id: str) -> str:
    return f"{PARTNER_USER_PREFIX}{partner_id}"


def is_partner_user_id(user_id: str) -> bool:
    return user_id.startswith(PARTNER_USER_PREFIX)
