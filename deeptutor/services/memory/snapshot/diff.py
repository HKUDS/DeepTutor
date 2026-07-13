"""Pure-function diff between two snapshot states.

A ``state`` is ``{entity_id: fingerprint}``. ``label_map`` carries
human-readable titles for the change-log so we don't have to re-read
workspace state when rendering history.
"""

from __future__ import annotations

from datetime import datetime, timezone

from deeptutor.services.memory.snapshot.entity import ChangeEntry


def diff_snapshots(
    prev: dict[str, str],
    curr: dict[str, str],
    *,
    label_map: dict[str, str],
    prev_label_map: dict[str, str] | None = None,
) -> list[ChangeEntry]:
    """Return the change list moving ``prev`` → ``curr``.

    ``label_map`` provides labels for currently-present entities;
    ``prev_label_map`` (optional) is consulted for removed-entity labels.
    """
    ts = datetime.now(tz=timezone.utc).isoformat()
    out: list[ChangeEntry] = []
    prev_keys = set(prev)
    curr_keys = set(curr)

    for entity_id in sorted(curr_keys - prev_keys):
        out.append(
            ChangeEntry(
                ts=ts,
                kind="added",
                entity_id=entity_id,
                label=label_map.get(entity_id, entity_id),
                prev_fingerprint=None,
                new_fingerprint=curr[entity_id],
            )
        )
    for entity_id in sorted(prev_keys - curr_keys):
        prior_label = (prev_label_map or {}).get(entity_id, "") or entity_id
        out.append(
            ChangeEntry(
                ts=ts,
                kind="removed",
                entity_id=entity_id,
                label=prior_label,
                prev_fingerprint=prev[entity_id],
                new_fingerprint=None,
            )
        )
    for entity_id in sorted(prev_keys & curr_keys):
        if prev[entity_id] != curr[entity_id]:
            out.append(
                ChangeEntry(
                    ts=ts,
                    kind="modified",
                    entity_id=entity_id,
                    label=label_map.get(entity_id, entity_id),
                    prev_fingerprint=prev[entity_id],
                    new_fingerprint=curr[entity_id],
                )
            )
    return out
