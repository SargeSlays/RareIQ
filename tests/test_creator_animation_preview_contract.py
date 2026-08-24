from pathlib import Path


STATIC = Path("rareiq/web/static")


def test_creator_has_safe_animation_preview_controls():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    script = (STATIC / "studiox.js").read_text(encoding="utf-8")

    for tier in ("low", "medium", "grail"):
        assert f'data-animation-preview="{tier}"' in html
    assert "function previewCreatorAnimation(tier)" in script
    assert 'url.searchParams.set("preview",tier)' in script
    assert 'document.querySelectorAll("[data-animation-preview]")' in script
    preview_function = script.split("function previewCreatorAnimation(tier)", 1)[1].split("async function saveRevealSequence", 1)[0]
    assert 'method:"POST"' not in preview_function


def test_overlay_preview_does_not_poll_and_live_reveal_uses_reference_artwork():
    overlay = (STATIC / "overlay_reveal_sequence.html").read_text(encoding="utf-8")

    assert 'id="revealCardArt"' in overlay
    assert 's.current_card?.reference_image_url' in overlay
    assert 'new URLSearchParams(location.search)' in overlay
    assert '["low","medium","grail"].includes(previewTier)' in overlay
    assert "if([\"low\",\"medium\",\"grail\"].includes(previewTier)){render(previewState(previewTier))}else{tick();setInterval(tick,350)}" in overlay


def test_animation_preview_styles_are_scoped_to_studio_ui():
    css = (STATIC / "studiox_update15.css").read_text(encoding="utf-8")
    assert "body.studiox-ui4 .creator-animation-previews" in css
