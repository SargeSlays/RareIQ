from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_library_sync_errors_are_operator_facing_and_url_free() -> None:
    assert "function librarySyncErrorSummary" in JS
    assert "Reference provider is temporarily unavailable." in JS
    assert "Reference provider rate limit reached" in JS
    assert "Reference provider authorization failed" in JS
    assert 'replace(/https?:\\/\\/\\S+/gi,"")' in JS
    assert "Last error: ${state.last_error}" not in JS


def test_library_sync_preserves_resume_guidance_after_failure() -> None:
    assert '"Progress saved · sync paused by provider"' in JS
    assert "Resume Sync will continue from the last completed set." in JS
    assert "librarySyncErrorSummary(state.last_error)" in JS


def test_collection_light_theme_covers_nested_operational_surfaces() -> None:
    assert 'html[data-theme="light"] body.studiox-ui4 .workspace[data-workspace="collection"]' in CSS
    for selector in (
        ".library-sync-stats>div",
        ".collection-trend-layout>div",
        "#collectionActivity>div",
        ".inventory-listing-metrics>article",
        ".inventory-pack-ledgers article",
        ".approved-inventory-intake",
        ".collection-duplicate-grid article",
    ):
        assert selector in CSS


def test_collection_light_theme_keeps_form_controls_and_tables_readable() -> None:
    assert 'input:not([type="checkbox"]):not([type="radio"]),select,textarea' in CSS
    assert '.collection-table :is(th,td){color:#294651}' in CSS
