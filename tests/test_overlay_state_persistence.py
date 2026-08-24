from rareiq.services.overlay_state_service import OverlayStateService


def test_rare_intelligence_presentation_survives_restart(tmp_path):
    state_path = tmp_path / "overlay-presentation.json"
    service = OverlayStateService(state_path=state_path)
    service.update({
        "pokedex_on_air": True,
        "pokedex_current": {"pokemon": {"name": "Crocalor"}},
        "status": "transient-value",
    })

    restored = OverlayStateService(state_path=state_path)

    assert restored.get()["pokedex_on_air"] is True
    assert restored.get()["pokedex_current"]["pokemon"]["name"] == "Crocalor"
    assert restored.get()["status"] == "ready"


def test_overlay_reset_persists_hidden_state(tmp_path):
    state_path = tmp_path / "overlay-presentation.json"
    service = OverlayStateService(state_path=state_path)
    service.update({"pokedex_on_air": True})
    service.reset()

    restored = OverlayStateService(state_path=state_path)

    assert restored.get()["pokedex_on_air"] is False
    assert restored.get()["pokedex_current"] is None
