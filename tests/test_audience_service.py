from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.audience_service import AudienceService, TrustedAudienceEvent
from rareiq.web.audience import create_audience_router


def rule(**changes):
    return {"id": "welcome", "name": "Welcome", "enabled": True, "platform": "any", "event": "first_chat",
            "message": "Welcome, {name}!", "animation": "slide", "duration_ms": 3000, "cooldown_seconds": 60, **changes}


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    service = AudienceService(tmp_path / "audience.sqlite3", clock=lambda: now[0])
    service.status()
    return service, now


def configure(service, action, data, request_id=None, revision=None):
    return service.configure(action=action, data=data, expected_revision=service.status()["revision"] if revision is None else revision,
                             request_id=request_id or str(service.status()["revision"]), actor_kind="local_operator")


def event(now, **changes):
    return TrustedAudienceEvent("twitch", "channel", changes.get("event_id", "one"), changes.get("subject_id", "viewer"),
                                changes.get("display_name", "Guest"), changes.get("kind", "chat"), changes.get("occurred_at", now[0]))


def arm(service, **changes):
    configure(service, "save_rule", rule(**changes))
    configure(service, "settings", {"enabled": True})


def test_first_chat_deduplicates_and_never_counts_reconnect_as_an_arrival(setup):
    service, now = setup
    arm(service)
    assert service.accept(event(now))["queued"] == 1
    assert service.accept(event(now))["duplicate"] is True
    assert service.accept(event(now, event_id="two"))["queued"] == 0
    state = service.status()
    assert state["participants"] == [{"platform": "twitch", "channel_id": "channel", "subject_id": "viewer", "label": "Guest", "observed_chats": 2, "featured": False}]
    assert state["queued"] == 1
    assert service.output()["graphic"]["subtitle"] == "First chat this session"


def test_stale_backlog_future_and_prior_session_events_fail_closed(setup):
    service, now = setup
    arm(service)
    for when in (999, 800, 1006):
        assert service.accept(event(now, occurred_at=when))["reason"] == "audience_event_outside_session"
    assert not service.status()["participants"]
    assert not service.output()["graphic"]


def test_preview_never_touches_history_participants_or_program(setup):
    service, _ = setup
    arm(service)
    before = service.status()
    preview = service.preview(rule(), '<img src=x onerror="alert(1)">')
    assert preview["simulation"] is True
    assert preview["graphic"]["title"].startswith("Welcome, <img")
    assert service.status() == before
    assert service.output()["graphic"] is None
    with pytest.raises(ValueError, match="trusted_server_event"):
        service.accept({"verified": True, "platform": "twitch"})


def test_disabled_rules_keep_observed_ledger_and_stop_all_clears_scheduled_graphics(setup):
    service, now = setup
    configure(service, "save_rule", rule())
    assert service.accept(event(now))["queued"] == 0
    assert service.status()["participants"][0]["observed_chats"] == 1
    configure(service, "settings", {"enabled": True})
    assert service.accept(event(now, event_id="two", subject_id="other"))["queued"] == 1
    configure(service, "settings", {"enabled": False})
    assert service.status()["queued"] == 0 and service.output()["graphic"] is None


def test_featured_matching_uses_platform_channel_and_account_id(setup):
    service, now = setup
    arm(service, event="featured_chat")
    configure(service, "feature", {"platform": "twitch", "channel_id": "channel", "subject_id": "chosen", "label": "Same name"})
    assert service.accept(event(now, display_name="Same name"))["queued"] == 0
    assert service.accept(event(now, event_id="chosen", subject_id="chosen", display_name="Renamed"))["queued"] == 1
    assert service.output()["graphic"]["title"] == "Welcome, Renamed!"
    assert service.accept(event(now, event_id="chosen2", subject_id="chosen"))["queued"] == 0
    now[0] += 61
    assert service.accept(event(now, event_id="chosen3", subject_id="chosen"))["queued"] == 1
    assert "_participant_key" not in service.output()["graphic"]
    configure(service, "unfeature", {"platform": "twitch", "channel_id": "channel", "subject_id": "chosen"})
    assert service.output()["graphic"] is None


def test_disabling_a_rule_also_cancels_its_pending_animation(setup):
    service, now = setup
    arm(service)
    service.accept(event(now))
    configure(service, "save_rule", rule(enabled=False))
    assert service.output()["graphic"] is None


def test_schedule_has_global_capacity_and_expires_without_overlay_consumers(setup):
    service, now = setup
    arm(service, event="follow", duration_ms=10000)
    for index in range(25):
        service.accept(event(now, kind="follow", event_id=str(index), subject_id=str(index)))
    assert service.status()["queued"] <= service.MAX_QUEUE
    assert service.status()["queued"] == 4  # Last accepted start is 30 seconds away.
    first = service.output()["graphic"]
    assert first["starts_at"] == now[0] and first["ends_at"] == now[0] + 10
    assert first["remaining_ms"] == 10000
    now[0] += 41
    assert service.status()["queued"] == 0 and service.output()["graphic"] is None


