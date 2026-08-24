from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_live_toolbar_exposes_compact_automatic_or_manual_game_selection() -> None:
    assert 'id="tcgGameSelect"' in HTML
    assert 'aria-label="Trading card game"' in HTML
    assert "Game / Set" in HTML
    assert 'api("/api/tcg/games")' in JS
    assert 'api("/api/tcg/selection"' in JS
    assert 'gameId==="auto"?"auto":"manual"' in JS
    assert "document.body.dataset.tcgGame" in JS


def test_game_selection_refreshes_available_sets() -> None:
    updater = JS.split("async function updateTCGSelection", 1)[1].split(
        "function readPackSession", 1
    )[0]
    assert "await loadTCGGames()" in updater
    assert "await loadRecognitionSets()" in updater
