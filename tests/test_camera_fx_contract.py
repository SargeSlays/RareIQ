from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_camera_fx_is_a_dedicated_production_app():
    assert 'data-target="camera-fx"' in CONTROL
    assert 'aria-label="Camera Effects"' in CONTROL
    assert 'data-workspace="camera-fx"' in CONTROL
    assert 'id="cameraFxApply"' in CONTROL
    assert 'id="cameraFxReset"' in CONTROL
    assert 'id="cameraFxCanvas"' in CONTROL


def test_camera_fx_has_popular_presets_and_manual_controls():
    for preset in ("clean", "vibrant", "cinematic", "warm", "cool", "noir", "vintage"):
        assert f'data-camera-fx-preset="{preset}"' in CONTROL
    for control_id in ("cameraFxBrightness", "cameraFxContrast", "cameraFxSaturation", "cameraFxBlur"):
        assert f'id="{control_id}"' in CONTROL
    assert "CAMERA_FX_PRESETS" in STUDIO
    assert "brightness(${values.brightness}%)" in STUDIO


def test_green_screen_is_processed_on_a_separate_output_layer():
    assert 'id="cameraFxChroma" type="checkbox"' in CONTROL
    assert 'id="cameraFxKeyColor" type="color"' in CONTROL
    assert 'id="cameraFxTolerance"' in CONTROL
    assert 'id="cameraFxSoftness"' in CONTROL
    assert 'context.getImageData(0,0,width,height)' in STUDIO
    assert 'context.putImageData(frame,0,0)' in STUDIO
    assert 'feed=$("cameraFeed"),canvas=$("cameraFxCanvas")' in STUDIO
    assert "Recognition and Program / OBS remain on the clean source." in CONTROL


def test_camera_fx_preferences_and_responsive_theme_are_complete():
    assert 'CAMERA_FX_PREFERENCES_KEY="rareiq.cameraFx.preferences.v1"' in STUDIO
    assert "function restoreCameraFxPreferences" in STUDIO
    assert "function resetCameraFx" in STUDIO
    assert "/* Camera FX: audience styling stays isolated from the raw recognition frame. */" in CSS
    assert "html[data-theme=light] body.studiox-ui4 .camera-fx-shell" in CSS
    assert "@media(max-width:620px)" in CSS


def test_camera_fx_truthfully_limits_effects_to_studio_preview():
    assert "Studio X preview only" in CONTROL
    assert "Recognition and Program / OBS remain on the clean source." in CONTROL
    assert "without changing recognition or broadcast output" in CONTROL
    assert "Program styling is active" not in STUDIO
    assert 'notify(cameraFxState.enabled?"Studio Preview Styled":"Studio Preview Bypassed"' in STUDIO


def test_camera_fx_has_momentary_mouse_and_keyboard_clean_comparison():
    assert 'id="cameraFxCompare" type="button" aria-pressed="false"' in CONTROL
    assert "function setCameraFxCompare(active)" in STUDIO
    assert 'preview.dataset.compareClean==="true"?"none":filter' in STUDIO
    for event_name in ("pointerdown", "pointerup", "pointercancel", "pointerleave"):
        assert f'["{event_name}",' in STUDIO
    assert 'event.key===" "||event.key==="Enter"' in STUDIO
    assert '.camera-fx-preview img[data-compare-clean="true"]' in CSS


def test_camera_fx_preview_copy_does_not_claim_program_or_obs_delivery():
    assert "Apply to Studio Preview" in CONTROL
    assert '"Bypass Studio Preview":"Apply to Studio Preview"' in STUDIO
    assert "Preview-only chroma key" in CONTROL
    assert '"Green screen preview active"' in STUDIO
