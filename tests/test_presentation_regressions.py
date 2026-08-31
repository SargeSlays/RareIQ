"""Structural guards for the regressions found during the readiness audit."""
from pathlib import Path
import re


STATIC = Path(__file__).resolve().parents[1] / "rareiq/web/static"


def test_every_command_deck_color_token_has_a_definition():
    styles = "\n".join(path.read_text(encoding="utf-8-sig") for path in STATIC.glob("*.css"))
    declared = set(re.findall(r"(--sx-[\w-]+)\s*:", styles))
    used = set(re.findall(r"var\((--sx-[\w-]+)", styles))
    assert used <= declared, f"Undefined presentation tokens: {used - declared}"


def test_custom_inspector_width_only_owns_the_live_workspace():
    css = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")
    owner = re.search(r'([^{}]+)\{\s*grid-template-columns: var\(--command-deck-rail\) minmax\(0, 1fr\) var\(--sx-custom-inspector-width, var\(--command-deck-inspector\)\)', css)
    assert owner and '[data-ui4-workspace="live"]' in owner[1]
    assert "container: studio-content / inline-size" in css
    assert "@container studio-content (max-width: 760px)" in css


def test_overlay_surfaces_share_the_brand_and_preserve_full_card_artwork():
    for filename in ("overlay_multicard.css", "overlay_v3.css"):
        css = (STATIC / filename).read_text(encoding="utf-8")
        assert "overlay_theme.css" in css
        assert "object-fit: contain" in css
        assert "object-fit: cover" not in css
    for filename in ("overlay_graphics.html", "overlay_production_screen.html", "overlay_replay.html"):
        assert "overlay_theme.css" in (STATIC / filename).read_text(encoding="utf-8")


def test_broadcast_tabs_budget_for_button_height_and_padding():
    css = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")
    block = re.search(r'\.workspace\[data-workspace="broadcast"\] \.broadcast-workspace-tabs \{([^}]+)', css)[1]
    assert "min-height: 54px" in block  # 38px button + 14px padding + 2px border
    assert "height: auto" in block and "overflow-y: hidden" in block


def test_primary_action_text_has_accessible_contrast_in_both_themes():
    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))

    css = (STATIC / "studiox_command_deck.css").read_text(encoding="utf-8")
    for theme in ("dark", "light"):
        block = re.search(r'html\[data-theme="' + theme + r'"\] body\.studiox-command-deck\[data-studiox-visual-system="unified"\]\s*\{([^}]+)', css)[1]
        accent = re.search(r"--sx-accent:\s*(#[\da-f]+)", block)[1]
        text = re.search(r"--sx-on-accent:\s*(#[\da-f]+)", block)[1]
        bright, dark = sorted((luminance(accent), luminance(text)), reverse=True)
        assert (bright + .05) / (dark + .05) >= 4.5
