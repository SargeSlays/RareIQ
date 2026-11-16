from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from rareiq.services.greenroom_service import EMPTY_MEDIA, GreenroomError, GreenroomService
from rareiq.web.shared_scene_access import VerifiedPrincipal


@pytest.fixture
def room(tmp_path):
    now = [10_000.0]
    service = GreenroomService(tmp_path / "room.sqlite3", clock=lambda: now[0])
    return service, now


def join(service, number=1, name="Fixture guest"):
    invite = service.create_invite("Fixture invitation")
    token = f"{number:064x}"
    participant = service.join(invite["token"], name, token)
    return invite, participant, token


def code(error, expected, status=None):
    assert error.value.reason == expected
    if status is not None:
        assert error.value.status == status


def test_single_use_invite_retry_and_session_hijack_protection(room):
    service, _ = room
    invite, participant, token = join(service)
    assert participant["state"] == "waiting"
    assert service.join(invite["token"], "Fixture guest", token) == participant
    with pytest.raises(GreenroomError) as error:
        service.join(invite["token"], "Intruder", "f" * 64)
    code(error, "invitation_already_used", 409)
    with pytest.raises(GreenroomError):
        service.join(invite["token"], "Changed identity", token)
    assert service.authenticate(token) == participant
    assert len([e for e in service.history()["events"] if e["action"] == "guest.joined"]) == 1


def test_waiting_admission_connection_and_media_all_gate_source_availability(room):
    service, _ = room
    _, participant, _ = join(service)
    camera, screen = participant["sources"]["camera"], participant["sources"]["screen"]
    service.set_connected(participant["id"], True)
    media = {"camera": True, "microphone": True, "screen": False, "screen_audio": False}
    service.update_media(participant["id"], media)
    assert not service.source_available(camera)
    service.moderate(participant["id"], "admit")
    assert service.source_available(camera) and not service.source_available(screen)
    service.update_media(participant["id"], media | {"screen": True, "screen_audio": True})
    assert service.source_available(screen)
    service.set_connected(participant["id"], False)
    assert not service.source_available(camera) and not service.source_available(screen)
    assert service.snapshot()["participants"][0]["media"] == EMPTY_MEDIA
    service.set_connected(participant["id"], True)
    assert not service.source_available(camera)  # Reconnect must publish fresh availability.


def test_audio_only_guest_has_admission_gated_audio_source(room):
    service, _ = room
    _, participant, _ = join(service)
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"microphone": True})
    assert not service.source_available(participant["sources"]["audio"])
    service.moderate(participant["id"], "admit")
    assert service.source_available(participant["sources"]["audio"])
    assert not service.source_available(participant["sources"]["camera"])


def test_media_validation_never_coerces_booleans_or_unknown_fields(room):
    service, _ = room
    _, participant, _ = join(service)
    for media in ({"camera": True}, EMPTY_MEDIA | {"camera": 1}, EMPTY_MEDIA | {"actor": "owner"}, EMPTY_MEDIA | {"screen_audio": True}):
        with pytest.raises(GreenroomError) as error:
            service.update_media(participant["id"], media)
        code(error, "invalid_guest_media")
    with pytest.raises(GreenroomError):
        service.set_connected(participant["id"], "true")


def test_program_audio_defaults_and_waiting_guest_can_be_pre_muted(room):
    service, _ = room
    _, participant, token = join(service)
    assert participant["program_audio"] == {"microphone_muted": False, "screen_muted": False}
    flags = {"microphone_muted": True, "screen_muted": False}
    result = service.moderate(participant["id"], "program_audio", **flags)
    current = service.authenticate(token)
    assert result["program_audio"] == current["program_audio"] == flags
    assert current["state"] == "waiting" and not current["connected"]
    assert current["media"] == EMPTY_MEDIA
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], dict.fromkeys(EMPTY_MEDIA, True))
    service.moderate(participant["id"], "admit")
    current = service.authenticate(token)
    assert current["program_audio"] == flags
    assert all(current["media"].values()) and current["connected"]
    assert all(service.source_available(source) for source in current["sources"].values())


