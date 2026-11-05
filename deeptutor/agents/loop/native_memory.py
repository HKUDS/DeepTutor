"""Resolve read-only memory grants in the originating user/partner scope."""

from __future__ import annotations


def memory_roots(name: str) -> list[str]:
    from deeptutor.services.memory.paths import memory_path_service_override, memory_root

    if name == "read_memory":
        return [str(memory_root().resolve())]
    from deeptutor.multi_user.paths import get_admin_path_service, get_current_path_service
    from deeptutor.services.partners.interaction import get_partner_turn_context

    turn = get_partner_turn_context()
    services = (
        (turn.shared_memory, turn.own_memory)
        if turn
        else (get_admin_path_service(), get_current_path_service())
    )
    roots = []
    for service in services:
        with memory_path_service_override(service):
            roots.append(str(memory_root().resolve()))
    return roots
