from rareiq.services.brand_settings_service import DEFAULT_BRAND, LEGACY_BRAND_COLORS, current_brand
from rareiq.services.overlay_state_service import current_intelligence_theme


def test_default_and_untouched_legacy_palettes_follow_current_brand():
    assert current_brand({}) == DEFAULT_BRAND
    old = {**LEGACY_BRAND_COLORS, "creator_name": "My shop"}
    migrated = current_brand(old)
    assert migrated["primary"] == "#8be8ca"
    assert migrated["creator_name"] == "My shop"
    assert old["primary"] == LEGACY_BRAND_COLORS["primary"]


def test_custom_overlay_colors_are_never_reset_by_a_brand_upgrade():
    custom = {**LEGACY_BRAND_COLORS, "primary": "#123456", "creator_name": "Custom"}
    assert current_brand(custom)["primary"] == "#123456"
    for key in LEGACY_BRAND_COLORS:
        assert current_brand(custom)[key] == custom[key]


def test_stock_intelligence_theme_migrates_without_resetting_layout():
    old = {"preset": "rareiq", "accent_color": "#a6e8ce", "secondary_color": "#4f9f83",
           "background_color": "#080d0a", "text_color": "#f5f2e9", "corner_radius": 12,
           "alignment": "right", "scale": 80, "show_art": False}
    current = current_intelligence_theme(old)
    assert current["background_color"] == "#18222e"
    assert current["corner_radius"] == 4
    assert current["alignment"] == "right" and current["scale"] == 80
    assert current["show_art"] is False
    assert old["corner_radius"] == 12
    custom = {**old, "accent_color": "#123456"}
    assert current_intelligence_theme(custom) == custom
    custom_preset = {**old, "preset": "minimal"}
    assert current_intelligence_theme(custom_preset) == custom_preset
