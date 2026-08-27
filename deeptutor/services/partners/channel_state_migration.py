"""One-shot rehoming of channel state that used to be shared by all partners.

Channel runtime state — bot tokens, long-poll cursors, conversation
references, E2EE device stores — used to live in one directory per *channel*
(``data/partners/weixin/``), not per partner. Two partners on the same channel
therefore read each other's credentials and overwrote each other's cursor,
which is why only one of them could ever be online. It now lives under
``data/partners/{partner_id}/channels/{channel}/``.

That move would log the working partner out, so the old state is copied across
first — but only when its owner is certain. Two kinds of certainty:

* the state *names* its owner (a saved bot token that matches one partner's
  configured token), or
* only one partner has the channel enabled at all.

Anything else is a genuine tie, and guessing would hand one partner another's
account — the very bug this fixes. Those re-authenticate once instead.

Copies rather than moves, like the TutorBot migration before it: the legacy
tree is left untouched, so a bad outcome is always recoverable by hand.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping

from deeptutor.partners.config.paths import get_data_dir, get_partner_channel_dir

logger = logging.getLogger(__name__)

#: Channel name → the directory it used to share, under ``data/partners/``.
LEGACY_STATE_DIRS: dict[str, str] = {
    "weixin": "weixin",
    "mochat": "mochat",
    "msteams": "msteams",
    "matrix": "matrix-store",
}


def _has_content(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _weixin_claims(legacy: Path, channel_config: Mapping[str, Any]) -> bool:
    """True when the legacy ``account.json`` holds *this* partner's bot token.

    The web onboarding writes the token it wins into the partner's own config,
    so for every partner set up that way the saved state proves whose it is.
    """
    token = str(channel_config.get("token") or "").strip()
    if not token:
        return False
    try:
        data = json.loads((legacy / "account.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and str(data.get("token") or "").strip() == token


#: Channels whose stored state can identify its own owner.
_CLAIMS: dict[str, Callable[[Path, Mapping[str, Any]], bool]] = {"weixin": _weixin_claims}


def _resolve_owner(
    channel: str,
    legacy: Path,
    candidates: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Which partner the legacy state belongs to, or ``None`` if undecidable."""
    enabled = [
        partner_id
        for partner_id, channels in candidates.items()
        if isinstance(channels.get(channel), Mapping) and channels[channel].get("enabled")
    ]
    if not enabled:
        return None

    claims = _CLAIMS.get(channel)
    if claims:
        proven = [pid for pid in enabled if claims(legacy, candidates[pid][channel])]
        if len(proven) == 1:
            return proven[0]
        if len(proven) > 1:
            return None  # Two partners configured with one token: not ours to split.

    return enabled[0] if len(enabled) == 1 else None


def rehome_shared_channel_state(candidates: Mapping[str, Mapping[str, Any]]) -> None:
    """Copy each legacy shared channel state dir to the partner that owns it.

    ``candidates`` maps partner id → that partner's ``channels`` config dict.
    Safe to call repeatedly: a partner that already has its own state is left
    alone, which is also what stops the copy from happening twice.
    """
    base = get_data_dir()
    for channel, dirname in LEGACY_STATE_DIRS.items():
        legacy = base / dirname
        if not _has_content(legacy):
            continue
        if (legacy / "config.yaml").exists():
            continue  # A partner that happens to be named after a channel.

        owner = _resolve_owner(channel, legacy, candidates)
        if owner is None:
            logger.info(
                "Legacy %s state in %s has no unambiguous owner; leaving it in place "
                "(affected partners re-authenticate once)",
                channel,
                legacy,
            )
            continue

        target = get_partner_channel_dir(owner, channel)
        if _has_content(target):
            continue
        try:
            shutil.copytree(legacy, target, dirs_exist_ok=True)
        except OSError:
            logger.exception("Failed to rehome legacy %s state to partner '%s'", channel, owner)
            continue
        logger.info("Rehomed legacy %s state to partner '%s'", channel, owner)
