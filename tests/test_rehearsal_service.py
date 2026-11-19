"""Deterministic local authority tests; no encoder, platform, or recording."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from rareiq.services import rehearsal_service as module
from rareiq.services.rehearsal_service import RehearsalError, RehearsalService


def service(tmp_path, **kwargs):
    return RehearsalService(tmp_path / "rehearsal.json", idle_provider=lambda: {"ready": True}, **kwargs)


def run(value):
    return asyncio.run(value)


def test_entry_latches_before_async_observation_and_survives_interrupted_restart(tmp_path):
    async def scenario():
        observed, finish = asyncio.Event(), asyncio.Event()
        async def idle():
            assert not room.publishing_allowed()
            assert room.snapshot()["mode"] == "entering"
            observed.set()
            await finish.wait()
            return {"ready": True}
        room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=idle)
        task = asyncio.create_task(room.enter("enter-1", 0))
        await observed.wait()
        restored = service(tmp_path)
        assert restored.snapshot()["mode"] == "recovery_required"
        assert restored.snapshot()["reason"] == "rehearsal_interrupted"
        assert not restored.publishing_allowed()
        with pytest.raises(RehearsalError, match="rehearsal_publishing_blocked"):
            with room.publishing_lease():
                pytest.fail("lease must not run")
        finish.set()
        result = await task
        assert result["mode"] == "rehearsal" and not result["publishing_allowed"]
        assert service(tmp_path).snapshot()["mode"] == "rehearsal"
    run(scenario())


def test_checklist_cas_generation_exact_retry_and_metadata_only_history(tmp_path):
    room = service(tmp_path)
    entered = run(room.enter("enter-1", 0))
    assert run(room.enter("enter-1", 0)) == entered
    marked = run(room.mark("audio_vod", "passed", "mark-1", entered["revision"], entered["generation"]))
    assert run(room.mark("audio_vod", "passed", "mark-1", entered["revision"], entered["generation"])) == marked
    with pytest.raises(RehearsalError, match="rehearsal_request_conflict"):
        run(room.mark("audio_vod", "needs_attention", "mark-1", entered["revision"], entered["generation"]))
    with pytest.raises(RehearsalError, match="rehearsal_revision_conflict"):
        run(room.mark("video", "passed", "mark-2", entered["revision"], entered["generation"]))
    with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
        run(room.exit("exit-stale", marked["revision"], "a" * 32))
    restored = service(tmp_path)
    assert restored.snapshot() == marked
    exited = run(restored.exit("exit-1", marked["revision"], marked["generation"]))
    assert exited["mode"] == "production" and restored.publishing_allowed()
    assert run(restored.exit("exit-1", marked["revision"], marked["generation"])) == exited
    next_room = run(restored.enter("enter-2", exited["revision"]))
    assert next_room["generation"] != entered["generation"]
    assert all(item["status"] == "not_tested" for item in next_room["checks"])
    document = json.loads(restored.path.read_text())
    assert all(item["actor_kind"] == "local_operator" and item["attribution"] == "unverified" for item in document["history"])
    assert all(set(item) == {"action", "outcome", "revision", "at", "actor_kind", "attribution"} for item in document["history"])
    assert not {"history", "receipts"} & set(next_room)


def test_observed_busy_rolls_back_without_stopping_or_losing_previous_checklist(tmp_path):
    room = service(tmp_path)
    entered = run(room.enter("enter-1", 0))
    marked = run(room.mark("video", "passed", "mark-1", entered["revision"], entered["generation"]))
    prior = run(room.exit("exit-1", marked["revision"], marked["generation"]))
    room._idle_provider = lambda: {"ready": False, "reason": "private detail must not appear"}
    with pytest.raises(RehearsalError, match="^rehearsal_production_busy$"):
        run(room.enter("busy", prior["revision"]))
    result = room.snapshot()
    assert result["mode"] == "production" and result["publishing_allowed"]
    assert result["generation"] == prior["generation"] and result["checks"] == prior["checks"]
    assert "private detail" not in room.path.read_text()
    assert service(tmp_path).publishing_allowed()
    with pytest.raises(RehearsalError, match="rehearsal_production_busy"):
        run(room.enter("busy", prior["revision"]))


@pytest.mark.parametrize("result", [None, {"ready": 1}, {"ready": "true"}, {"ready": False}])
def test_exit_does_not_open_publication_without_positive_stopped_observation(tmp_path, result):
    room = service(tmp_path, exit_idle_provider=lambda: result)
    entered = run(room.enter("enter-1", 0))
    with pytest.raises(RehearsalError, match="rehearsal_encoding_active|rehearsal_idle_unavailable"):
        run(room.exit("exit-1", entered["revision"], entered["generation"]))
    assert room.snapshot()["mode"] == "rehearsal" and not room.publishing_allowed()
    assert not service(tmp_path).publishing_allowed()


@pytest.mark.parametrize("kind", ["exception", "invalid", "timeout"])
def test_unknown_entry_observation_remains_durably_blocked(tmp_path, kind):
    async def idle():
        if kind == "exception":
            raise OSError("private machine details")
        if kind == "timeout":
            await asyncio.sleep(1)
        return {"ready": 1}
    room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=idle)
    room.IDLE_TIMEOUT_SECONDS = 0.001
    with pytest.raises(RehearsalError, match="^rehearsal_idle_unavailable$"):
        run(room.enter("enter-1", 0))
    assert not room.publishing_allowed() and not service(tmp_path).publishing_allowed()
    assert "private" not in room.path.read_text()


def test_cancelled_entry_preserves_interrupted_latch_and_can_explicitly_exit(tmp_path):
    async def scenario():
        observed = asyncio.Event()
        async def idle():
            observed.set()
            await asyncio.Future()
        room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=idle)
        task = asyncio.create_task(room.enter("enter-1", 0))
        await observed.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert room.snapshot()["mode"] == "recovery_required"
        restored = service(tmp_path)
        snapshot = restored.snapshot()
        result = await restored.exit("explicit-exit", snapshot["revision"], snapshot["generation"])
        assert result["publishing_allowed"]
    run(scenario())


def test_inflight_production_lease_blocks_entry_and_always_releases(tmp_path):
    room = service(tmp_path)
    acquired, release = threading.Event(), threading.Event()
    def worker():
        with room.publishing_lease():
            acquired.set()
            assert release.wait(5)
            raise RuntimeError("synthetic failure")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert acquired.wait(5)
        try:
            assert room.publishing_allowed() and room.snapshot()["publishing_work_pending"]
            with pytest.raises(RehearsalError, match="rehearsal_production_busy"):
                run(room.enter("enter-1", 0))
            assert room.snapshot()["revision"] == 0 and not room.path.exists()
        finally:
            release.set()
        with pytest.raises(RuntimeError):
            future.result(timeout=5)
    assert not room.snapshot()["publishing_work_pending"]
    assert run(room.enter("enter-1", 0))["mode"] == "rehearsal"


def test_competing_entries_only_one_generation_and_one_observation(tmp_path):
    async def scenario():
        calls = []
        async def idle():
            calls.append(True)
            await asyncio.sleep(0)
            return {"ready": True}
        room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=idle)
        results = await asyncio.gather(room.enter("first", 0), room.enter("second", 0), return_exceptions=True)
        assert sum(isinstance(item, dict) for item in results) == 1
        assert len(calls) == 1 and not room.publishing_allowed()
    run(scenario())


@pytest.mark.parametrize("raw", [b"{broken", b'{"version":1,"version":1}', b"null", b"NaN", b"x" * (RehearsalService.MAX_BYTES + 1)],
                         ids=["malformed", "duplicate", "null", "nonfinite", "oversized"])
def test_invalid_existing_store_is_not_overwritten_and_explicit_recovery_preserves_bytes(tmp_path, raw):
    path = tmp_path / "rehearsal.json"
    path.write_bytes(raw)
    room = service(tmp_path)
    before = room.snapshot()
    assert before["mode"] == "recovery_required" and not room.publishing_allowed()
    with pytest.raises(RehearsalError, match="rehearsal_storage_invalid"):
        run(room.enter("enter-1", 0))
    assert path.read_bytes() == raw
    result = run(room.recover("recover-1", before["revision"], before["generation"]))
    assert result["publishing_allowed"] and result["generation"] != before["generation"]
    archives = list(tmp_path.glob(".rehearsal-state-corrupt-*.json"))
    assert len(archives) == 1 and archives[0].read_bytes() == raw
    assert not list(tmp_path.glob("*.recovering.json"))
    assert service(tmp_path).publishing_allowed()
    assert run(room.recover("recover-1", before["revision"], before["generation"])) == result


def test_recovery_requires_current_revision_generation_and_stopped_encoding(tmp_path):
    (tmp_path / "rehearsal.json").write_bytes(b"broken")
    room = service(tmp_path, exit_idle_provider=lambda: {"ready": False})
    before = room.snapshot()
    with pytest.raises(RehearsalError, match="rehearsal_revision_conflict"):
        run(room.recover("recover-1", 1, before["generation"]))
    with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
        run(room.recover("recover-1", 0, "a" * 32))
    with pytest.raises(RehearsalError, match="rehearsal_encoding_active"):
        run(room.recover("recover-1", 0, before["generation"]))
    assert room.path.read_bytes() == b"broken" and not list(tmp_path.glob(".rehearsal-state-corrupt-*"))


def test_corrupt_recovery_marker_is_also_preserved_without_an_unlatched_crash_gap(tmp_path, monkeypatch):
    path = tmp_path / "rehearsal.json"
    path.write_bytes(b"original broken state")
    marker = tmp_path / ".rehearsal.json.recovering.json"
    marker.write_bytes(b"original broken marker")
    room = service(tmp_path)
    state = room.snapshot()
    original_rename = module.os.rename
    def crash_after_marker_preservation(source, target):
        original_rename(source, target)
        if Path(source) == marker:
            raise OSError("synthetic interruption")
    monkeypatch.setattr(module.os, "rename", crash_after_marker_preservation)
    with pytest.raises(RehearsalError, match="rehearsal_storage_unavailable"):
        run(room.recover("recover-1", state["revision"], state["generation"]))
    archives = {item.read_bytes() for item in tmp_path.glob(".rehearsal-state-corrupt-*" )}
    assert archives == {b"original broken state", b"original broken marker"}
    restored = service(tmp_path)
    assert not restored.publishing_allowed() and restored.snapshot()["mode"] == "recovery_required"
    monkeypatch.setattr(module.os, "rename", original_rename)
    state = restored.snapshot()
    assert run(restored.recover("recover-2", state["revision"], state["generation"]))["publishing_allowed"]


def test_failed_preservation_or_replacement_leaves_durable_recovery_latch(tmp_path, monkeypatch):
    path = tmp_path / "rehearsal.json"
    path.write_bytes(b"broken evidence")
    room = service(tmp_path)
    before = room.snapshot()
    original_rename = module.os.rename
    def deny_preserve(source, target):
        if Path(source) == path:
            raise PermissionError("private fixture path")
        return original_rename(source, target)
    monkeypatch.setattr(module.os, "rename", deny_preserve)
    with pytest.raises(RehearsalError, match="rehearsal_storage_unavailable"):
        run(room.recover("recover-1", before["revision"], before["generation"]))
    assert path.read_bytes() == b"broken evidence" and not service(tmp_path).publishing_allowed()
    monkeypatch.setattr(module.os, "rename", original_rename)
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(PermissionError("private fixture")))
    before = room.snapshot()
    with pytest.raises(RehearsalError, match="rehearsal_storage_unavailable"):
        run(room.recover("recover-2", before["revision"], before["generation"]))
    assert not path.exists()  # Preserved file is intentionally not discarded.
    assert list(tmp_path.glob(".rehearsal-state-corrupt-*"))[0].read_bytes() == b"broken evidence"
    restored = service(tmp_path)
    assert not restored.publishing_allowed() and restored.snapshot()["reason"] == "rehearsal_recovery_interrupted"


def test_permission_failure_and_failed_busy_rollback_never_open_publication(tmp_path, monkeypatch):
    room = service(tmp_path)
    original_owner = module._owner_only
    monkeypatch.setattr(module, "_owner_only", lambda _: (_ for _ in ()).throw(PermissionError("fixture")))
    with pytest.raises(RehearsalError, match="rehearsal_storage_unavailable"):
        run(room.enter("enter-1", 0))
    assert not room.publishing_allowed()
    monkeypatch.setattr(module, "_owner_only", original_owner)
    room = RehearsalService(tmp_path / "busy.json", idle_provider=lambda: {"ready": False})
    original_replace, calls = module.os.replace, []
    def fail_rollback(source, target):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("fixture")
        return original_replace(source, target)
    monkeypatch.setattr(module.os, "replace", fail_rollback)
    with pytest.raises(RehearsalError, match="rehearsal_storage_unavailable"):
        run(room.enter("enter-1", 0))
    assert not room.publishing_allowed()
    assert not RehearsalService(room.path, idle_provider=lambda: {"ready": True}).publishing_allowed()


def test_tampering_deletion_bad_parent_and_symlink_do_not_default_to_production(tmp_path):
    room = service(tmp_path)
    entered = run(room.enter("enter-1", 0))
    run(room.exit("exit-1", entered["revision"], entered["generation"]))
    room.path.unlink()
    assert not room.publishing_allowed() and room.snapshot()["reason"] == "rehearsal_storage_changed"
    parent = tmp_path / "not-a-directory"
    parent.write_text("fixture")
    assert not RehearsalService(parent / "state.json", idle_provider=lambda: {"ready": True}).publishing_allowed()
    target, link = tmp_path / "foreign.json", tmp_path / "linked.json"
    target.write_bytes(b"foreign evidence")
    try:
        link.symlink_to(target)
    except OSError:
        return  # Windows installations may not grant symlink creation.
    linked = RehearsalService(link, idle_provider=lambda: {"ready": True})
    assert not linked.publishing_allowed()
    snapshot = linked.snapshot()
    assert run(linked.recover("recover-link", snapshot["revision"], snapshot["generation"]))["publishing_allowed"]
    assert target.read_bytes() == b"foreign evidence" and not link.is_symlink()


def test_history_and_receipts_remain_bounded(tmp_path):
    room = service(tmp_path)
    state = run(room.enter("enter-1", 0))
    for index in range(140):
        state = run(room.mark("video", "passed" if index % 2 else "not_tested", f"mark-{index}", state["revision"], state["generation"]))
    document = json.loads(room.path.read_text())
    assert len(document["receipts"]) == room.MAX_RECEIPTS
    assert len(document["history"]) == room.MAX_HISTORY
    assert room.path.stat().st_size < room.MAX_BYTES


def test_invalid_configured_path_keeps_status_available_but_cannot_publish_or_recover(tmp_path, monkeypatch):
    import rareiq.services.rehearsal_service as module
    source = tmp_path / "source"
    monkeypatch.setattr(module, "__file__", str(source / "rareiq/services/rehearsal_service.py"))
    for path in (Path("relative-state.json"), source / "runtime/config/rehearsal_state.json"):
        room = RehearsalService(path, idle_provider=lambda: {"ready": True})
        state = room.snapshot()
        assert state["mode"] == "recovery_required"
        assert state["reason"] == "rehearsal_storage_invalid"
        assert not room.publishing_allowed()
        with pytest.raises(RehearsalError, match="rehearsal_storage_invalid"):
            run(room.recover("invalid-path-recovery", state["revision"], state["generation"]))
        with pytest.raises(RehearsalError, match="rehearsal_storage_invalid"):
            run(room.enter("invalid-path-enter", state["revision"]))
    assert not source.exists()


def test_pending_exit_excludes_new_local_claims_and_restart_requires_explicit_recovery(tmp_path):
    async def scenario():
        observed, release = asyncio.Event(), asyncio.Event()
        async def idle():
            observed.set()
            await release.wait()
            return {"ready": True}
        room = service(tmp_path, exit_idle_provider=idle)
        state = await room.enter("lease-enter", 0)
        with room.local_encoding_lease(state["generation"]):
            pass
        leaving = asyncio.create_task(room.exit("lease-exit", state["revision"], state["generation"]))
        await observed.wait()
        try:
            with pytest.raises(RehearsalError, match="rehearsal_production_busy"):
                with room.local_encoding_lease(state["generation"]):
                    pytest.fail("New encoder reserved during exit")
            restored = service(tmp_path)
            assert restored.snapshot()["mode"] == "recovery_required"
            assert not restored.publishing_allowed()
            with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
                with restored.local_encoding_lease(state["generation"]):
                    pytest.fail("Interrupted exit accepted new encoder")
        finally:
            release.set()
            await leaving
        assert room.publishing_allowed()
        with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
            with room.local_encoding_lease(state["generation"]):
                pytest.fail("Production accepted local encoder")
    run(scenario())
