from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_decision_header_contains_accessible_removal_progress():
    for element_id in ("cardRemovalProgress", "cardRemovalProgressLabel", "cardRemovalProgressBar"):
        assert f'id="{element_id}"' in HTML
    assert 'role="progressbar"' in HTML
    assert 'aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"' in HTML


def test_progress_uses_both_poll_and_elapsed_time_safety_gates():
    assert "function renderCardRemovalProgress" in JS
    assert "const pollProgress=cardRemovalMissingPolls/preset.polls" in JS
    assert "const timeProgress=(now-cardRemovalMissingSince)/preset.ms" in JS
    assert "Math.min(1,pollProgress,timeProgress)" in JS
    assert 'setAttribute("aria-valuenow",String(value))' in JS


def test_progress_resets_when_card_reappears_and_completes_after_clear():
    assert '"Card still visible · waiting for removal"' in JS
    assert 'renderCardRemovalProgress(100,`Removal confirmed${timing} · ready for next`,true)' in JS
    assert 'renderCardRemovalProgress(0,"Waiting for removal",false)' in JS


def test_progress_is_responsive_themed_and_reduced_motion_safe():
    progress_css = CSS[CSS.index("Physical removal confirmation progress") :]
    assert ".card-removal-progress[hidden]" in progress_css
    assert "html[data-theme=light]" in progress_css
    assert "@media(max-width:520px)" in progress_css
    assert "@media(prefers-reduced-motion:reduce)" in progress_css
