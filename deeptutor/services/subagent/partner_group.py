"""Bridge chat consultation to the native, approval-aware Group session."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from deeptutor.services.subagent.partner import PartnerBackend
from deeptutor.services.subagent.types import ConsultResult, SubagentEvent


class PartnerGroupBackend(PartnerBackend):
    kind = "partner_group"
    display_name = "Partner Group"

    async def consult(
        self,
        question,
        *,
        on_event,
        cwd=None,
        session_id=None,
        config=None,
        images=None,
        partner_id=None,
    ) -> ConsultResult:
        from deeptutor.services.partner_groups.manager import get_partner_group_manager

        manager = get_partner_group_manager()
        group_id = str(partner_id or "")
        group = manager.get_group(group_id)
        if group is None:
            return ConsultResult(success=False, error="Partner Group is unavailable.")
        session_key = session_id or f"dt-{uuid4().hex[:12]}"
        live = manager.start_live_turn(
            group_id,
            content=question,
            session_key=session_key,
            mentions=list(group.member_ids),
        )
        window = manager.begin_consultation(group_id, session_key)
        last_status = None
        last_emit = 0.0
        event_count = 0
        try:
            while True:
                invocations = manager.invocations(group_id, session_key, limit=10000)
                messages = manager.history(group_id, session_key, limit=10000)
                operations = manager.subscribe_live_turns(group_id, session_key)
                busy = any(op.task and not op.task.done() for op in operations) or any(
                    item["status"] in {"pending", "approved"} for item in invocations
                )
                revision = (
                    tuple(m["event_id"] for m in messages),
                    tuple((i["invocation_id"], i["status"]) for i in invocations),
                )
                remaining = window.remaining(busy=busy, revision=revision)
                status = (
                    "completed"
                    if remaining == 0
                    else "waiting"
                    if remaining is not None
                    else "discussing"
                )
                if remaining == 0:
                    # Seal the snapshot before awaiting the final notification.
                    manager.end_consultation(group_id, session_key, window)
                if (status, remaining) != last_status or time.monotonic() - last_emit >= 15:
                    await on_event(
                        SubagentEvent(
                            "log",
                            group.name,
                            meta={
                                "merge_id": "group-wait",
                                "partner_group_id": group_id,
                                "partner_group_session_key": session_key,
                                "partner_group_consultation_status": status,
                                "partner_group_idle_seconds": remaining,
                            },
                        )
                    )
                    event_count += 1
                    last_status = (status, remaining)
                    last_emit = time.monotonic()
                if remaining == 0:
                    break
                await asyncio.sleep(0.25)

            # Include the entire public conversation, including user follow-ups,
            # every approved peer exchange and summaries, rather than only the
            # initial round. Private reasoning never enters this transcript.
            text = "\n\n".join(
                f"{m.get('author_name') or m['role']} ({m['kind']}{', failed' if m['error'] else ''}):\n{m['content']}"
                for m in messages
            )
            decisions = "\n".join(
                f"{i['requester_partner_name']} → {i['target_partner_name']}: {i['status']}"
                for i in invocations
            )
            if decisions:
                text += "\n\nFollow-up decisions:\n" + decisions
            return ConsultResult(
                final_text=text,
                session_id=session_key,
                success=any(m["role"] == "partner" and not m["error"] for m in messages),
                event_count=event_count,
                error="" if messages else "The discussion produced no messages.",
            )
        except asyncio.CancelledError:
            # Stopping the parent chat also stops any approved follow-up still
            # running; never leave a detached generation consuming resources.
            for operation in manager.subscribe_live_turns(group_id, session_key):
                if operation.task and not operation.task.done():
                    operation.task.cancel()
            raise
        finally:
            manager.end_consultation(group_id, session_key, window)
