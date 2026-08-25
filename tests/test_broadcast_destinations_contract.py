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
    assert 'async function loadBroadcastDestinations(){try{const payload=await api("/api/production/destinations")' in JS
    section = JS[
        JS.index("function broadcastDestinationCard") :
        JS.index("async function saveObsSettings")
    ]
    assert "setInterval" not in section
    assert "method:\"POST\"" not in section
    assert "destination.connected=" not in section
    assert "routing.platform_live_verified" in section


def test_destination_failure_renders_a_truthful_durable_state() -> None:
    section = JS[
        JS.index("function renderBroadcastDestinationsUnavailable") :
        JS.index("async function saveObsSettings")
    ]
    assert 'status.dataset.state="unavailable"' in section
    assert 'Destination connectors unavailable' in section
    assert 'No platform connection or live state is being assumed.' in section
    assert 'renderBroadcastDestinationsUnavailable(error);throw error' in section
    assert ".broadcast-destination-unavailable" in CSS


def test_destination_console_is_truthful_and_responsive() -> None:
    assert "Review setup requirements and verified connector state" in HTML
    assert "never displays or accepts credentials, stream keys, or account authorization" in HTML
    assert ".broadcast-destination-grid{display:grid" in CSS
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in CSS
    assert "@media(max-width:620px)" in CSS
    assert ".broadcast-destination-card" in CSS


def test_destination_cards_expose_read_only_setup_guidance_and_explicit_checks() -> None:
    section = JS[
        JS.index("function broadcastDestinationCard") :
        JS.index("function renderBroadcastDestinations")
    ]
    assert 'guide.className="broadcast-destination-guide"' in section
    assert 'summary.textContent="View setup requirements"' in section
    assert "destination.setup?.requirements" in section
    assert "destination.setup?.verification_method" in section
    assert 'check.textContent="Check status"' in section
    assert "loadBroadcastDestinations()" in section
    assert 'method:"POST"' not in section
    assert ".broadcast-destination-readiness" in CSS
    assert ".broadcast-destination-guide>summary:focus-visible" in CSS


def test_destination_cards_render_verified_connector_states_without_mutation() -> None:
    section = JS[
        JS.index("function broadcastDestinationCard") :
        JS.index("function renderBroadcastDestinations")
    ]
    assert "destination.ready||destination.connected" in section
    assert "destination.connector_detail" in section
    assert '.broadcast-destination-card[data-state="ready"]' in CSS
    assert '.broadcast-destination-card[data-state="live"]' in CSS
    assert '.broadcast-destination-card[data-state="stale"]' in CSS
    assert '.broadcast-destination-card[data-state="connector_error"]' in CSS
    assert 'method:"POST"' not in section
