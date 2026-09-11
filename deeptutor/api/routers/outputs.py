"""Request-scoped delivery of generated output artifacts."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.context import get_current_user_or_none
from deeptutor.multi_user.partner_access import visible_partners
from deeptutor.multi_user.paths import get_path_service_for_scope
from deeptutor.services.auth import TokenPayload
from deeptutor.services.partners.scope import partner_scope
from deeptutor.services.path_service import PathService

router = APIRouter()


def _request_path_service() -> PathService:
    """Resolve the workspace installed by ``require_auth`` without fallback.

    The general-purpose ``get_path_service()`` retains a compatibility fallback
    to the local admin workspace for non-request callers.  A download endpoint
    must fail closed instead: otherwise an authentication/context regression
    could expose an administrator artifact to an ordinary request.
    """
    user = get_current_user_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output not found")
    return get_path_service_for_scope(user.scope)


def _resolve_output(path_service: PathService, relative_path: str) -> Path:
    output_path = path_service.resolve_public_output_path(relative_path)
    if output_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output not found")
    return output_path


def _resolve_partner_output(relative_path: str) -> Path | None:
    """Resolve *relative_path* against partner scopes the caller may use.

    Partner web chats run inside a synthetic workspace under
    ``data/partners/<id>/workspace``, so generated files are not beneath the
    human caller's own ``data/users/<uid>`` tree. The public artifact URL shape
    is still ``/files/outputs/<relative path>``, which means the download surface
    has to search the caller's visible partner workspaces when their own
    workspace misses (#1012).

    The first-party chat flow already scopes the request to one conversation, so
    the same relative path colliding across multiple partners is vanishingly
    unlikely. Fail closed anyway: only a unique partner match is served.
    """
    matches: list[Path] = []
    for partner in visible_partners():
        partner_id = str(partner.get("partner_id") or "").strip()
        if not partner_id:
            continue
        candidate = get_path_service_for_scope(
            partner_scope(partner_id)
        ).resolve_public_output_path(relative_path)
        if candidate is not None:
            matches.append(candidate)
            if len(matches) > 1:
                return None
    return matches[0] if matches else None


@router.get("/{output_path:path}", operation_id="read_output_get")
@router.head("/{output_path:path}", operation_id="read_output_head")
async def read_output(
    output_path: str,
    _auth: TokenPayload | None = Depends(require_auth),
) -> FileResponse:
    """Serve one allowlisted artifact from the authenticated user's reach."""
    try:
        path = _resolve_output(_request_path_service(), output_path)
    except HTTPException:
        path = _resolve_partner_output(output_path)
        if path is None:
            raise
    return FileResponse(path)
