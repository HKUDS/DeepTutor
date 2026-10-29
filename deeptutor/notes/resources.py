"""Turn generated workspace paths into durable, authorized presentation URLs."""

import copy
import re


def normalize_note_resources(markdown, blocks=None, *, workspace_id="", published=None):
    cache = dict(published or {})

    def resolve(url):
        if not isinstance(url, str) or not url.startswith("outputs/"):
            return url
        if url not in cache:
            from deeptutor.services.workspace import get_content_workspace_service

            service = get_content_workspace_service()
            binding = (
                service.binding_by_id(workspace_id) if workspace_id else service.current_binding()
            )
            item = service.publish(binding, [{"path": url}])[0]
            cache[url] = item.url
        return cache[url]

    def text(value):
        # Leave fenced code examples verbatim; only Markdown destinations are links.
        pieces = re.split(r"(^```[^\n]*\n[\s\S]*?^```[^\n]*$)", value, flags=re.M)
        for i in range(0, len(pieces), 2):
            pieces[i] = re.sub(
                r"(\]\()(outputs/[^\s()]+)(\))", lambda m: m[1] + resolve(m[2]) + m[3], pieces[i]
            )
        return "".join(pieces)

    def visit(items):
        if not isinstance(items, list):
            return
        for block in items:
            if not isinstance(block, dict):
                continue
            props = block.get("props", {})
            if not isinstance(props, dict):
                continue
            for key in ("url", "sourceUrl"):
                if key in props:
                    props[key] = resolve(props[key])
            if isinstance(props.get("markdown"), str):
                props["markdown"] = text(props["markdown"])
            visit(block.get("children", []))

    normalized = copy.deepcopy(blocks)
    if normalized:
        visit(normalized)
    return text(markdown), normalized


async def saved_note_resources(markdown, blocks=None):
    """Recover legacy links from this account/scope's recorded attachments only."""
    import json

    from deeptutor.services.session import get_session_store

    serialized = markdown + "\n" + json.dumps(blocks or [])
    paths = set(re.findall(r"outputs/[^\s\\\"()]+", serialized))
    sessions = {
        match[1]
        for path in paths
        if (match := re.match(r"outputs/[^/]+/(unified_[a-zA-Z0-9_]+)/", path))
    }
    published = {}
    for session_id in sessions:
        session = await get_session_store().get_session_with_messages(session_id)
        for message in (session or {}).get("messages", []):
            for item in message.get("attachments") or []:
                path = item.get("relative_path")
                url = item.get("url", "")
                if path in paths and url.startswith("/files/workspace-items/"):
                    published[path] = url
    return published
