from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
LEGACY_CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def test_camera_fx_is_a_dedicated_production_app():
    assert 'data-target="camera-fx"' in CONTROL
    assert 'aria-label="Camera Effects"' in CONTROL
    assert 'data-workspace="camera-fx"' in CONTROL
    assert 'id="cameraFxApply"' in CONTROL
    assert 'id="cameraFxApply" type="button" aria-describedby="cameraFxOutputScope"' in CONTROL
    assert 'id="cameraFxReset"' in CONTROL
    assert 'id="cameraFxCanvas"' in CONTROL
    assert 'id="cameraFxState" data-state="off" role="status" aria-live="polite"' in CONTROL


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
    assert 'if($("cameraFxKeyColor"))$("cameraFxKeyColor").value="#00ff00"' in STUDIO
    assert "/* Camera FX */" in CSS
    assert 'body.studiox-command-deck[data-studiox-visual-system="unified"] .workspace[data-workspace="camera-fx"]' in CSS
    assert "background: var(--sx-surface-raised) !important" in CSS
    assert "border: 1px solid var(--sx-divider) !important" in CSS
    assert "@media (max-width: 620px)" in CSS
    assert "/* Camera FX: audience styling stays isolated from the raw recognition frame. */" not in LEGACY_CSS
    assert "/* Camera FX scope and momentary clean comparison. */" not in LEGACY_CSS
    assert ".camera-fx-header span,.camera-fx-layout header span{color:#5eddf7" not in LEGACY_CSS


def test_camera_fx_shell_is_content_sized_instead_of_inheriting_legacy_stretch():
    camera_fx = CSS[CSS.index("/* Camera FX */") : CSS.index("/* Spotify */")]
    assert "grid-template-rows: auto auto !important" in camera_fx
    assert "align-content: start !important" in camera_fx
    assert "width: 100% !important" in camera_fx
    assert "max-width: none !important" in camera_fx
    assert "margin: 0 !important" in camera_fx
    assert "min-height: 0 !important" in camera_fx


def test_camera_fx_uses_the_full_wide_desktop_stage_without_changing_preview_geometry():
    camera_fx = CSS[CSS.index("/* Camera FX */") : CSS.index("/* Spotify */")]
    assert "@media (min-width: 1800px)" in camera_fx
    assert "grid-template-columns: minmax(0, 1.3fr) minmax(620px, .7fr) !important" in camera_fx
    assert "grid-template-columns: repeat(4, minmax(0, 1fr)) !important" in camera_fx
    assert "aspect-ratio: 16 / 9 !important" in camera_fx
    assert "object-fit: contain !important" in camera_fx


def test_camera_fx_presets_use_a_compact_desktop_rail_with_safe_breakpoints():
    camera_fx = CSS[CSS.index("/* Camera FX */") : CSS.index("/* Spotify */")]
    assert "grid-template-columns: repeat(7, minmax(0, 1fr)) !important" in camera_fx
    assert "white-space: nowrap !important" in camera_fx
    assert "@media (max-width: 1400px)" in camera_fx
    assert "grid-template-columns: repeat(4, minmax(0, 1fr)) !important" in camera_fx
    assert "@media (max-width: 1100px)" in camera_fx
    assert "@media (max-width: 620px)" in camera_fx


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


def test_camera_fx_canvas_layering_and_clean_source_contract_are_owned_by_command_deck():
    assert ".camera-fx-canvas" in CSS
    assert "object-fit: fill !important" in CSS
    assert "pointer-events: none !important" in CSS
    assert ":is(.camera-feed-state-shield, .multi-card-camera-overlay)" in CSS
    assert "z-index: 5 !important" in CSS
    assert "Recognition and Program / OBS remain on the clean source." in CONTROL


def test_camera_fx_preview_copy_does_not_claim_program_or_obs_delivery():
    assert "Apply to Studio Preview" in CONTROL
    assert '"Bypass Studio Preview":"Apply to Studio Preview"' in STUDIO
    assert "Preview-only chroma key" in CONTROL
    assert '"Green screen preview active"' in STUDIO
