"""Memory consolidator — chunk-based update / audit / dedup.

Public surface (call these from the API router / store / tests):

* :class:`ConsolidateResult`, :data:`OnEvent` — legacy types preserved
  for :mod:`deeptutor.services.memory.store`.
* :func:`consolidate_l2`, :func:`consolidate_l3` — legacy shims that
  delegate to :func:`run_update`.
* :func:`run_update`, :func:`run_audit`, :func:`run_dedup` — the three
  modes the workbench drives directly.
* :func:`_parse_ops_response`, :func:`_filter_banned`,
  :func:`_has_banned` — kept for :meth:`store.MemoryStore.apply_ops_payload`
  and the existing test suite.

Submodule layout:

    chunker.py         pure char-based chunker with boundary expansion
    line_doc.py        line-numbered view + replace/delete/insert edits
    meta.py            *.meta.json read/write for "seen ids" diffs
    references.py      ref pool validation + raw-trace annotation
    guards.py          banned-phrase filter (legacy + L3 enforcement)
    parse.py           legacy ops-array parser (apply_ops_payload)
    modes/
      _runtime.py      shared prompt loading + LLM + atomic write
      _shims.py        legacy consolidate_l2/l3 → run_update
      update.py        chunk-based incremental fact extraction
      audit.py         chunk-based line edits vs raw evidence
      dedup.py         iterative line-level dedup over full doc
    prompts/
      {en,zh}/{update_l2,update_l3,audit_l2,audit_l3,dedup,_meta}.yaml
"""

from __future__ import annotations

from deeptutor.services.memory.consolidator.guards import _filter_banned, _has_banned
from deeptutor.services.memory.consolidator.modes import (
    consolidate_l2,
    consolidate_l3,
    run_audit,
    run_dedup,
    run_merge,
    run_update,
)
from deeptutor.services.memory.consolidator.modes._shims import (
    ConsolidateResult,
    OnEvent,
)
from deeptutor.services.memory.consolidator.parse import _parse_ops_response

__all__ = [
    "ConsolidateResult",
    "OnEvent",
    "_filter_banned",
    "_has_banned",
    "_parse_ops_response",
    "consolidate_l2",
    "consolidate_l3",
    "run_audit",
    "run_dedup",
    "run_merge",
    "run_update",
]
