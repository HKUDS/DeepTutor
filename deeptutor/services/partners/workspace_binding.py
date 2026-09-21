"""A Partner may use one of its owner's registered content workspaces."""

from contextlib import contextmanager

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.models import LOCAL_ADMIN_ID
from deeptutor.multi_user.paths import local_admin_user, user_context
from deeptutor.services.partners.interaction import actor_for_account
from deeptutor.services.partners.scope import partner_user
from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service
from deeptutor.services.workspace.activity import data_activity
from deeptutor.services.workspace.context import workspace_context


def workspace_owner(owner_id: str):
    owner_id = owner_id or LOCAL_ADMIN_ID
    if owner_id == LOCAL_ADMIN_ID:
        return local_admin_user()
    # Creation and configuration already have an authenticated owner. IM
    # turns instead reconstruct the saved account, refusing deleted users.
    caller = get_current_user()
    owner = caller if caller.id == owner_id else actor_for_account(owner_id)
    if owner is None:
        raise WorkspaceError("The partner's workspace owner is unavailable.")
    return owner


def validate_partner_workspace(workspace_id: str, owner_id: str) -> str:
    workspace_id = workspace_id.strip()
    if workspace_id:
        with user_context(workspace_owner(owner_id)), workspace_context(""):
            get_content_workspace_service().validate_chat_binding(workspace_id)
    return workspace_id


@contextmanager
def partner_content_context(partner_id: str, config):
    workspace_id = getattr(config, "workspace_id", "")
    if not workspace_id:
        with user_context(partner_user(partner_id, name=config.name)):
            yield
        return
    # Pin identity and data scope for the full turn, including async tools.
    # A shared activity lease prevents moving the workspace mid-generation.
    with user_context(workspace_owner(config.owner_id)), data_activity():
        get_content_workspace_service().validate_chat_binding(workspace_id)
        with workspace_context(workspace_id):
            yield
