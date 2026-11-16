from rareiq.services.production_trigger_guard import ProductionTriggerGuard


def fixture(labels=("open_palm",), **kwargs):
    time = [0.0]
    guard = ProductionTriggerGuard(labels, clock=lambda: time[0], **kwargs)
    return guard, time


def held(guard, time, label, duration=1):
    result = None
    for _ in range(round(duration / .1)):
        time[0] += .1
        result = guard.observe(label, .99)
        if result.get("state") == "accepted":
            return result
    return result


def test_no_detector_or_action_is_implied_and_manual_override_disarms():
    guard, time = fixture()
    assert not guard.observe("open_palm", .99)["ok"]
    guard.arm()
    result = held(guard, time, "open_palm", 1.2)
    assert result["state"] == "accepted" and result["practice"] and result["executed"] is False
    guard.manual_override()
    assert held(guard, time, "open_palm")["reason"] == "trigger_not_armed"


def test_dwell_rejects_drift_low_confidence_and_stale_samples():
    guard, time = fixture()
    guard.arm()
    held(guard, time, "open_palm", .4)
    assert not guard.observe("open_palm", .5)["ok"]
    assert held(guard, time, "open_palm", .4)["state"] == "candidate"
    time[0] += 5
    assert guard.observe("open_palm", .99)["state"] == "candidate"
    assert held(guard, time, "open_palm", .4)["state"] == "candidate"
    assert guard.observe("open_palm", .99, tracking=False)["reason"] == "tracking_lost"
    assert not guard.armed


def test_gesture_requires_neutral_release_and_cooldown_before_repeat():
    guard, time = fixture()
    guard.arm()
    assert held(guard, time, "open_palm", 1.2)["state"] == "accepted"
    assert held(guard, time, "open_palm", 4)["reason"] == "trigger_cooldown_or_release_required"
    assert guard.observe("neutral", .99)["state"] == "neutral"
    assert held(guard, time, "open_palm", 1.2)["state"] == "accepted"


def test_look_directions_require_external_calibration_and_do_not_repeat_same_target():
    guard, time = fixture(("look_camera_1", "look_camera_2"), neutral_required=False)
    assert guard.arm()["reason"] == "calibration_required"
    guard.arm(calibrated=True, practice=False)
    assert held(guard, time, "look_camera_1", 1.2)["state"] == "accepted"
    held(guard, time, "look_camera_1", 3)
    assert guard.observe("look_camera_1", .99)["reason"] == "trigger_cooldown_or_release_required"
    result = held(guard, time, "look_camera_2", 1.2)
    assert result["state"] == "accepted" and not result["practice"] and result["executed"] is False
