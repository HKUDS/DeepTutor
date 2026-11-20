"""A licence is a set of permissions, not a word.

Why this module exists
----------------------
`licence_code` used to be a free string. `"cc-by"` and `"asdf"` were both
accepted, both hashed into the cache key, and both written into the asset row
as though they meant the same thing. That made the rights column of Gate 8
decorative: the system recorded that *a* licence was named, not that any
particular use was allowed.

The fix is to treat a licence as what it actually is -- a small set of granted
permissions -- and to check the permissions the pipeline needs against the
permissions the licence grants:

* may we **reproduce** the source text in a generated lesson?
* may we **adapt** it (summarise, cut, reorder, translate)?
* may we **render** it to audio and video?
* does the licence require **attribution** (so the asset must carry it)?
* does it require **share-alike** (so the derivative cannot be relicensed)?

A licence that does not grant rendering cannot produce a video, no matter how
correctly the row is written.

What this module deliberately does not do
-----------------------------------------
It does not decide whether we *have* a licence for a given book. That is a
human decision recorded against the source, and it is exactly the question open
since Phase 5. What this module guarantees is narrower and checkable: **if a
licence code is recorded, the operations performed were permitted by it.** A
pipeline run under `citation-only` cannot render audio, and attempting it is a
refusal rather than a footnote in a report.

Unknown codes are refused rather than trusted. A registry that accepts anything
is a registry that says nothing, and the failure mode of trusting an unknown
code is distributing content we had no right to distribute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The operations the studio performs on a source. Named after what we do, not
#: after what a licence calls it, so the check reads as a sentence about work.
OP_REPRODUCE = "reproduce"
OP_ADAPT = "adapt"
OP_RENDER_AUDIO = "render_audio"
OP_RENDER_VISUAL = "render_visual"
OP_REDISTRIBUTE = "redistribute"

#: Everything a rendered lesson needs. Kept as one tuple so a new kind cannot
#: quietly skip a permission by constructing its own list.
LESSON_OPS: tuple[str, ...] = (OP_REPRODUCE, OP_ADAPT, OP_RENDER_AUDIO, OP_RENDER_VISUAL)

#: What each media kind needs from the licence.
KIND_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "audio_overview": (OP_REPRODUCE, OP_ADAPT, OP_RENDER_AUDIO),
    "video_lesson": LESSON_OPS,
    "slide_deck": (OP_REPRODUCE, OP_ADAPT, OP_RENDER_VISUAL),
    "mind_map": (OP_REPRODUCE, OP_ADAPT, OP_RENDER_VISUAL),
    "infographic": (OP_REPRODUCE, OP_ADAPT, OP_RENDER_VISUAL),
}


@dataclass(frozen=True)
class Licence:
    """One licence and what it grants.

    ``grants`` is the whole point: a licence is the set of things it allows.
    ``requires`` are obligations the pipeline must satisfy or refuse -- an
    attribution-only licence that produces an asset with no attribution field
    populated has not been complied with, even though no permission was
    exceeded.
    """

    code: str
    name: str
    grants: frozenset[str]
    requires: frozenset[str] = field(default_factory=frozenset)
    #: True for licences that permit commercial use; recorded because a school
    #: pilot and a paid product are different questions.
    commercial_ok: bool = False
    url: str = ""

    def allows(self, operation: str) -> bool:
        return operation in self.grants

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "grants": sorted(self.grants),
            "requires": sorted(self.requires),
            "commercial_ok": self.commercial_ok,
            "url": self.url,
        }


_ALL_RENDER = frozenset({OP_REPRODUCE, OP_ADAPT, OP_RENDER_AUDIO, OP_RENDER_VISUAL})

#: The registry. Small on purpose: these are the licences a Persian educational
#: product actually meets, not an attempt at completeness. Adding one is a
#: deliberate act with its obligations spelled out, which is the point.
REGISTRY: dict[str, Licence] = {
    "cc-by": Licence(
        code="cc-by",
        name="Creative Commons Attribution 4.0",
        grants=_ALL_RENDER,
        requires=frozenset({"attribution"}),
        commercial_ok=True,
        url="https://creativecommons.org/licenses/by/4.0/",
    ),
    "cc-by-sa": Licence(
        code="cc-by-sa",
        name="Creative Commons Attribution-ShareAlike 4.0",
        grants=_ALL_RENDER,
        requires=frozenset({"attribution", "share_alike"}),
        commercial_ok=True,
        url="https://creativecommons.org/licenses/by-sa/4.0/",
    ),
    "cc-by-nc": Licence(
        code="cc-by-nc",
        name="Creative Commons Attribution-NonCommercial 4.0",
        grants=_ALL_RENDER,
        requires=frozenset({"attribution", "non_commercial"}),
        commercial_ok=False,
        url="https://creativecommons.org/licenses/by-nc/4.0/",
    ),
    "cc0": Licence(
        code="cc0",
        name="CC0 1.0 Universal (public domain dedication)",
        grants=_ALL_RENDER,
        requires=frozenset(),
        commercial_ok=True,
        url="https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    "public-domain": Licence(
        code="public-domain",
        name="Public domain",
        grants=_ALL_RENDER,
        requires=frozenset(),
        commercial_ok=True,
    ),
    "own-work": Licence(
        code="own-work",
        name="Authored by us, all rights held",
        grants=_ALL_RENDER,
        requires=frozenset(),
        commercial_ok=True,
    ),
    # A licence that permits *quoting* but not *rendering* is included on
    # purpose: it is the common shape of an academic or publisher permission,
    # and it is the case where a naive "has a licence" check would wrongly
    # allow a video.
    "citation-only": Licence(
        code="citation-only",
        name="Quotation with citation; no derivative rendering",
        grants=frozenset({OP_REPRODUCE}),
        requires=frozenset({"attribution"}),
        commercial_ok=False,
    ),
    "internal-only": Licence(
        code="internal-only",
        name="Internal evaluation only; not distributable",
        grants=_ALL_RENDER,
        requires=frozenset({"no_redistribution"}),
        commercial_ok=False,
    ),
    # Not a licence with terms but the absence of one: the rights holder *is*
    # the source. Registered explicitly rather than left out, because a user
    # uploading their own textbook will reach for this word, and "unknown code"
    # would be a confusing way to say "you may do what you like".
    "all-rights": Licence(
        code="all-rights",
        name="All rights held; no external obligations",
        grants=_ALL_RENDER | frozenset({OP_REDISTRIBUTE}),
        requires=frozenset(),
        commercial_ok=True,
    ),
}

#: Obligations the studio can actually satisfy. An obligation it cannot satisfy
#: means the licence cannot be used for that kind -- refusing is the only honest
#: option, because silently ignoring the obligation is a breach with a receipt.
SATISFIABLE_REQUIREMENTS = frozenset({"attribution", "share_alike", "non_commercial"})


class LicenceError(ValueError):
    """A licence problem: unknown code, missing permission, unmet obligation."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


