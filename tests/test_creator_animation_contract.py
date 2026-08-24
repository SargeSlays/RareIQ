from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
OVERLAY=Path("rareiq/web/static/overlay_reveal_sequence.html").read_text(encoding="utf-8")

def test_creator_exposes_animation_safety_and_intensity_controls():
    for field in ("creatorAnimationsEnabled","creatorParticlesEnabled","creatorFlashEnabled","creatorMinimumAnimationTier","creatorAnimationIntensity","creatorAnimationDuration"):
        assert f'id="{field}"' in CONTROL
    assert "animations_enabled:" in STUDIO and "minimum_animation_tier:" in STUDIO

def test_overlay_has_distinct_rare_medium_and_grail_presets():
    for preset in ("preset-low","preset-medium","preset-grail"):
        assert preset in OVERLAY
    for effect in ("shimmer","shockwave","particles","grailBackdrop"):
        assert effect in OVERLAY
    assert "prefers-reduced-motion:reduce" in OVERLAY
