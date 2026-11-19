"""Who may execute code on this deployment.

The agent's ``exec`` tool, sandbox-backed skills and the learner-facing code
runner must answer this the same way. Keeping the policy in one function means
adding a new execution surface cannot accidentally widen the rule for ordinary
learners.
"""

from __future__ import annotations

from typing import Any

from .service import get_sandbox_service
from .spec import IsolationLevel


async def can_execute_for_user(user: Any | None = None) -> bool:
    """Whether *user* may run untrusted code right now.

    ``SYSTEM`` isolation serves every account whose per-user grant does not
    switch exec off. ``APPLICATION`` isolation is admin-only: path checks are
    not a security boundary for a learner typing arbitrary code. ``OFF`` never
    executes.
    """
    if user is None:
        from deeptutor.multi_user.context import get_current_user_or_none

        user = get_current_user_or_none()

    level = await get_sandbox_service().isolation_level()
    if level is IsolationLevel.SYSTEM:
        from deeptutor.multi_user.tool_access import exec_override

        return exec_override() is not False
    if level is IsolationLevel.APPLICATION:
        return bool(getattr(user, "is_admin", False))
    return False


__all__ = ["can_execute_for_user"]
