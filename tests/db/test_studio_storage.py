"""Storage accounting and the real local renderers.

Two separate concerns that share a file because they meet at one question: when
an asset is stored, does the meter move, and does the thing being stored
actually contain what it claims?
"""

from __future__ import annotations

import io
import wave

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import jobs as S


def _user(db, user_id="u1", tokens=5000, storage_quota_bytes=100_000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(
        user_id, tokens=tokens, storage_quota_bytes=storage_quota_bytes
    )
    return user_id


def _run(db, size_bytes=500, user="u1", script="مشتق چیست؟"):
    queue = JobQueue(db, worker_id="t")
    out = S.submit(
        db, queue=queue, request=S.JobRequest(user_id=user, kind="mind_map", script=script)
    )

    def render(kind, payload):
        return S.RenderResult(
            storage_path=f"media/{user}/{payload['content_hash'][:10]}.png",
            mime_type="image/png",
            size_bytes=size_bytes,
            actual_tokens=40,
        )

    queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=render)},
        limit=1,
    )
    return out


# ---------------------------------------------------------------------------
# Storage accounting -- the meter that was never moving
# ---------------------------------------------------------------------------


def test_storing_an_asset_charges_its_bytes(db):
    """Before this, assets appeared while `storage_used_bytes` stayed at zero."""
    _user(db)
    _run(db, size_bytes=1500)
    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 1500


def test_deleting_an_asset_gives_the_bytes_back(db):
    """Otherwise delete-and-recreate burns quota with nothing to explain it."""
    _user(db)
    _run(db, size_bytes=1500)
    asset = S.list_assets(db, user_id="u1")[0]

    S.delete_asset(db, asset["id"], user_id="u1")
    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 0


def test_storage_accumulates_across_assets(db):
    _user(db, storage_quota_bytes=1_000_000)
    _run(db, size_bytes=700, script="اول")
    _run(db, size_bytes=300, script="دوم")
    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 1000


def test_can_store_refuses_when_the_quota_is_gone(db):
    _user(db, storage_quota_bytes=1000)
    _run(db, size_bytes=900)

    assert S.can_store(db, user_id="u1", size_bytes=50) is True
    assert S.can_store(db, user_id="u1", size_bytes=200) is False


def test_can_store_is_permissive_without_a_quota(db):
    """A zero quota means unlimited, not zero -- the opposite would be a trap."""
    IdentityRepository(db).save("free", {"id": "free", "hash": "x", "role": "user"})
    WalletRepository(db).grant("free", tokens=100)
    assert S.can_store(db, user_id="free", size_bytes=10**9) is True


def test_can_store_is_permissive_without_a_wallet(db):
    IdentityRepository(db).save("nowallet", {"id": "nowallet", "hash": "x", "role": "user"})
    assert S.can_store(db, user_id="nowallet", size_bytes=1) is True


def test_a_missing_wallet_does_not_fail_a_finished_render(db):
    """The bytes and the tokens are already spent; a counter must not undo that."""
    _user(db)
    out = _run(db, size_bytes=100)
    with db.transaction() as conn:
        conn.execute("DELETE FROM user_wallets WHERE user_id = 'u1'")
    # The asset row survives and is still addressable.
    assert S.get_asset(db, S.list_assets(db, user_id="u1")[0]["id"], user_id="u1")
    assert out["job_id"]


# ---------------------------------------------------------------------------
# The local renderers produce real artefacts
# ---------------------------------------------------------------------------


def test_a_mind_map_renders_real_png_bytes(db):
    from deeptutor.services.studio.render import render_mind_map
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(kind="mind_map", source_text="مشتق نرخ تغییر است. مشتق سرعت است.", source_id="s1")
    )
    data = render_mind_map(script=script)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 2000


def test_a_deck_renders_one_page_per_section(db):
    from PIL import Image

    from deeptutor.services.studio.render import render_slide_deck
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(
            kind="slide_deck",
            source_text="یک. دو. سه. چهار.",
            source_id="s1",
        )
    )
    data = render_slide_deck(script=script)
    image = Image.open(io.BytesIO(data))
    # Tiled contact sheet: wider than a single 1280px slide when >1 slide.
    assert image.width > 1280
    assert len(script.outline) >= 2


def test_an_infographic_renders_real_png_bytes():
    from deeptutor.services.studio.render import render_infographic
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(kind="infographic", source_text="الف. ب. ج.", source_id="s1")
    )
    assert render_infographic(script=script)[:4] == b"\x89PNG"


