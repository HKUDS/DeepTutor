from deeptutor.services.partner_groups import consultation
from deeptutor.services.partner_groups.consultation import ConsultationWindow


def test_idle_boundary_tracks_activity_drafts_and_all_operations(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(consultation.time, "monotonic", lambda: now[0])
    window = ConsultationWindow(last_activity=0)
    assert window.remaining(busy=True, revision=1) is None
    now[0] = 20
    assert window.remaining(busy=False, revision=2) == 10
    now[0] = 29
    assert window.remaining(busy=False, revision=2) == 1
    window.activity("sidebar", has_draft=False, active=True)
    assert window.remaining(busy=False, revision=2) == 10
    now[0] = 38
    window.activity("sidebar", has_draft=True, active=True)
    assert window.remaining(busy=False, revision=2) is None
    now[0] = 50
    window.activity("sidebar", has_draft=True, active=False)
    assert window.remaining(busy=False, revision=2) is None
    window.activity("sidebar", has_draft=False, active=True)
    assert window.remaining(busy=True, revision=3) is None
    now[0] = 60
    assert window.remaining(busy=False, revision=4) == 10
    now[0] = 69
    window.activity("sidebar", has_draft=False, active=False)
    assert window.remaining(busy=False, revision=4) == 1
    now[0] = 70
    assert window.remaining(busy=False, revision=4) == 0


def test_disconnected_or_stale_draft_does_not_block_forever(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(consultation.time, "monotonic", lambda: now[0])
    window = ConsultationWindow(last_activity=0)
    window.activity("tab1", has_draft=True, active=True)
    window.activity("tab2", has_draft=True, active=True)
    window.disconnect("tab1")
    assert window.remaining(busy=False, revision=1) is None
    now[0] = 7
    assert window.remaining(busy=False, revision=1) == 10
    now[0] = 17
    assert window.remaining(busy=False, revision=1) == 0
