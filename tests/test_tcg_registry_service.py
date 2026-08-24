from pathlib import Path

import pytest

from rareiq.services.tcg_registry_service import TCGDefinition, TCGRegistryService


def test_registry_supports_alias_resolution_and_capability_metadata() -> None:
    registry = TCGRegistryService((
        TCGDefinition(
            game_id="pokemon",
            name="Pokémon Trading Card Game",
            aliases=("PTCG",),
            providers=("tcgdex",),
        ),
    ))

    assert registry.resolve("Pokémon").game_id == "pokemon"
    assert registry.resolve("ptcg").game_id == "pokemon"
    status = registry.status()
    assert status["automatic_detection"] is True
    assert status["manual_selection"] is True
    assert status["games"][0]["providers"] == ["tcgdex"]


def test_registry_rejects_empty_game_id() -> None:
    with pytest.raises(ValueError):
        TCGRegistryService((TCGDefinition(game_id="", name="Broken"),))


def test_manual_selection_persists_and_auto_remains_default(tmp_path: Path) -> None:
    config = tmp_path / "tcg_selection.json"
    games = (
        TCGDefinition(game_id="pokemon", name="Pokémon"),
        TCGDefinition(game_id="one-piece", name="One Piece", aliases=("opcg",)),
    )
    registry = TCGRegistryService(games, config_path=config)
    assert registry.selection() == {
        "mode": "auto",
        "game_id": None,
        "resolved_game_id": "pokemon",
    }

    registry.configure_selection("manual", "opcg")
    restored = TCGRegistryService(games, config_path=config)
    assert restored.selection() == {
        "mode": "manual",
        "game_id": "one-piece",
        "resolved_game_id": "one-piece",
    }

    assert restored.configure_selection("auto")["selection"]["mode"] == "auto"


def test_manual_selection_rejects_unregistered_games() -> None:
    registry = TCGRegistryService((TCGDefinition(game_id="pokemon", name="Pokémon"),))
    with pytest.raises(ValueError):
        registry.configure_selection("manual", "one-piece")


def test_server_exposes_tcg_registry_endpoint() -> None:
    root = Path(__file__).resolve().parents[1]
    server = (root / "rareiq/web/server.py").read_text(encoding="utf-8")
    orchestrator = (root / "rareiq/core/orchestrator.py").read_text(encoding="utf-8")
    assert '@app.get("/api/tcg/games")' in server
    assert '@app.post("/api/tcg/selection")' in server
    assert "orchestrator.tcg_registry.status()" in server
    assert 'game_id="pokemon"' in orchestrator
    assert '"localized_sets"' in orchestrator


def test_recognition_and_set_routes_are_scoped_to_resolved_game() -> None:
    root = Path(__file__).resolve().parents[1]
    server = (root / "rareiq/web/server.py").read_text(encoding="utf-8")
    assert '"tcg": orchestrator.tcg_registry.selection()' in server
    assert 'game_id = selection.get("resolved_game_id")' in server
    assert 'if game_id == "pokemon":' in server
    assert 'if game_id != "pokemon":' in server
    assert '"game_id": game_id' in server
    assert "set_active_filter(None, None, None)" in server
