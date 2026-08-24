from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_best_known_profiles_are_scoped_by_game_language_and_set():
    scope = JS.split("function packTuningScope", 1)[1].split("function packTuningScopeLabel", 1)[0]
    assert "card.game" in scope
    assert "card.language" in scope
    assert "card.set_id" in scope
    assert "card.set_code" in scope
    assert "card.set_name" in scope
    assert "`${game}|${language}|${set}`" in scope


def test_profile_lookup_and_application_never_fall_back_across_sets():
    assert "function loadPackBestTuning(scope=packTuningScope())" in JS
    apply = JS.split("async function applyPackBestTuning", 1)[1].split("function renderPackTuningHistory", 1)[0]
    assert "loadPackBestTuning(scope)" in apply
    assert "profile.scope!==scope" in apply
    assert "loadPackBestTunings()[scope]||null" in JS


def test_history_filters_to_the_active_scope_and_build_is_current():
    render = JS.split("function renderPackTuningHistory", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert ".filter(row=>row.scope===scope)" in render
    assert "panel.dataset.scope=scope" in render
    assert "6.8.8-provisional-identity" in HTML