def test_program_audio_migration_preserves_existing_guests_and_is_repeatable(room):
    service, now = room
    _, participant, token = join(service)
    # Reconstruct the pre-mute schema while preserving an existing guest row.
    with sqlite3.connect(service.path) as db:
        db.execute("ALTER TABLE greenroom_participants DROP COLUMN microphone_muted")
        db.execute("ALTER TABLE greenroom_participants DROP COLUMN screen_muted")
    migrated = GreenroomService(service.path, clock=lambda: now[0], reset_runtime=False)
    flags = {"microphone_muted": False, "screen_muted": False}
    assert migrated.authenticate(token)["program_audio"] == flags
    _, fresh, _ = join(migrated, 2)
    assert fresh["program_audio"] == flags
    migrated.moderate(participant["id"], "program_audio", microphone_muted=True, screen_muted=True)
    reopened = GreenroomService(service.path, clock=lambda: now[0], reset_runtime=False)
    assert all(reopened.authenticate(token)["program_audio"].values())


def test_program_audio_disconnect_and_restart_preserve_policy_but_clear_media(room):
    service, now = room
    _, participant, token = join(service)
    service.moderate(participant["id"], "program_audio", microphone_muted=True, screen_muted=True)
    service.moderate(participant["id"], "admit")
    for operation in ("disconnect", "restart"):
        service.set_connected(participant["id"], True)
        service.update_media(participant["id"], dict.fromkeys(EMPTY_MEDIA, True))
        if operation == "disconnect":
            service.set_connected(participant["id"], False)
        else:
            service = GreenroomService(service.path, clock=lambda: now[0])
        current = service.authenticate(token)
        assert all(current["program_audio"].values())
        assert current["media"] == EMPTY_MEDIA and not current["connected"]
        assert not any(service.source_available(source) for source in current["sources"].values())


@pytest.mark.parametrize("flags", [{}, {"microphone_muted": True}, {"screen_muted": False},
                                     {"microphone_muted": 1, "screen_muted": False},
                                     {"microphone_muted": False, "screen_muted": "true"}])
def test_program_audio_requires_exact_boolean_flags(room, flags):
    service, _ = room
    _, participant, _ = join(service)
    with pytest.raises(GreenroomError) as error:
        service.moderate(participant["id"], "program_audio", **flags)
    code(error, "invalid_program_audio")
    assert not any(service.snapshot()["participants"][0]["program_audio"].values())


def test_program_audio_cas_receipts_and_private_audit(room):
    service, _ = room
    invitation, participant, token = join(service, name="Private display name")
    flags = {"microphone_muted": True, "screen_muted": False}
    revision = service.snapshot()["revision"]
    request = dict(expected_revision=revision, request_id="mute-microphone", **flags)
    result = service.moderate(participant["id"], "program_audio", actor_kind="paired_lan_operator", **request)
    assert service.moderate(participant["id"], "program_audio", actor_kind="paired_lan_operator", **request) == result
    assert result["participant"] == {"id": participant["id"], "state": "waiting"}
    for request_id, expected in (("mute-microphone", "room_request_conflict"), ("stale", "room_revision_conflict")):
        with pytest.raises(GreenroomError) as error:
            service.moderate(participant["id"], "program_audio", actor_kind="paired_lan_operator",
                             **(request | {"request_id": request_id, "screen_muted": True}))
        code(error, expected, 409)
    events = [e for e in service.history()["events"] if e["action"] == "guest.program_audio" and e["outcome"] == "succeeded"]
    assert len(events) == 1
    assert events[0]["actor_kind"] == "paired_lan_operator" and not events[0]["identity_verified"]
    assert events[0]["details"] == {"before": {"microphone_muted": False, "screen_muted": False}, "after": flags}
    serialized = json.dumps(events)
    assert all(secret not in serialized for secret in (invitation["token"], token, "Private display name"))
    unchanged = service.moderate(participant["id"], "program_audio", expected_revision=result["revision"], request_id="same-flags", **flags)
    assert unchanged["revision"] == result["revision"]
    service.moderate(participant["id"], "program_audio", microphone_muted=False, screen_muted=True)
    assert service.authenticate(token)["program_audio"] == {"microphone_muted": False, "screen_muted": True}


