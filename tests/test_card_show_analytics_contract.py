from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_card_analytics_api_uses_reveal_collection_and_inventory_data():
    assert '@app.get("/api/production/session/card-analytics")' in SERVER
    assert 'reveal_sequence.snapshot()' in SERVER
    assert 'inventory.dashboard()' in SERVER
    assert 'collection.dashboard(' in SERVER
    assert 'verified_value_total' in SERVER
    assert 'unvalued_cards' in SERVER
    assert 'top_pulls' in SERVER


def test_card_analytics_dashboard_and_top_pull_graphic_exist():
    for token in ('class="card-show-analytics"', 'id="cardAnalyticsRevealed"', 'id="cardAnalyticsPace"', 'id="cardAnalyticsValue"', 'id="cardAnalyticsCoverage"', 'id="cardAnalyticsTiers"', 'id="cardAnalyticsRarities"', 'id="cardAnalyticsTopPulls"', 'id="cardAnalyticsTopPullGraphic"'):
        assert token in CONTROL
    assert 'function renderCardShowAnalytics' in JS
    assert 'async function loadCardShowAnalytics' in JS
    assert 'async function takeTopPullGraphic' in JS
    assert 'Verified value $' in JS
    assert '.card-analytics-panels' in CSS
    assert '.top-pulls-panel' in CSS
