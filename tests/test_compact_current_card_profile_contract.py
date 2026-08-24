from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_profile_preserves_bound_duplicate_fields_but_marks_them_presentationally_hidden():
    assert 'id="cardMeta" aria-hidden="true"' in HTML
    assert 'id="identityVerdictBadge" aria-hidden="true"' in HTML
    assert 'id="cardStatus" aria-hidden="true"' in HTML
    profile_css = CSS[CSS.index("Compact current-card profile") :]
    assert ":is(#cardMeta,.identity-verdict-badge,.card-status){display:none!important}" in profile_css


def test_profile_uses_compact_artwork_and_fact_grid():
    profile_css = CSS[CSS.index("Compact current-card profile") :]
    assert "grid-template-columns:76px minmax(0,1fr)" in profile_css
    assert "width:76px" in profile_css
    assert "height:108px" in profile_css
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in profile_css
    for element_id in ("cardSetName", "cardCollectorNumber", "cardLanguage", "cardRarity", "cardVariant", "cardFinish"):
        assert f'id="{element_id}"' in HTML


def test_profile_is_responsive_and_light_theme_aware():
    profile_css = CSS[CSS.index("Compact current-card profile") :]
    assert "html[data-theme=light]" in profile_css
    assert "@media(max-width:520px)" in profile_css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in profile_css
