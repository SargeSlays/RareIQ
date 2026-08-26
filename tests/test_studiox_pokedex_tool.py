from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"


def test_studiox_exposes_pokedex_tool_and_broadcast_controls():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    script = (STATIC / "studiox.js").read_text(encoding="utf-8")

    assert html.count('data-studiox-widget="pokedex"') == 1
    assert 'data-widget-visibility="pokedex"' in html
    assert 'id="pokedexOnAir"' in html
    assert 'id="pokedexHeldNotice"' in html
    assert "Last verified profile" in html
    assert 'href="/overlay/rare-intelligence"' in html
    assert "Rare Intelligence" in html
    assert "Species data powered by PokéAPI" in html
    assert 'pokedex:renderPokedexWidget' in script
    assert 'api("/api/rare-intelligence/current")' in script
    assert "async function hydrateHeldRareIntelligence()" in script
    assert "setTimeout(hydrateHeldRareIntelligence,300);" in script
    assert "payload?.pokemon&&payload?.held===true" in script
    assert "studioXPokedexPayload?.held===true&&studioXPokedexPayload?.pokemon" in script
    assert 'api("/api/rare-intelligence/on-air"' in script
    assert "studioXPokedexBroadcastEligible=payload?.broadcast_eligible===true" in script
    assert "onAirControl.disabled=!onAir&&!studioXPokedexBroadcastEligible" in script
    assert "Species preview only · verify identity to enable ON AIR" in script
    assert "Rare Intelligence Not On Air" in script
    assert 'payload?.held===true' in script
    assert 'classList.toggle("is-held-profile",held)' in script
    assert "Held profile · 16:9 overlay hidden" in script


def test_pokedex_overlay_is_16_by_9_and_obeys_on_air_state():
    overlay = (STATIC / "overlay_pokedex.html").read_text(encoding="utf-8")
    server = (ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")

    assert "aspect-ratio:16/9" in overlay
    assert 'payload?.on_air===true' in overlay
    assert 'payload?.reveal?.hit_tier' in overlay
    assert "reveal-medium" in overlay
    assert "reveal-grail" in overlay
    assert 'fetch("/api/rare-intelligence/current"' in overlay
    assert '@app.get("/overlay/rare-intelligence")' in server
    assert '@app.get("/api/rare-intelligence/current")' in server
    assert '@app.post("/api/rare-intelligence/on-air")' in server
    assert 'overlay.get("pokedex_current")' in server
    assert '"held": True' in server
    assert 'isinstance(held, dict)' in server
    assert 'and held.get("pokemon")' in server
    assert 'held.get("provisional") is False' in server
    assert '(held.get("identity") or {}).get("verified") is True' in server
    assert "multi_card_recognition.status()" in server
    assert 'slot.get("verified") is True' in server


def test_reference_comparison_fit_preserves_complete_portrait_geometry():
    deck = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")
    assert "Reference comparison uses intrinsic portrait geometry at Fit" in deck
    compare = deck.split("Reference comparison uses intrinsic portrait geometry at Fit", 1)[1]
    assert "width: auto !important" in compare
    assert "height: auto !important" in compare
    assert "max-width: 100% !important" in compare
    assert "max-height: 100% !important" in compare
    assert "object-fit: contain !important" in compare
    assert "transform: scale(var(--compare-zoom, 1)) !important" in compare


def test_rare_intelligence_broadcast_controls_cannot_overflow_the_inspector():
    deck = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")

    responsive = deck.rsplit("@media (max-width: 1799px)", 1)[1]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important" in responsive
    assert "overflow-wrap: anywhere !important" in responsive
    assert ".studiox-pokedex-broadcast :is(a, button)" in responsive
    assert "width: 100% !important" in responsive
