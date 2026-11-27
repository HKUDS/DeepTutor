"""The review package itself must be correct, or the review is worthless.

A package that ships broken artefacts, a form that loses verdicts, or a loader
that records them against the wrong asset would produce confident evidence of
nothing. These tests build the package and check the parts that carry meaning.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_review_package.py"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    out = tmp_path_factory.mktemp("review-package")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return out


def _manifest(package: Path) -> dict:
    return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Contents
# ---------------------------------------------------------------------------


def test_every_kind_gets_an_artefact(package):
    kinds = {entry["kind"] for entry in _manifest(package)["artefacts"]}
    assert kinds == {
        "infographic",
        "mind_map",
        "slide_deck",
        "audio_overview",
        "video_lesson",
    }


def test_every_artefact_file_exists_and_matches_its_hash(package):
    import hashlib

    for entry in _manifest(package)["artefacts"]:
        path = package / "artefacts" / entry["asset"]
        assert path.exists(), entry["asset"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], (
            f"{entry['asset']} does not match the hash in the manifest: the "
            f"verdict would be tied to a file nobody reviewed"
        )


def test_every_artefact_has_a_checklist(package):
    for entry in _manifest(package)["artefacts"]:
        assert entry["checklist"], entry["asset"]
        for item in entry["checklist"]:
            assert item["id"] and item["question"]


def test_the_source_text_is_the_real_source(package):
    """A reviewer cannot check traceability against a summary."""
    for entry in _manifest(package)["artefacts"]:
        assert len(entry["source_text"]) > 80, entry["asset"]


def test_the_renderer_note_is_carried_through(package):
    """The reviewer must know a storyboard is not a video."""
    video = next(
        e for e in _manifest(package)["artefacts"] if e["kind"] == "video_lesson"
    )
    assert "storyboard" in video["renderer_note"].lower()
    audio = next(
        e for e in _manifest(package)["artefacts"] if e["kind"] == "audio_overview"
    )
    assert "TTS" in audio["renderer_note"] or "placeholder" in audio["renderer_note"]


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------


def test_the_form_is_self_contained(package):
    html = (package / "review.html").read_text(encoding="utf-8")
    assert "<script" in html
    # No network: a reviewer may be offline, and a CDN would break the form.
    assert "http://" not in html.replace("https://creativecommons.org", "")
    assert 'src="artefacts/' in html


def test_the_form_has_no_hidden_requirement_to_be_online(package):
    html = (package / "review.html").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in html
    assert "cdn." not in html


def test_the_form_offers_exactly_three_verdicts(package):
    html = (package / "review.html").read_text(encoding="utf-8")
    for verdict in ("pass", "fail", "unclear"):
        assert f'value="{verdict}"' in html
    assert 'value="maybe"' not in html


def test_the_form_requires_a_reviewer_name(package):
    html = (package / "review.html").read_text(encoding="utf-8")
    assert 'id="reviewer"' in html
    assert "نام یا شناسهٔ خود را بنویسید" in html


# ---------------------------------------------------------------------------
# The verdict template and the loader
# ---------------------------------------------------------------------------


def test_the_template_covers_every_question(package):
    manifest = _manifest(package)
    template = json.loads((package / "verdict_template.json").read_text(encoding="utf-8"))
    expected = sum(len(entry["checklist"]) for entry in manifest["artefacts"])
    assert len(template["verdicts"]) == expected
    assert all(row["verdict"] == "" for row in template["verdicts"])


def test_the_loader_refuses_a_self_review(package, tmp_path):
    """A self-review recorded as independent is exactly the false evidence
    Gate 8 exists to prevent."""
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({"verdicts": []}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(package / "load_verdict.py"),
            "--verdict",
            str(verdict),
            "--db",
            "sqlite:///:memory:",
            "--owner",
            "u1",
            "--reviewer",
            "u1",
            "--registry",
            str(registry),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not independent" in result.stderr


def test_the_loader_is_executable(package):
    import os

    assert os.access(package / "load_verdict.py", os.X_OK)


def test_the_readme_states_what_the_package_does_not_prove(package):
    readme = (package / "README.md").read_text(encoding="utf-8")
    assert "ویدیو یک فایل ویدیو نیست" in readme
    assert "صدا گفتار نیست" in readme


def test_the_readme_lists_the_defects_the_author_already_sees(package):
    """Asking a reviewer to find them would be asking them to do my job first."""
    readme = (package / "README.md").read_text(encoding="utf-8")
    assert "نقص‌هایی که خودم می‌بینم" in readme
    assert "سه شرط پیوستگی" in readme


# ---------------------------------------------------------------------------
# The loop: a package verdict becomes independent evidence
# ---------------------------------------------------------------------------


def test_a_package_verdict_moves_the_independent_count(db):
    """The whole point of the package: a reviewer's file becomes a number.

    If this does not work, the package is paperwork -- the form produces a file
    and nothing downstream reads it, so `independent_reviews` stays zero no
    matter how many humans filled in the form.
    """
    from deeptutor.db.jobs.queue import JobQueue
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.db.repositories.wallets import WalletRepository
    from deeptutor.services.studio import jobs as S

    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=500_000)
    queue = JobQueue(db, worker_id="t")
    submitted = S.submit(
        db, queue=queue, request=S.JobRequest(user_id="u1", kind="mind_map", script="مشتق چیست؟")
    )

    def renderer(kind, payload):
        return S.RenderResult(
            storage_path="m/x.png", mime_type="image/png", size_bytes=10,
            actual_tokens=10, provider="local", content="مشتق",
        )

    while queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)}
    ):
        pass
    with db.read() as conn:
        asset_id = conn.query_one(
            "SELECT id FROM media_assets WHERE job_id = ?", (submitted["job_id"],)
        )["id"]

    from deeptutor.services.studio.script import quality_checklist

    items = [item["id"] for item in quality_checklist("mind_map")]

    for item in items:
        S.record_review(
            db, asset_id=asset_id, user_id="u1", item_id=item, verdict="pass", reviewer_id="u1"
        )
    own = S.review_status(db, asset_id, user_id="u1")
    assert own["complete"] is True
    assert own["independent_reviews"] == 0, "a self-review must not count as independent"
    assert own["independently_reviewed"] is False

    for item in items:
        S.record_review(
            db, asset_id=asset_id, user_id="u1", item_id=item,
            verdict="pass", reviewer_id="teacher-01",
        )
    after = S.review_status(db, asset_id, user_id="u1")
    assert after["independent_reviews"] == len(items)
    assert after["independently_reviewed"] is True


def test_a_fail_verdict_survives_the_round_trip(db):
    """A verdict of fail must be recorded as fail, not coerced or dropped."""
    from deeptutor.db.jobs.queue import JobQueue
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.db.repositories.wallets import WalletRepository
    from deeptutor.services.studio import jobs as S

    IdentityRepository(db).save("u2", {"id": "u2", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u2", tokens=500_000)
    queue = JobQueue(db, worker_id="t")
    submitted = S.submit(
        db, queue=queue, request=S.JobRequest(user_id="u2", kind="mind_map", script="متن")
    )

    def renderer(kind, payload):
        return S.RenderResult(
            storage_path="m/y.png", mime_type="image/png", size_bytes=10,
            actual_tokens=10, provider="local", content="متن",
        )

    while queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)}
    ):
        pass
    with db.read() as conn:
        asset_id = conn.query_one(
            "SELECT id FROM media_assets WHERE job_id = ?", (submitted["job_id"],)
        )["id"]

    S.record_review(
        db, asset_id=asset_id, user_id="u2", item_id="persian_register",
        verdict="fail", comment="جمله‌ها ترجمهٔ ماشینی‌اند", reviewer_id="teacher-02",
    )
    status = S.review_status(db, asset_id, user_id="u2")
    assert "persian_register" in status["failures"]
    assert status["items"][0]["verdicts"][0]["comment"] == "جمله‌ها ترجمهٔ ماشینی‌اند"
