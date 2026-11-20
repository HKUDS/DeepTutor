"""Repositories: the only place SQL is allowed to live.

Each repository owns one aggregate and exposes *dicts shaped like the JSON
records they replace*. That is not laziness — it is the migration contract. The
Phase 2 callers (``deeptutor.multi_user.identity``, ``otp.py``, routers) read
``record["disabled"]``, ``record["token_version"]`` and
``record["created_at"][:10]``. If a repository returned a dataclass or renamed a
field, every one of those call-sites would need an edit, and every edit is a
chance to silently drop security state — exactly the class of bug Phase 2 hit
twice with ``_canonical_record``.

Keeping the shape means the swap is: replace the storage functions inside the
existing module, leave every caller untouched.
"""

from __future__ import annotations

from deeptutor.db.repositories.audit import AuditRepository
from deeptutor.db.repositories.identity import IdentityRepository, IdentityRepositoryError
from deeptutor.db.repositories.otp import OtpRepository
from deeptutor.db.repositories.sessions import SessionRepository
from deeptutor.db.repositories.wallets import WalletRepository, WalletRepositoryError

__all__ = [
    "AuditRepository",
    "IdentityRepository",
    "IdentityRepositoryError",
    "OtpRepository",
    "SessionRepository",
    "WalletRepository",
    "WalletRepositoryError",
]
