"""Small data models for DeepTutor's optional multi-user layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Role = Literal["admin", "user"]
ScopeKind = Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    username: str
    role: Role = "user"
    created_at: str = ""
    disabled: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "disabled": self.disabled,
        }


@dataclass(frozen=True, slots=True)
class UserScope:
    kind: ScopeKind
    user_id: str
    root: Path

    @property
    def cache_key(self) -> str:
        return f"{self.kind}:{self.user_id}:{self.root.resolve()}"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    username: str
    role: Role
    scope: UserScope

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_admin": self.is_admin,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeResource:
    id: str
    name: str
    base_dir: Path
    source: Literal["admin", "user"]
    assigned: bool = False
    read_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def physical_name(self) -> str:
        return self.name


LOCAL_ADMIN_ID = "local-admin"
LOCAL_ADMIN_USERNAME = "local"
