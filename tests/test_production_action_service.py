import threading
import time
from concurrent.futures import ThreadPoolExecutor

from rareiq.services.production_action_service import ActionSpec, ProductionActions


def rig(execute, **options):
    actions = ProductionActions(**options)
    def validate(params):
        if set(params) != {"slot"} or type(params["slot"]) is not int or not 1 <= params["slot"] <= 4:
            raise ValueError("invalid_slot")
        return params
    actions.register(ActionSpec("program.take", validate, execute, "program.camera", .02))
    return actions


def test_concurrent_duplicate_completes_once_and_retains_original_outcome():
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def execute(params):
        calls.append(params); entered.set(); finish.wait(2)
        return {"ok": True, "program_slot": params["slot"]}
    actions = rig(execute)
    try:
        args = dict(origin="operator", request_id="same", expires_at=time.time() + 30)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(actions.dispatch, "program.take", {"slot": 2}, **args)
            assert entered.wait(1)
            duplicate = actions.dispatch("program.take", {"slot": 2}, **args)
            assert duplicate["state"] == "executing"
            assert first.result()["state"] == "executing"
        finish.set()
        time.sleep(.02)
        saved = actions.dispatch("program.take", {"slot": 2}, **args)
        assert saved["state"] == "succeeded"
        saved["result"]["program_slot"] = 99
        assert actions.dispatch("program.take", {"slot": 2}, **args)["result"]["program_slot"] == 2
        assert len(calls) == 1
        assert actions.dispatch("program.take", {"slot": 3}, **args)["reason"] == "request_id_conflict"
    finally:
        finish.set(); actions.close()


def test_untrusted_invalid_stale_unknown_and_practice_never_execute():
    calls = []
    actions = rig(lambda params: calls.append(params))
    try:
        assert actions.dispatch("program.take", {"slot": 1}, origin="chat")["reason"] == "untrusted_action_origin"
        assert actions.dispatch("shell.exec", {}, origin="operator")["reason"] == "unknown_action"
        assert actions.dispatch("program.take", {"slot": True}, origin="operator")["reason"] == "invalid_action_parameters"
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="old")["reason"] == "request_expiry_required"
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", expires_at=time.time()-1)["reason"] == "action_expired"
        result = actions.dispatch("program.take", {"slot": 1}, origin="operator", practice=True)
        assert result["state"] == "validated" and result["executed"] is False
        assert calls == []
    finally:
        actions.close()


def test_capacity_does_not_evict_recent_idempotency_keys_and_exceptions_are_private():
    def failed(_params):
        raise RuntimeError("sensitive host details")
    actions = rig(failed, retained=1)
    try:
        first = actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="one", expires_at=time.time()+30)
        assert first["state"] == "failed" and "sensitive" not in str(first)
        assert actions.dispatch("program.take", {"slot": 2}, origin="operator")["reason"] == "action_capacity_reached"
    finally:
        actions.close()


def test_retry_cannot_extend_expiry_then_escape_deduplication(monkeypatch):
    from rareiq.services import production_action_service as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    calls = []
    actions = rig(lambda params: (calls.append(params) or {"ok": True}))
    try:
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="A", expires_at=1010)["ok"]
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="A", expires_at=1100)["reason"] == "request_id_conflict"
        clock[0] = 1011
        assert actions.dispatch("program.take", {"slot": 2}, origin="operator", request_id="B", expires_at=1100)["ok"]
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="A", expires_at=1100)["reason"] == "request_id_conflict"
        assert actions.dispatch("program.take", {"slot": 1}, origin="operator", request_id="A", expires_at=1010)["reason"] == "action_expired"
        assert len(calls) == 2
    finally:
        actions.close()
