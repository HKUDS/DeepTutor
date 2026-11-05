"""Lazy service callbacks assembled in dependency order."""

from functools import partial
from importlib import import_module

from .catalog import dependency_order, manifests, module_enabled


def module_service_callbacks(action, container):
    if action not in {"start", "stop"}:
        raise ValueError(action)
    names = dependency_order(list(manifests()))
    # BackgroundLeaderSupervisor reverses the started prefix at shutdown;
    # keep start/stop callback positions paired, including partial startup.
    callbacks = []
    for name in names:
        if not module_enabled(name):
            continue
        for service in manifests()[name]["services"]:

            async def invoke(reference, owner):
                module, attribute = reference.split(":", 1)
                await getattr(import_module(module), attribute)(owner)

            callbacks.append(partial(invoke, service[action], container))
    return callbacks
