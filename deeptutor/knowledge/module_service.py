"""Background services contributed by this installed module."""


async def start_github_sync(application_container) -> None:
    from deeptutor.services.github_source.sync_service import get_sync_service

    await get_sync_service().start()


async def stop_github_sync(application_container) -> None:
    from deeptutor.services.github_source.sync_service import get_sync_service

    await get_sync_service().stop()


async def start_web_source_sync(application_container) -> None:
    from deeptutor.services.web_source.scheduler import (
        start_web_source_sync_scheduler,
    )

    await start_web_source_sync_scheduler()


async def stop_web_source_sync(application_container) -> None:
    from deeptutor.services.web_source.scheduler import (
        stop_web_source_sync_scheduler,
    )

    await stop_web_source_sync_scheduler()
