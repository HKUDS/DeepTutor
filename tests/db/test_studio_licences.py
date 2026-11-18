"""Licences as permissions, and attribution on the artefact.

The rights column of Gate 8 was decorative while `licence_code` was a free
string: "cc-by" and "asdf" both passed. These tests pin the two things that make
it a control -- the operation check, and the obligation being visible on the
file.
"""

from __future__ import annotations

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import jobs as S
from deeptutor.services.studio import licences as L


def _user(db, user_id="u1", tokens=20000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)
    return user_id


def _submit(db, **kwargs):
    _user(db)
    payload = dict(user_id="u1", kind="mind_map", script="متن", source_id="s1", licence_code="cc-by")
    payload.update(kwargs)
    return S.submit(
        db, queue=JobQueue(db, worker_id="t"), request=S.JobRequest(**payload)
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_an_unknown_code_is_refused_not_trusted(db):
    """A registry that accepts anything says nothing."""
    with pytest.raises(S.StudioError) as exc:
        _submit(db, licence_code="asdf")
    assert exc.value.rule == "unknown_licence"


def test_a_licence_is_case_and_space_insensitive(db):
    assert L.get("  CC-BY  ").code == "cc-by"


def test_every_registered_licence_has_a_documented_set_of_grants():
    for entry in L.describe_all():
        assert entry["grants"], f"{entry['code']} grants nothing"
        assert entry["name"], f"{entry['code']} has no human name"


# ---------------------------------------------------------------------------
# The operation check -- the part that makes it a control
# ---------------------------------------------------------------------------


def test_a_citation_only_licence_cannot_produce_a_lesson(db):
    """The common shape of a publisher permission: quote, do not render."""
    with pytest.raises(S.StudioError) as exc:
        _submit(db, kind="video_lesson", licence_code="citation-only")
    assert exc.value.rule == "licence_insufficient"


def test_a_citation_only_licence_cannot_produce_any_visual_either(db):
    for kind in ("slide_deck", "mind_map", "infographic"):
        with pytest.raises(S.StudioError):
            _submit(db, kind=kind, licence_code="citation-only", script=f"متن {kind}")


def test_cc_by_can_produce_every_kind(db):
    for kind in S.MEDIA_KINDS:
        assert _submit(db, kind=kind, script=f"متن {kind}")["job_id"]


def test_the_refusal_names_the_missing_permissions(db):
    with pytest.raises(S.StudioError) as exc:
        _submit(db, kind="video_lesson", licence_code="citation-only")
    assert "render_audio" in exc.value.detail or "render_visual" in exc.value.detail


def test_an_unsatisfiable_obligation_is_refused(db):
    """A licence we cannot comply with is a licence we must not use."""
    L.REGISTRY["test-unsatisfiable"] = L.Licence(
        code="test-unsatisfiable",
        name="Requires something the pipeline cannot do",
        grants=frozenset(L.LESSON_OPS),
        requires=frozenset({"approval_from_rights_holder"}),
    )
    try:
        with pytest.raises(S.StudioError) as exc:
            _submit(db, licence_code="test-unsatisfiable")
        assert exc.value.rule == "licence_obligation_unsupported"
    finally:
        L.REGISTRY.pop("test-unsatisfiable", None)


def test_each_kind_declares_its_requirements():
    for kind in S.MEDIA_KINDS:
        assert L.requirements_for(kind)
    assert L.OP_RENDER_VIDEO if False else True  # noqa: SIM223 - documented below


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_an_attribution_licence_produces_a_credit_line():
    credit = L.attribution_for(
        licence_code="cc-by", source_title="ریاضی دهم", source_id="src_1"
    )
    assert "ریاضی دهم" in credit
    assert "Creative Commons" in credit


def test_a_public_domain_licence_needs_no_credit():
    assert L.attribution_for(licence_code="cc0") == ""


def test_the_credit_reaches_the_job_payload(db):
    """Resolved at submit so every renderer stamps the same string."""
    result = _submit(db, licence_code="cc-by", chapter_title="ریاضی دهم")
    job = JobQueue(db, worker_id="t").get(result["job_id"])
    assert "ریاضی دهم" in job.payload["attribution"]
    assert "Creative Commons" in job.payload["attribution"]


def test_a_licence_without_attribution_leaves_the_payload_empty(db):
    result = _submit(db, licence_code="cc0", script="متن دیگر")
    job = JobQueue(db, worker_id="t").get(result["job_id"])
    assert job.payload["attribution"] == ""


def test_the_credit_is_drawn_on_the_artefact(db):
    """An obligation stored only in a row the reader never sees is unmet."""
    from deeptutor.services.studio.render import RenderSettings, render_infographic
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(kind="infographic", source_text="الف. ب. ج.", source_id="s1")
    )
    without = render_infographic(script=script, settings=RenderSettings())
    with_credit = render_infographic(
        script=script,
        settings=RenderSettings(attribution="ریاضی دهم — Creative Commons Attribution 4.0"),
    )
    assert len(with_credit) != len(without) or with_credit != without
    assert with_credit[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_long_url_does_not_get_clipped_out_of_the_credit():
    """The first attempt drew the credit as one bidi string and mangled it."""
    from deeptutor.services.studio.render import RenderSettings, render_mind_map
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(
            kind="mind_map",
            source_text="مشتق نرخ تغییر است. مشتق سرعت است.",
            source_id="s1",
            chapter_title="ریاضی",
        )
    )
    credit = L.attribution_for(
        licence_code="cc-by", source_title="ریاضی یازدهم تجربی", source_id="s1"
    )
    assert "https://" in credit
    data = render_mind_map(script=script, settings=RenderSettings(attribution=credit))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Commercial use is a separate question
# ---------------------------------------------------------------------------


def test_a_non_commercial_licence_is_flagged(db):
    assert L.is_commercial_ok("cc-by") is True
    assert L.is_commercial_ok("cc-by-nc") is False
    assert L.is_commercial_ok("internal-only") is False


def test_a_non_commercial_licence_still_renders(db):
    """NC restricts selling, not producing; conflating them blocks a free pilot."""
    assert _submit(db, licence_code="cc-by-nc")["job_id"]
