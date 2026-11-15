import pytest

from deeptutor.api.routers import dashboard


@pytest.mark.asyncio
async def test_practice_listing_does_one_bounded_search_and_preserves_page_metadata(monkeypatch):
    calls = []

    class Store:
        async def list_notebook_entries(self, **kwargs):
            calls.append(kwargs)
            return {"items": [{"id": 251, "question": "needle"}], "total": 12000}

    monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", lambda: Store())

    async def scoped(reader):
        return [{**row, "content_workspace_id": "school"} for row in await reader()]

    monkeypatch.setattr(dashboard, "_workspace_rows", scoped)
    result = await dashboard.get_source_library("practice", limit=50, offset=250, search="needle")
    assert calls == [{"limit": 50, "offset": 250, "search": "needle"}]
    assert result["items"][0]["content_workspace_id"] == "school"
    assert result["total"] == 12000 and result["has_more"] is True
    assert result["offset"] == 250
