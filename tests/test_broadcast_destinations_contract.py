from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8-sig")


def test_destinations_have_a_first_class_broadcast_view() -> None:
    assert HTML.count('data-broadcast-view="destinations"') == 1
    assert HTML.count('id="broadcastDestinations"') == 1
    assert HTML.count('id="broadcastDestinationGrid"') == 1
    assert HTML.count('id="broadcastDestinationsRefresh"') == 1
    assert 'destinations:[".broadcast-destinations"]' in JS


def test_destination_state_uses_one_read_only_status_endpoint() -> None:
    assert '@app.get("/api/production/destinations")' in SERVER
    assert 'async function loadBroadcastDestinations(){const payload=await api("/api/production/destinations")' in JS
    section = JS[
        JS.index("function broadcastDestinationCard") :
        JS.index("async function saveObsSettings")
    ]
    assert "setInterval" not in section
    assert "method:\"POST\"" not in section
    assert "destination.connected=" not in section
    assert "routing.platform_live_verified" in section


def test_destination_console_is_truthful_and_responsive() -> None:
    assert "RareIQ reports only platform-confirmed connection and live states" in HTML
    assert "Credentials, stream keys, and account authorization are not collected" in HTML
    assert ".broadcast-destination-grid{display:grid" in CSS
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in CSS
    assert "@media(max-width:620px)" in CSS
    assert ".broadcast-destination-card" in CSS