def test_config_revision_receipt_and_audit_are_atomic(setup):
    service, _ = setup
    saved = configure(service, "save_rule", rule(), request_id="saved", revision=0)
    assert configure(service, "save_rule", rule(), request_id="saved", revision=0) == saved
    assert configure(service, "save_rule", rule(name="Other"), request_id="saved", revision=0)["reason"] == "audience_request_conflict"
    assert configure(service, "settings", {"enabled": True}, request_id="stale", revision=0)["reason"] == "audience_revision_conflict"
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER reject_audience_audit BEFORE INSERT ON audience_audit BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        configure(service, "settings", {"enabled": True})
    assert service.status()["revision"] == 1 and not service.status()["enabled"]
    assert len(service.status()["history"]) == 1


def test_event_queue_participant_and_receipt_commit_together(setup):
    service, now = setup
    arm(service)
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER reject_audience_event BEFORE INSERT ON audience_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.accept(event(now))
    assert service.status()["participants"] == [] and service.output()["graphic"] is None


def test_concurrent_duplicate_events_queue_once(setup):
    service, now = setup
    arm(service)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.accept(event(now)), range(2)))
    assert sum(result["queued"] for result in results) == 1
    assert service.status()["participants"][0]["observed_chats"] == 1


def test_restart_keeps_rules_and_dedup_but_disarms_and_clears_queue(setup):
    service, now = setup
    arm(service)
    service.accept(event(now))
    restarted = AudienceService(service.path, clock=lambda: now[0])
    state = restarted.status()
    assert len(state["rules"]) == 1 and not state["enabled"] and state["queued"] == 0
    assert restarted.accept(event(now))["duplicate"] is True
    assert not state["participants"]


def test_new_session_pauses_clears_seen_and_keeps_featured_rules(setup):
    service, now = setup
    arm(service)
    service.accept(event(now))
    now[0] += 1
    configure(service, "session", {})
    state = service.status()
    assert not state["enabled"] and not state["participants"] and len(state["rules"]) == 1
    configure(service, "settings", {"enabled": True})
    assert service.accept(event(now, event_id="fresh"))["queued"] == 1


@pytest.mark.parametrize("changes", [{"message": "Welcome {unknown}"}, {"url": "https://example.invalid"}, {"duration_ms": 50000}, {"cooldown_seconds": 0}, {"enabled": "yes"}, {"animation": "javascript"}])
def test_rule_rejects_unsupported_templates_urls_and_unbounded_fields(setup, changes):
    with pytest.raises(ValueError):
        setup[0].preview(rule(**changes), "Guest")


def test_browser_endpoints_cannot_submit_verified_events_or_actor(setup, tmp_path):
    service, _ = setup
    app = FastAPI()
    app.include_router(create_audience_router(service, tmp_path))
    http = TestClient(app, client=("127.0.0.1", 50000))
    try:
        payload = {"action": "settings", "data": {"enabled": True}, "expected_revision": 0, "request_id": "http"}
        for extra in ({"actor_kind": "owner"}, {"verified": True}):
            assert http.post('/api/production/audience/configure', json=payload | extra).status_code == 400
        assert http.post('/api/production/audience/configure', json=payload | {"action": "ingest"}).status_code == 400
        assert http.post('/api/production/audience/ingest', json={"verified": True}).status_code == 404
        assert http.post('/api/production/audience/configure', json=payload).status_code == 200
        assert http.post('/api/production/audience/configure', json=payload, headers={"Origin": "https://untrusted.invalid"}).status_code == 400
        assert http.post('/api/production/audience/configure', json=payload, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 400
        assert http.get('/api/production/audience').json()["history"][0]["identity_verified"] is False
        assert http.post('/api/production/audience/preview', json={"rule": rule(), "display_name": "Sample"}).json()["simulation"] is True
        assert http.get('/api/production/audience/output').json()["graphic"] is None
        assert http.get('/api/production/audience/output').headers['cache-control'] == 'no-store'
        assert http.post('/api/production/audience/preview', content=b'x' * 17000).status_code == 400
    finally:
        http.close()


def test_observed_account_can_be_featured_without_exposing_ids_in_output_or_audit(setup):
    service, now = setup
    arm(service, event="featured_chat")
    service.accept(event(now, event_id="seen"))
    participant = service.status()["participants"][0]
    assert participant["featured"] is False
    configure(service, "feature", {key: participant[key] for key in ("platform", "channel_id", "subject_id", "label")})
    assert service.status()["participants"][0]["featured"] is True
    assert service.accept(event(now, event_id="future"))["queued"] == 1
    graphic = service.output()["graphic"]
    assert graphic["subtitle"] == "Featured participant"
    public = json.dumps({"graphic": graphic, "history": service.status()["history"]})
    assert "subject_id" not in public and "channel_id" not in public and '"viewer"' not in public
