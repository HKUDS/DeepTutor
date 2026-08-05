"""ASM-01 packaged-registration smoke (read-only, no provider/network).

Proves that every new Feynman / model / media / knowledge-card router and
worker is reachable from the *packaged* application — not only from a focused
test harness — by exercising the same import surface the deployed process uses:

* ``deeptutor.api.main`` imports cleanly and the OpenAPI schema contains the
  learning (mastery-path), media and knowledge-card routes;
* the media runtime/scheduler/worker, the knowledge-card generation worker,
  the draft/publication/retraction services and the model selector are all
  importable and constructible (no circular import, no missing optional
  dependency, no source-tree-only import).

The probe runs in a fresh interpreter via subprocess (matching
``tests/runtime/test_api_import_memory_boundary.py``) so import-time
registration is verified from a cold process rather than a warmed module
cache.  Nothing is mutated: stores are rooted in throwaway temp dirs and no
provider endpoint is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import json
import tempfile
from pathlib import Path

# 1) The packaged application imports and its new route families register.
import deeptutor.api.main as main
paths = set(main.app.openapi()["paths"])

# 2) Every new worker/service imports and constructs from the packaged app.
from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.learning.knowledge_cards import KnowledgeCardGenerationWorker
from deeptutor.learning.knowledge_cards.publish import KnowledgeCardPublicationService
from deeptutor.learning.knowledge_cards.retraction import KnowledgeCardRetractionService
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.media.runtime import MediaRuntimeManager
from deeptutor.services.model_selection import ModelSelector

tmp = Path(tempfile.mkdtemp())
store = LearningStore(root=tmp)
KnowledgeCardGenerationWorker(store)
KnowledgeCardDraftService(store)
KnowledgeCardPublicationService(LearningStore(root=tmp))
KnowledgeCardRetractionService(LearningStore(root=tmp))
MediaRuntimeManager(roots=[tmp], executor_factory=None)
ModelSelector()

print(json.dumps(
    {
        "learning": sorted(p for p in paths if p.startswith("/api/v1/learning/progress/")),
        "knowledge": sorted(p for p in paths if p.startswith("/api/v1/knowledge")),
        "media": sorted(
            p
            for p in paths
            if p.startswith("/api/v1/image-jobs") or p.startswith("/api/v1/generated-artifacts")
        ),
        "mastery_tools": list(MASTERY_TOOL_NAMES),
    }
))
"""


def test_asm01_packaged_registration_smoke() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)

    learning = set(result["learning"])
    assert "/api/v1/learning/progress/{book_id}/map" in learning
    assert "/api/v1/learning/progress/{book_id}/knowledge-cards" in learning
    assert "/api/v1/learning/progress/{book_id}/knowledge-points/{kp_id}/knowledge-card" in learning
    assert "/api/v1/learning/progress/{book_id}/knowledge-cards/{card_id}/publish" in learning
    assert "/api/v1/learning/progress/{book_id}/knowledge-cards/{card_id}/retract" in learning

    media = set(result["media"])
    assert "/api/v1/image-jobs" in media
    assert "/api/v1/generated-artifacts" in media

    assert result["knowledge"], "no /api/v1/knowledge routes registered in the packaged app"

    # The seven LRN-03 tools the mastery capability mounts together.
    assert result["mastery_tools"] == [
        "mastery_status",
        "mastery_cycle_start",
        "mastery_record_evidence",
        "mastery_finalize",
        "mastery_quiz",
        "mastery_grade",
        "mastery_build",
    ]