@pytest.mark.parametrize("operation", ["remove", "revoke", "leave", "close", "expire"])
def test_program_audio_cannot_resurrect_unavailable_guest(room, operation):
    service, now = room
    invitation, participant, _ = join(service)
    service.moderate(participant["id"], "program_audio", microphone_muted=True, screen_muted=True)
    if operation == "remove":
        service.moderate(participant["id"], "remove")
    elif operation == "revoke":
        service.revoke_invite(invitation["invite_id"])
    elif operation == "leave":
        service.leave(participant["id"])
    elif operation == "close":
        service.close_room()
    else:
        now[0] += 12 * 3600
    with pytest.raises(GreenroomError) as error:
        service.moderate(participant["id"], "program_audio", microphone_muted=False, screen_muted=False)
    code(error, "guest_unavailable", 404)
    current = service.snapshot()["participants"][0]
    assert all(current["program_audio"].values())
    assert current["state"] == "removed" and current["media"] == EMPTY_MEDIA


def test_program_audio_guest_identity_is_forbidden_and_audit_failure_rolls_back(room):
    service, _ = room
    _, participant, _ = join(service)
    flags = {"microphone_muted": True, "screen_muted": True}
    with pytest.raises(GreenroomError) as error:
        service.moderate(participant["id"], "program_audio", actor_kind="guest_session", **flags)
    code(error, "invalid_producer_identity", 403)
    with pytest.raises(GreenroomError):
        service.update_media(participant["id"], EMPTY_MEDIA | {"program_audio": flags})
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER reject_audio_audit BEFORE INSERT ON greenroom_activity BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.moderate(participant["id"], "program_audio", request_id="mute", **flags)
    assert not any(service.snapshot()["participants"][0]["program_audio"].values())
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM greenroom_requests").fetchone()[0] == 0


def test_expired_invitation_and_session_do_not_allow_join_or_sources(room):
    service, now = room
    invite = service.create_invite(ttl_minutes=1)
    now[0] += 60
    with pytest.raises(GreenroomError) as error:
        service.join(invite["token"], "Fixture", "a" * 64)
    code(error, "invitation_expired", 410)
    _, participant, token = join(service)
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
    service.moderate(participant["id"], "admit")
    now[0] += 12 * 3600
    with pytest.raises(GreenroomError) as error:
        service.authenticate(token)
    code(error, "invalid_guest_session", 401)
    assert not service.source_available(participant["sources"]["camera"])
    expired = service.snapshot()["participants"][0]
    assert expired["expired"] and expired["state"] == "removed" and not expired["connected"]


@pytest.mark.parametrize("operation", ["remove", "revoke", "leave", "close"])
def test_removal_revokes_auth_and_clears_sources(room, operation):
    service, _ = room
    invite, participant, token = join(service)
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True, "microphone": True})
    service.moderate(participant["id"], "admit")
    if operation == "remove":
        service.moderate(participant["id"], "remove")
    elif operation == "revoke":
        service.revoke_invite(invite["invite_id"])
    elif operation == "leave":
        assert service.leave(participant["id"]) == service.leave(participant["id"])
    else:
        service.close_room()
    with pytest.raises(GreenroomError):
        service.authenticate(token)
    with pytest.raises(GreenroomError):
        service.join(invite["token"], "Fixture guest", token)
    assert not service.source_available(participant["sources"]["camera"])
    assert service.snapshot()["participants"][0]["media"] == EMPTY_MEDIA


def test_capacity_counts_live_unconsumed_invites_and_active_guests(tmp_path):
    now = [500.0]
    service = GreenroomService(tmp_path / "small.sqlite3", max_guests=1, max_invites=1, clock=lambda: now[0])
    first = service.create_invite(ttl_minutes=1)
    with pytest.raises(GreenroomError) as error:
        service.create_invite()
    code(error, "invitation_capacity_reached")
    guest = service.join(first["token"], "One", "a" * 64)
    second = service.create_invite()
    with pytest.raises(GreenroomError) as error:
        service.join(second["token"], "Two", "b" * 64)
    code(error, "guest_capacity_reached")
    service.leave(guest["id"])
    assert service.join(second["token"], "Two", "b" * 64)["state"] == "waiting"


def test_concurrent_invite_redemption_has_one_owner(room):
    service, now = room
    other = GreenroomService(service.path, clock=lambda: now[0])
    invite = service.create_invite()

    def redeem(item):
        index, instance = item
        try:
            return instance.join(invite["token"], "Guest", f"{index:064x}")
        except GreenroomError as error:
            return {"reason": error.reason}

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(redeem, [(1, service), (2, other)]))
    assert sum("id" in result for result in results) == 1
    assert len(service.snapshot()["participants"]) == 1


