"""Exercise the learning picker from source discovery through raw file listing."""

import json
from urllib.parse import quote

import pytest

from deeptutor.api.routers import dashboard, knowledge
from deeptutor.services.path_service import get_path_service
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.knowledge import qualified_kb_id
from tests.services.workspace.test_data_scope import account as account
from tests.services.workspace.test_http_scope import scoped_client as scoped_client


def seed_kb(workspace_id, name, filename):
    with workspace_context(workspace_id):
        root = get_path_service().get_knowledge_bases_root()
        raw = root / name / "raw"
        raw.mkdir(parents=True)
        (raw / filename).write_bytes(b"%PDF-1.4\n")
        (root / "kb_config.json").write_text(
            json.dumps({"knowledge_bases": {name: {"name": name, "rag_provider": "llamaindex"}}}),
            encoding="utf-8",
        )


@pytest.mark.parametrize("scope", ["account", "own", "assigned"])
def test_learning_picker_lists_files_from_the_source_workspace(account, scoped_client, scope):
    scoped_client.app.include_router(dashboard.router, prefix="/api/dashboard")
    scoped_client.app.include_router(knowledge.router, prefix="/api")
    name = "Study notes 中文 #1%"
    owner = "" if scope == "account" else account.create_workspace("Owner")["workspace_id"]
    viewer = owner
    seed_kb(owner, name, "selected.pdf")
    if owner:
        # A legacy ID must not silently return a same-name account KB's files.
        seed_kb("", name, "different.pdf")
    if scope == "assigned":
        viewer = account.create_workspace("Reader")["workspace_id"]
        account.update_workspace(
            viewer, resources={"knowledge_bases": [qualified_kb_id(name, owner)]}
        )

    response = scoped_client.get(
        "/api/dashboard/source-library/knowledge", params={"dt_workspace": viewer}
    )
    assert response.status_code == 200, response.text
    (row,) = response.json()["items"]
    assert row["content_workspace_id"] == owner
    response = scoped_client.get(
        f"/api/knowledge-bases/{quote(row['id'], safe='')}/files",
        params={"resource_library": "true", "dt_workspace": row["content_workspace_id"]},
    )
    assert response.status_code == 200, response.text
    assert [file["name"] for file in response.json()["files"]] == ["selected.pdf"]
