from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")


def test_held_profile_restores_in_control_panel_while_off_air():
    assert 'if isinstance(held, dict) and held.get("pokemon")' in SERVER
    assert '"on_air": bool(overlay.get("pokedex_on_air"))' in SERVER
    assert '"held": True' in SERVER


def test_verified_profile_is_persisted_after_resolution():
    assert 'orchestrator.overlay_state.update({"pokedex_current": response})' in SERVER


def test_visible_unresolved_card_never_falls_back_to_previous_species():
    pending_guard = 'if bool(current.get("card_present") or current.get("recognition_locked")):'
    held_lookup = 'held = overlay.get("pokedex_current")'
    assert pending_guard in SERVER
    assert SERVER.index(pending_guard) < SERVER.index(held_lookup)
    assert '"reason": "current_species_pending"' in SERVER


def test_multi_card_selection_refreshes_held_profile_immediately():
    assert 'rare_intelligence = await current_pokedex_entry()' in SERVER
    assert '"rare_intelligence": rare_intelligence' in SERVER


def test_explicit_verified_slot_precedes_current_single_card_species_profile():
    assert 'selected_verified_slot = next(' in SERVER
    assert 'candidate = selected_verified_slot.get("card") if selected_verified_slot else None' in SERVER
    assert 'current_name = orchestrator.pokedex.pokemon_name(current_candidate)' in SERVER
    assert '"provisional": not profile_verified' in SERVER
    assert '"verified": profile_verified' in SERVER
