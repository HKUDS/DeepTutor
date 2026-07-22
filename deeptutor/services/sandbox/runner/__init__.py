"""Sandbox runner sidecar: a tiny HTTP service that executes untrusted shell.

Runs in its own least-privileged container, isolated from the main app. The
main app talks to it via :class:`deeptutor.services.sandbox.backends.RunnerSidecarBackend`,
pointed at it through ``DEEPTUTOR_SANDBOX_RUNNER_URL``.
"""
