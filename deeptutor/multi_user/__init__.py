"""Optional multi-user support for DeepTutor.

The package is deliberately isolated from the legacy single-user services.
Existing code enters it through thin adapters only when AUTH_ENABLED=true.

Backend support matrix
----------------------

The default JSON/SQLite backend (``POCKETBASE_URL`` unset) is the supported
multi-user path: per-user workspaces under ``multi-user/<uid>/``, per-user
SQLite session DBs, and JWT-based auth.

PocketBase mode (``POCKETBASE_URL`` set) is **single-user only** at the
moment: the PocketBase ``users`` collection has no ``role`` field by default
(every login resolves to ``role="user"``, so no admin can be created), and
the ``sessions`` / ``messages`` / ``turns`` collections are not filtered by
``user_id`` in the queries. Treat PocketBase deployments as single-user until
the schema and queries are updated.
"""

from .models import CurrentUser, UserRecord, UserScope

__all__ = ["CurrentUser", "UserRecord", "UserScope"]
