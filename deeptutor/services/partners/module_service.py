"""Background services contributed by this installed module."""


async def start_partners(application_container) -> None:
    from deeptutor.services.partners import get_partner_manager

    manager = get_partner_manager()
    manager.configure_runtime_owner(application_container.worker_id)
    await manager.auto_start_partners()


async def stop_partners(application_container) -> None:
    from deeptutor.services.partners import get_partner_manager

    await get_partner_manager().stop_all(preserve_auto_start=True)
