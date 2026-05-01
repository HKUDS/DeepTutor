"""
DeepTutor Plugin Namespace
==========================

Drop-in plugins extend DeepTutor without touching core. Each plugin lives in
its own subdirectory (``deeptutor/plugins/<name>/``) and ships a
``manifest.yaml`` plus a ``capability.py`` exposing a ``BaseCapability``
subclass — see ``AGENTS.md`` for the contract.

The plugin loader (``deeptutor.plugins.loader``) is intentionally optional:
``CapabilityRegistry.load_plugins`` swallows ``ImportError`` so the framework
keeps working when no plugins are installed.
"""