def test_process_restart_retains_sessions_but_clears_media_readiness(room):
    service, now = room
    _, participant, token = join(service)
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
    service.moderate(participant["id"], "admit")
    restarted = GreenroomService(service.path, clock=lambda: now[0])
    assert restarted.authenticate(token)["state"] == "admitted"
    assert not restarted.authenticate(token)["connected"]
    assert restarted.authenticate(token)["media"] == EMPTY_MEDIA
    assert not restarted.source_available(participant["sources"]["camera"])
    assert restarted.history()["events"][0]["action"] == "room.restarted"


def test_app_import_can_initialize_without_resetting_active_guest_runtime(room):
    service, now = room
    _, participant, token = join(service)
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
    imported = GreenroomService(service.path, clock=lambda: now[0], reset_runtime=False)
    assert imported.authenticate(token)["connected"] is True
    assert imported.authenticate(token)["media"]["camera"] is True
    imported.reset_runtime()
    assert imported.authenticate(token)["connected"] is False
    count = len(imported.history()["events"])
    imported.reset_runtime()
    assert len(imported.history()["events"]) == count


def test_closed_room_requires_explicit_new_room_and_never_reuses_capabilities(room):
    service, _ = room
    invite, _, token = join(service)
    old_room = service.snapshot()["room_id"]
    closed = service.close_room(request_id="close")
    assert closed == service.close_room(request_id="close")
    with pytest.raises(GreenroomError) as error:
        service.create_invite()
    code(error, "room_closed")
    opened = service.open_room(expected_revision=closed["revision"], request_id="open")
    assert opened == service.open_room(expected_revision=closed["revision"], request_id="open")
    assert opened["room_id"] != old_room
    assert service.snapshot()["participants"] == []
    with pytest.raises(GreenroomError):
        service.join(invite["token"], "Fixture guest", token)
    with pytest.raises(GreenroomError):
        service.authenticate(token)


def test_producer_preconditions_and_receipts_do_not_reexecute_actions(room):
    service, _ = room
    _, participant, _ = join(service)
    revision = service.snapshot()["revision"]
    first = service.moderate(participant["id"], "admit", expected_revision=revision, request_id="admit")
    assert service.moderate(participant["id"], "admit", expected_revision=revision, request_id="admit") == first
    with pytest.raises(GreenroomError) as error:
        service.moderate(participant["id"], "remove", expected_revision=revision, request_id="admit")
    code(error, "room_request_conflict", 409)
    with pytest.raises(GreenroomError) as error:
        service.moderate(participant["id"], "remove", expected_revision=revision, request_id="stale")
    code(error, "room_revision_conflict", 409)
    assert service.snapshot()["participants"][0]["state"] == "admitted"
    assert service.history()["events"][0]["outcome"] == "room_revision_conflict"


def test_invitation_secret_returned_once_even_on_retry_and_never_stored(room):
    service, _ = room
    created = service.create_invite(request_id="invite", expected_revision=0)
    repeated = service.create_invite(request_id="invite", expected_revision=0)
    assert repeated["invite_id"] == created["invite_id"]
    assert repeated["token"] is None and not repeated["token_available"]
    assert created["token"] not in service.path.read_bytes().decode("latin1")
    assert created["token"] not in json.dumps(service.snapshot())
    assert created["token"] not in json.dumps(service.history())


def test_session_hash_and_safe_audit_do_not_record_names_or_tokens(room):
    service, _ = room
    invite, participant, token = join(service, name="Private display name")
    principal = VerifiedPrincipal("fixture", "studio", "verified-subject")
    service.moderate(participant["id"], "admit", principal=principal)
    history = service.history()["events"]
    assert history[0]["identity_verified"] is True
    assert history[0]["actor_id"] == '["fixture","studio","verified-subject"]'
    assert history[1]["actor_kind"] == "guest_session" and not history[1]["identity_verified"]
    serialized = json.dumps(history)
    assert all(value not in serialized for value in (token, invite["token"], "Private display name"))
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT session_hash FROM greenroom_participants").fetchone()[0] != token
        for sql in ("UPDATE greenroom_activity SET action='forged'", "DELETE FROM greenroom_activity"):
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                db.execute(sql)


