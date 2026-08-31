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


def test_overlay_reset_hides_every_live_surface_and_advances_generations(tmp_path):
    state_path = tmp_path / "overlay.json"
    service = OverlayStateService(state_path=state_path)
    service.update({
        "pokedex_on_air": True,
        "broadcast_graphic": {"visible": True, "preview": True, "title": "Previous card", "generation": 8},
        "production_screen": {"visible": True, "title": "Starting soon", "generation": 12},
    })
    reset = service.reset()
    restored = OverlayStateService(state_path=state_path).get()
    for state in (reset, restored):
        assert state["pokedex_on_air"] is False
        assert state["broadcast_graphic"]["visible"] is False
        assert state["broadcast_graphic"]["preview"] is False
        assert state["broadcast_graphic"]["generation"] > 8
        assert state["production_screen"]["visible"] is False
        assert state["production_screen"]["generation"] > 12


def test_overlay_nested_state_is_not_mutable_outside_the_service(tmp_path):
    service = OverlayStateService(state_path=tmp_path / "overlay.json")
    payload = {"pokedex_current": {"pokemon": {"name": "Nickit"}}}
    result = service.update(payload)
    payload["pokedex_current"]["pokemon"]["name"] = "Mutated input"
    result["pokedex_current"]["pokemon"]["name"] = "Mutated output"
    snapshot = service.get()
    assert snapshot["pokedex_current"]["pokemon"]["name"] == "Nickit"
    snapshot["pokedex_current"]["pokemon"]["name"] = "Mutated snapshot"
    assert service.get()["pokedex_current"]["pokemon"]["name"] == "Nickit"


def test_overlay_theme_survives_restart_and_reset(tmp_path):
    state_path = tmp_path / "overlay.json"
    service = OverlayStateService(state_path=state_path)
    theme = {"accent_color": "#abcdef", "alignment": "right", "scale": 80}
    service.update({"rare_intelligence_theme": theme})
    assert OverlayStateService(state_path=state_path).get()["rare_intelligence_theme"] == theme
    service.reset()
    assert OverlayStateService(state_path=state_path).get()["rare_intelligence_theme"] == theme


def test_corrupt_on_air_setting_cannot_go_live_by_truthiness(tmp_path):
    state_path = tmp_path / "overlay.json"
    state_path.write_text('{"pokedex_on_air":"false"}', encoding="utf-8")
    assert OverlayStateService(state_path=state_path).get()["pokedex_on_air"] is False