def get(code: str) -> Licence:
    """Look a licence up, or refuse.

    An unknown code is an error, not a wildcard. The whole value of the
    registry is that a typo in a licence field is caught at submit time rather
    than discovered in a rights complaint.
    """
    key = str(code or "").strip().lower()
    if not key:
        raise LicenceError("licence_required", "no licence code was given")
    licence = REGISTRY.get(key)
    if licence is None:
        raise LicenceError(
            "unknown_licence",
            f"{code!r} is not a registered licence; known codes: {sorted(REGISTRY)}",
        )
    return licence


def requirements_for(kind: str) -> tuple[str, ...]:
    """What this media kind needs from a licence."""
    try:
        return KIND_REQUIREMENTS[kind]
    except KeyError as exc:
        raise LicenceError("unknown_kind", f"{kind!r} has no licence requirements") from exc


def check(code: str, kind: str) -> Licence:
    """Would this licence permit producing this kind? Return it, or refuse.

    Every missing permission is reported, not just the first: a user who gets
    "video needs render_audio AND render_visual" can act on it, whereas two
    round trips to discover the same licence cannot do either is just noise.
    """
    licence = get(code)
    needed = requirements_for(kind)
    missing = [op for op in needed if not licence.allows(op)]
    if missing:
        raise LicenceError(
            "licence_insufficient",
            f"{licence.code} grants {sorted(licence.grants)} but {kind} needs "
            f"{list(needed)}; missing {missing}",
        )
    unsatisfiable = sorted(licence.requires - SATISFIABLE_REQUIREMENTS)
    if unsatisfiable:
        raise LicenceError(
            "licence_obligation_unsupported",
            f"{licence.code} requires {unsatisfiable}, which this pipeline cannot "
            "satisfy; using it would breach the licence rather than honour it",
        )
    return licence


def obligations(code: str) -> frozenset[str]:
    return get(code).requires


def is_commercial_ok(code: str) -> bool:
    """Whether this licence permits a paid product.

    Separate from :func:`check` because a free pilot and a paid launch are the
    same pipeline and different legal questions.
    """
    return get(code).commercial_ok


def describe_all() -> list[dict[str, Any]]:
    """Every known licence and what it allows -- for the API and for docs."""
    return [REGISTRY[code].as_dict() for code in sorted(REGISTRY)]


def attribution_for(
    *, licence_code: str, source_title: str = "", source_id: str | None = None
) -> str:
    """The attribution line an asset must carry, or '' when none is required.

    Built here rather than at render time so every renderer produces the same
    string. An attribution that differs per renderer is an attribution that will
    be missing from at least one of them.
    """
    licence = get(licence_code)
    if "attribution" not in licence.requires:
        return ""
    parts = []
    if source_title:
        parts.append(source_title)
    elif source_id:
        parts.append(source_id)
    parts.append(licence.name)
    if licence.url:
        parts.append(licence.url)
    return " — ".join(parts)


__all__ = [
    "KIND_REQUIREMENTS",
    "LESSON_OPS",
    "Licence",
    "LicenceError",
    "OP_ADAPT",
    "OP_REDISTRIBUTE",
    "OP_RENDER_AUDIO",
    "OP_RENDER_VISUAL",
    "OP_REPRODUCE",
    "REGISTRY",
    "SATISFIABLE_REQUIREMENTS",
    "attribution_for",
    "check",
    "describe_all",
    "get",
    "is_commercial_ok",
    "obligations",
    "requirements_for",
]
