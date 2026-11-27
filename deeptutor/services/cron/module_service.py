"""Background services contributed by this installed module."""


async def start_cron(application_container) -> None:
    from deeptutor.services.cron import get_cron_service

    await get_cron_service().start()


async def stop_cron(application_container) -> None:
    from deeptutor.services.cron import get_cron_service

    await get_cron_service().stop()
