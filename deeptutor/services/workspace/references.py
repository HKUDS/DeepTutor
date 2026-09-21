"""Rebind persisted local download URLs while preserving resource identifiers."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_LOCAL_URL = re.compile(
    r"(?<![A-Za-z0-9:/])/(?:files/(?:attachments|outputs|workspace-items)/|api/(?:reading|video-learning)/)[^\s\"'<>\\)\]]+"
)


def rebind_local_urls(text: str, workspace_id: str) -> str:
    def replace(match):
        parts = urlsplit(match.group(0))
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["dt_workspace"] = workspace_id
        return urlunsplit(parts._replace(query=urlencode(query)))

    return _LOCAL_URL.sub(replace, text)
