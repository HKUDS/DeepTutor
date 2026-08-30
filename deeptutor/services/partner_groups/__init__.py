"""First-class Partner Group services."""

from deeptutor.services.partner_groups.manager import (
    PartnerGroupManager,
    get_partner_group_manager,
)
from deeptutor.services.partner_groups.memory import shared_memory_registry
from deeptutor.services.partner_groups.models import PartnerGroupConfig, PartnerInvocation
from deeptutor.services.partner_groups.modes import discussion_mode_registry

__all__ = [
    "PartnerGroupConfig",
    "PartnerGroupManager",
    "PartnerInvocation",
    "discussion_mode_registry",
    "get_partner_group_manager",
    "shared_memory_registry",
]
