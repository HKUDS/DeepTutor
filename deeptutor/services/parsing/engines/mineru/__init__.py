"""MinerU parsing engine (local CLI or hosted cloud API).

Modules:

* ``config``  — :class:`MinerUConfig` + ``resolve_mineru_config`` (read-side
  adapter over ``document_parsing.json``).
* ``backend`` — ``parse_pdf_to_workdir`` (local/cloud dispatch) + CLI probes.
* ``local``   — the local MinerU CLI subprocess runner.
* ``cloud``   — the hosted MinerU cloud API client.
* ``models``  — one-click model download manager + ``model_env_overrides``.
* ``readiness`` — local model-readiness probe (the "no silent download" gate).
* ``engine``  — :class:`MinerUParser` implementing the ``Parser`` protocol.
"""