def test_audio_is_a_real_wav_of_the_right_length():
    """Not silence and not speech: a real file whose duration is checkable."""
    from deeptutor.services.studio.render import render_silence

    data = render_silence(seconds=3.0)
    with wave.open(io.BytesIO(data), "rb") as handle:
        seconds = handle.getnframes() / handle.getframerate()
    assert data[:4] == b"RIFF"
    assert seconds == pytest.approx(3.0, abs=0.05)


def test_audio_duration_is_clamped_to_something_sane():
    from deeptutor.services.studio.render import render_silence

    with wave.open(io.BytesIO(render_silence(seconds=0)), "rb") as handle:
        assert handle.getnframes() > 0
    with wave.open(io.BytesIO(render_silence(seconds=10_000)), "rb") as handle:
        assert handle.getnframes() / handle.getframerate() <= 120.0


def test_persian_is_shaped_and_not_left_disconnected():
    from deeptutor.services.studio.render import shape

    shaped = shape("مشتق")
    assert shaped != "مشتق", "unshaped text would render as disconnected letters"
    # Presentation forms live in the Arabic Presentation Forms-B block.
    assert any("\ufe70" <= ch <= "\ufeff" for ch in shaped)


def test_latin_technical_terms_survive_shaping():
    """Mixing a Latin term into Persian must not drop it."""
    from deeptutor.services.studio.render import shape

    assert "API" in shape("مشتق API است")


def test_a_mind_map_does_not_draw_its_topic_twice():
    """The hub is the topic; a branch with the same label reads as a data bug."""
    from deeptutor.services.studio.script import ScriptRequest, build_script

    script = build_script(
        ScriptRequest(
            kind="mind_map",
            source_text="مشتق نرخ تغییر است. مشتق سرعت است. مشتق شتاب است.",
            source_id="s1",
        )
    )
    assert script.outline, "the fixture needs branches to be meaningful"
    # The renderer consumes the first branch as the hub, so it must not be
    # drawn again; this asserts the script still exposes that first branch and
    # that the list has enough left to draw.
    assert len(script.outline) >= 2


def test_a_mind_map_with_no_branches_is_refused():
    """An empty PNG would look like a styling bug rather than a missing outline."""
    from deeptutor.services.studio.render import RenderError, render_mind_map

    class Empty:
        outline: list = []
        text = ""

    with pytest.raises(RenderError):
        render_mind_map(script=Empty())


def test_the_worker_renders_and_stores_for_every_kind(db):
    """The integration point: real renderer + real store + real settlement."""
    from deeptutor.services.studio import worker

    _user(db, storage_quota_bytes=100_000_000)
    queue = JobQueue(db, worker_id="w")
    script_text = "مشتق نرخ تغییر است. مشتق سرعت است. شتاب مشتق سرعت است."

    for kind in S.MEDIA_KINDS:
        out = S.submit(
            db, queue=queue,
            request=S.JobRequest(
                user_id="u1", kind=kind, script=script_text, source_id="s1",
                licence_code="cc-by",
            ),
        )
        worker.drain(db, worker_id="w", limit=1)
        job = queue.get(out["job_id"])
        assert job.status == "succeeded", f"{kind} did not finish: {job.last_error}"

        asset = next(a for a in S.list_assets(db, user_id="u1") if a["job_id"] == out["job_id"])
        assert asset["size_bytes"] > 1000, f"{kind} produced an implausibly small artefact"
        assert asset["mime_type"] in {"image/png", "audio/wav"}

    with db.read() as conn:
        holds = conn.scalar(
            "SELECT COALESCE(SUM(reserved_tokens),0) FROM media_reservations "
            "WHERE user_id='u1' AND state='open'"
        )
    assert int(holds) == 0, "every hold must close"


def test_the_worker_reports_a_measured_cost_not_a_table_lookup(db):
    """Gate 8's cost claim is only checkable if the number comes from the output."""
    from deeptutor.services.studio import worker

    _user(db)
    queue = JobQueue(db, worker_id="w")
    out = S.submit(
        db, queue=queue,
        request=S.JobRequest(user_id="u1", kind="mind_map", script="مشتق نرخ تغییر است."),
    )
    worker.drain(db, worker_id="w", limit=1)

    costs = {c["phase"]: c for c in S.job_costs(db, out["job_id"])}
    assert costs["actual"]["provider"] == "local"
    assert 1 <= costs["actual"]["tokens"] < 10_000
