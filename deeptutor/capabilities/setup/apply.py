"""Commit one configuration change, or refuse to.

The order of the steps below is the whole point of this module, and it is
deliberately the *opposite* of the obvious one (write, then check):

1. resolve the row and check the caller may write its scope,
2. check the value is one the row actually offers,
3. run the row's ``probe`` against a **candidate** configuration that is not
   on disk,
4. only then write.

Probing before the write is what keeps the assistant from unplugging itself.
The chat model is configured by one of these rows; if a bad value were written
first and verified afterwards, the very next turn — including the turn that
would undo the mistake — would run on a model that cannot be reached, and the
user would be left in a conversation that no longer answers. With this order a
failed probe costs one message, and the stored configuration never moved.

The previous value travels back in :class:`ApplyOutcome` so an undo needs no
extra machinery: the model reverts by applying the row again with
``previous``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deeptutor.capabilities.setup.access import can_write
from deeptutor.services.config.settings_spec import (
    ProbeResult,
    SettingSpec,
    get_setting_spec,
)


@dataclass(frozen=True, slots=True)
class SideEffect:
    """Another setting that moved as a consequence of the one that was written."""

    key: str
    label: str
    previous: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "previous": self.previous,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """Result of one apply attempt, shaped for both the model and the UI."""

    ok: bool
    key: str
    value: str = ""
    previous: str = ""
    label: str = ""
    effect: str = ""
    effect_detail: str = ""
    error: str = ""
    probe: ProbeResult | None = None
    side_effects: tuple[SideEffect, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "key": self.key,
            "value": self.value,
            "previous": self.previous,
            "label": self.label,
            "effect": self.effect,
            "effect_detail": self.effect_detail,
        }
        if self.side_effects:
            payload["also_changed"] = [effect.to_dict() for effect in self.side_effects]
        if self.error:
            payload["error"] = self.error
        if self.probe is not None:
            payload["probe"] = {
                "ok": self.probe.ok,
                "detail": self.probe.detail,
                "elapsed_ms": self.probe.elapsed_ms,
            }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


def _neighbour_values(spec: SettingSpec) -> dict[str, tuple[str, str]]:
    """Current ``{key: (label, value)}`` of the other rows in this row's area.

    Read either side of a write so a change that moves a *second* setting is
    reported rather than discovered by the user later. This is not hypothetical:
    ``interface.json`` predates the split between interface and reply language,
    so a file that has never stored a reply language inherits the interface one
    — setting the UI to Chinese also switches replies to Chinese. Detecting that
    generically is what keeps the agent honest without a table of known
    couplings that would inevitably go stale.
    """
    from deeptutor.services.config.settings_spec import specs_for_area

    out: dict[str, tuple[str, str]] = {}
    for other in specs_for_area(spec.area):
        if other.key == spec.key:
            continue
        try:
            out[other.key] = (other.label, other.read())
        except Exception:  # noqa: BLE001 - a row we cannot read is one we cannot compare
            continue
    return out


def _diff_neighbours(
    before: dict[str, tuple[str, str]],
    after: dict[str, tuple[str, str]],
) -> tuple[SideEffect, ...]:
    changed: list[SideEffect] = []
    for key, (label, new_value) in after.items():
        if key not in before:
            continue
        _, old_value = before[key]
        if old_value != new_value:
            changed.append(SideEffect(key=key, label=label, previous=old_value, value=new_value))
    return tuple(changed)


def _choice_error(spec: SettingSpec, value: str) -> str | None:
    choices = spec.choices()
    if not choices:
        return (
            f"'{spec.label}' has no configured options yet, so there is nothing to select. "
            "It has to be set up in Settings first."
        )
    match = next((choice for choice in choices if choice.value == value), None)
    if match is None:
        offered = ", ".join(choice.value for choice in choices)
        return (
            f"'{value}' is not one of the available options for {spec.label}. Options: {offered}."
        )
    if not match.available:
        return f"'{match.label}' is listed but not usable yet: {match.description or 'it needs setup first'}"
    return None


async def apply_setting(key: str, value: str) -> ApplyOutcome:
    """Validate, probe and commit ``value`` for the row named ``key``."""
    spec = get_setting_spec(key)
    if spec is None:
        return ApplyOutcome(ok=False, key=key, value=value, error=f"Unknown setting '{key}'.")

    decision = can_write(spec.scope)
    if not decision.allowed:
        return ApplyOutcome(
            ok=False,
            key=spec.key,
            value=value,
            label=spec.label,
            effect=spec.effect,
            error=decision.reason,
        )

    previous = spec.read()
    if value == previous:
        return ApplyOutcome(
            ok=True,
            key=spec.key,
            value=value,
            previous=previous,
            label=spec.label,
            effect="instant",
            effect_detail="Already set to that value; nothing changed.",
            metadata={"unchanged": True},
        )

    error = _choice_error(spec, value)
    if error is None and spec.validate is not None:
        error = spec.validate(value)
    if error:
        return ApplyOutcome(
            ok=False,
            key=spec.key,
            value=value,
            previous=previous,
            label=spec.label,
            effect=spec.effect,
            error=error,
        )

    probe_result: ProbeResult | None = None
    if spec.probe is not None:
        probe_result = await spec.probe(value)
        if not probe_result.ok:
            return ApplyOutcome(
                ok=False,
                key=spec.key,
                value=value,
                previous=previous,
                label=spec.label,
                effect=spec.effect,
                probe=probe_result,
                error=(
                    f"{spec.label} was left unchanged: the new selection could not be reached. "
                    f"{probe_result.detail}".strip()
                ),
            )

    neighbours_before = _neighbour_values(spec)
    try:
        spec.write(value)
    except Exception as exc:  # noqa: BLE001 - surface the failure, keep the old value
        return ApplyOutcome(
            ok=False,
            key=spec.key,
            value=value,
            previous=previous,
            label=spec.label,
            effect=spec.effect,
            probe=probe_result,
            error=f"Could not save the change: {exc}",
        )
    side_effects = _diff_neighbours(neighbours_before, _neighbour_values(spec))

    # Read back rather than trusting the write: a row's writer normalises what
    # it stores (the catalog rewrites ids, the parsing settings coerce shapes),
    # so this is where a value that was silently adjusted becomes visible
    # instead of being reported to the user as an exact match.
    stored = spec.read()
    return ApplyOutcome(
        ok=True,
        key=spec.key,
        value=stored,
        previous=previous,
        label=spec.label,
        effect=spec.effect,
        effect_detail=spec.effect_detail,
        probe=probe_result,
        side_effects=side_effects,
        metadata={} if stored == value else {"adjusted_from": value},
    )


__all__ = ["ApplyOutcome", "apply_setting"]
