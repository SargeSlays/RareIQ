import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
CONTROL = (STATIC / "control.html").read_text(encoding="utf-8")
BRAND_CSS = (STATIC / "rareiq_brand_v1.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "brand" / "v1" / "rare-iq-tokens.css").read_text(encoding="utf-8")
MANIFEST = json.loads((STATIC / "rareiq.webmanifest").read_text(encoding="utf-8"))
BRAND_README = (STATIC / "brand" / "v1" / "README.md").read_text(encoding="utf-8")


OFFICIAL_ASSETS = {
    "rare-iq-primary-dark.svg": "F5F0E6",
    "rare-iq-primary-light.svg": "080B0D",
    "rare-iq-icon-dark.svg": "F5F0E6",
    "rare-iq-icon-light.svg": "080B0D",
}


def test_official_signal_cut_assets_are_local_and_transparent():
    logo_root = STATIC / "brand" / "v1" / "logos"
    for filename, foreground in OFFICIAL_ASSETS.items():
        asset = logo_root / filename
        text = asset.read_text(encoding="utf-8")
        assert asset.is_file()
        assert 'aria-label="Rare IQ"' in text
        assert f'fill="#{foreground}"' in text
        assert 'fill="#E6A62B"' in text
        assert '<rect width="100%" height="100%"' not in text
        assert 'filter=' not in text
        assert '<linearGradient' not in text
        assert len(hashlib.sha256(text.strip().encode()).hexdigest()) == 64


def test_official_developer_tokens_are_the_product_source_of_truth():
    expected = {
        "--riq-signal-mint": "#A6E8CE",
        "--riq-deep-mint": "#4B9F83",
        "--riq-discovery-amber": "#E6A62B",
        "--riq-obsidian": "#080B0D",
        "--riq-warm-ivory": "#F5F0E6",
        "--riq-slate": "#20282B",
        "--riq-mist": "#D7E2DD",
    }
    for token, value in expected.items():
        assert f"{token}: {value}" in TOKENS
        assert token in BRAND_CSS

    assert 'approved Rare IQ "Signal Cut" identity' in BRAND_README
    assert "Do not redraw them, animate them, add effects" in BRAND_README


def test_brand_and_command_deck_stylesheets_are_cache_busted_and_ordered():
    brand_link = '/static/rareiq_brand_v1.css?v=6.9.0-commanddeck96'
    deck_link = '/static/studiox_command_deck.css?v=6.9.0-commanddeck96'
    assert brand_link in CONTROL
    assert CONTROL.index(brand_link) > CONTROL.index("/static/pack_run_coach.css")
    assert CONTROL.index("brand/v1/rare-iq-tokens.css?v=1.0") < CONTROL.index(brand_link)
    assert CONTROL.index(brand_link) < CONTROL.index(deck_link)
    assert 'data-studiox-build="6.9.0-commanddeck96"' in CONTROL
    assert 'data-studiox-visual-system="unified"' in CONTROL


def test_current_control_does_not_load_superseded_presentation_layers():
    for filename in (
        "studiox_brand.css",
        "studiox_polish.css",
        "studiox_clarity.css",
        "studiox_motion.css",
        "studiox_adaptive.css",
        "studiox_30.css",
        "studiox_40.css",
        "studiox_401.css",
        "studiox_402.css",
        "studiox_50.css",
        "studiox_602.css",
        "studiox_603.css",
        "studiox_61.css",
        "studiox_62.css",
    ):
        assert f'/static/{filename}' not in CONTROL

    assert "commandDeckSplashOut" in (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")


def test_horizontal_lockup_is_default_and_old_neon_assets_are_not_rendered():
    assert CONTROL.count("brand/v1/logos/rare-iq-primary-dark.svg") >= 2
    assert 'class="brand-lockup-image"' in CONTROL
    assert "Intelligence for every collectible." not in CONTROL or "Project Iron Vision" not in CONTROL
    assert "Project Iron Vision" not in CONTROL
    assert "/static/brand/rareiq_full_transparent.png" not in CONTROL
    assert "/static/brand/rareiq_icon_transparent.png" not in CONTROL
    assert "filter: none !important" in BRAND_CSS
    assert "animation: none !important" in BRAND_CSS


def test_dark_and_light_themes_have_official_surface_and_logo_variants():
    assert 'html[data-theme="dark"] body.studiox-ui4 .brand-lockup-image' in BRAND_CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .brand-lockup-image' in BRAND_CSS
    assert "rare-iq-primary-dark.svg" in BRAND_CSS
    assert "rare-iq-primary-light.svg" in BRAND_CSS
    assert 'html[data-theme="light"] body.studiox-ui4' in BRAND_CSS
    assert 'background: var(--riq-warm-ivory) !important' in BRAND_CSS
    assert 'background: var(--riq-obsidian) !important' in BRAND_CSS
    assert 'id="studioThemeColor"' in CONTROL


def test_brand_layer_contains_no_legacy_cyan_purple_identity():
    lowered = BRAND_CSS.lower()
    for forbidden in ("#20d8ff", "#347bff", "#7b4dff", "#d93dff", "linear-gradient", "radial-gradient"):
        assert forbidden not in lowered


def test_manifest_uses_official_signal_cut_identity():
    assert MANIFEST["name"] == "Rare IQ Studio X"
    assert MANIFEST["short_name"] == "Rare IQ"
    assert MANIFEST["background_color"] == "#080B0D"
    assert MANIFEST["theme_color"] == "#080B0D"
    assert MANIFEST["icons"] == [
        {
            "src": "/static/brand/v1/logos/rare-iq-icon-dark.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any",
        }
    ]
