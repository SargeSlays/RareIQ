from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def test_mobile_destination_cards_collapse_to_one_readable_column() -> None:
    assert "@media(max-width:620px)" in CSS
    assert ".broadcast-destination-grid{grid-template-columns:1fr}" in CSS
    assert ".broadcast-destinations>header{align-items:flex-start!important;flex-direction:column}" in CSS


def test_destination_unavailable_state_replaces_the_loading_copy() -> None:
    section = JS[
        JS.index("function renderBroadcastDestinationsUnavailable") :
        JS.index("async function saveObsSettings")
    ]
    assert 'grid.replaceChildren(unavailable)' in section
    assert 'Destination status unavailable' in section
    assert 'No platform connection or live state is being assumed.' in section
    assert HTML.count('id="broadcastDestinationGrid"') == 1


def test_destination_refresh_remains_explicit_and_read_only() -> None:
    section = JS[JS.index("function broadcastDestinationCard") : JS.index("async function saveObsSettings")]
    assert 'api("/api/production/destinations")' in section
    assert 'method:"POST"' not in section
    assert "setInterval" not in section
    assert HTML.count('id="broadcastDestinationsRefresh"') == 1


def test_mobile_setup_guides_use_native_accessible_disclosure_without_extra_polling() -> None:
    section = JS[JS.index("function broadcastDestinationCard") : JS.index("async function saveObsSettings")]
    assert 'document.createElement("details")' in section
    assert 'document.createElement("summary")' in section
    assert "setInterval" not in section
    assert "destination.setup?.requirements" in section