def test_moderation_receipts_are_minimal_and_history_correlates_request_id(room):
    service, _ = room
    _, participant, _ = join(service, name="Private display name")
    result = service.moderate(participant["id"], "admit", request_id="fixture-admit")
    assert result["participant"] == {"id": participant["id"], "state": "admitted"}
    assert service.history()["events"][0]["request_id"] == "fixture-admit"
    with sqlite3.connect(service.path) as db:
        receipt = db.execute("SELECT result FROM greenroom_requests").fetchone()[0]
    assert "Private display name" not in receipt and "media" not in receipt


def test_activity_failure_rolls_back_invite_redemption_and_moderation(room):
    service, _ = room
    invite = service.create_invite()
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER reject_activity BEFORE INSERT ON greenroom_activity BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.join(invite["token"], "Fixture", "a" * 64)
    assert service.snapshot()["participants"] == []
    assert service.snapshot()["invites"][0]["status"] == "ready"
    with sqlite3.connect(service.path) as db:
        db.execute("DROP TRIGGER reject_activity")
    participant = service.join(invite["token"], "Fixture", "a" * 64)
    with sqlite3.connect(service.path) as db:
        db.execute("CREATE TRIGGER reject_activity BEFORE INSERT ON greenroom_activity BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.moderate(participant["id"], "admit", request_id="admit")
    assert service.snapshot()["participants"][0]["state"] == "waiting"
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM greenroom_requests").fetchone()[0] == 0


def test_production_intent_and_renderer_receipt_remain_distinct_idempotent_events(room):
    service, _ = room
    requested = service.record_production_event("program.take", "camera:2", "requested", request_id="take-1", details={"generation": 1, "duration_ms": 500})
    assert service.record_production_event("program.take", "camera:2", "requested", request_id="take-1", details={"generation": 1, "duration_ms": 500}) == requested
    service.record_production_event("program.rendered", "camera:2", "confirmed", actor_kind="program_renderer", request_id="renderer-1", details={"generation": 1})
    events = service.history()["events"]
    assert len(events) == 2 and events[0]["outcome"] == "confirmed" and events[1]["outcome"] == "requested"
    assert events[0]["actor_kind"] == "program_renderer" and not events[0]["identity_verified"]
    assert service.snapshot()["revision"] == 0
    with pytest.raises(GreenroomError):
        service.record_production_event("arbitrary", "camera:2", "requested")
    with pytest.raises(GreenroomError):
        service.record_production_event("program.take", "camera:2", "requested", details={"name": "private"})
    with pytest.raises(GreenroomError):
        service.record_production_event("program.take", "camera:2", "requested", actor_kind="guest_session")


@pytest.mark.parametrize("origin", ["producer_control", "host_voice", "host_gesture"])
def test_production_automation_origins_are_audited_but_cannot_create_invites(room, origin):
    service, _ = room
    service.record_production_event("program.take", "camera:2", "requested", actor_kind=origin)
    event = service.history()["events"][0]
    assert event["actor_kind"] == origin and not event["identity_verified"]
    with pytest.raises(GreenroomError):
        service.create_invite(actor_kind=origin)


def test_composition_audit_source_list_is_bounded_and_excludes_free_text(room):
    service, _ = room
    sources = ["camera:1", "guest:" + "a" * 32 + ":screen"]
    service.record_production_event("program.preview", "preview", "requested", details={"source_ids": sources})
    assert service.history()["events"][0]["details"] == {"source_ids": sources}
    for invalid in (["camera:1"] * 7, [None], ["private display name"], ["x" * 101], "camera:1", {"camera:1": True}):
        with pytest.raises(GreenroomError) as error:
            service.record_production_event("program.preview", "preview", "requested", details={"source_ids": invalid})
        code(error, "invalid_production_details")


@pytest.mark.parametrize("token", [None, "", "short", "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_bad_capability_tokens_fail_closed(room, token):
    service, _ = room
    with pytest.raises(GreenroomError):
        service.authenticate(token)
    with pytest.raises(GreenroomError):
        service.join(token, "Fixture", "b" * 64)
