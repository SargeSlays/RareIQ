from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_pack_tracker_groups_reveal_history_without_fake_values():
    assert '@app.get("/api/production/session/pack-tracker")' in SERVER
    assert 'pack_number' in SERVER
    assert 'hit_rate' in SERVER
    assert 'verified_value' in SERVER
    assert 'unvalued_cards' in SERVER
    assert 'strongest_pull' in SERVER
    assert 'best_pack' in SERVER


def test_pack_tracker_ui_and_finale_graphic_exist():
    for token in ('class="pack-tracker"', 'id="packTrackerPosition"', 'id="packTrackerHits"', 'id="packTrackerHitRate"', 'id="packTrackerValue"', 'id="packTrackerCoverage"', 'id="packTrackerStrongest"', 'id="packTrackerComparison"', 'id="packTrackerRecap"'):
        assert token in CONTROL
    assert 'function renderPackTracker' in JS
    assert 'async function loadPackTracker' in JS
    assert 'async function takePackFinaleGraphic' in JS
    assert 'Market value unavailable' in JS
    assert '.pack-tracker-current' in CSS
    assert '.pack-comparison' in CSS
