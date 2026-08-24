from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")

def test_single_card_control_explains_target_selection():
    assert 'id="singleCardControl"' in CONTROL
    assert 'id="singleCardTargetStatus"' in CONTROL
    assert 'id="singleCardTargetGuidance"' in CONTROL
    assert '>Choose Card</button>' in CONTROL

def test_single_region_is_automatically_selected_but_crowded_frames_are_numbered():
    assert "if(detected===1&&slots[0]?.slot)" in STUDIO
    assert "return recognizePickedSingleCard(slots[0].slot,true)" in STUDIO
    assert "renderMultiCardCameraOverlay(slots,[],true)" in STUDIO
    assert "Click a numbered box in the camera view." in STUDIO

def test_single_mode_and_control_visibility_are_persistent():
    assert 'localStorage.getItem(STUDIOX_RECOGNITION_MODE_KEY)||"single"' in STUDIO
    assert '$("singleCardControl").hidden=studioXRecognitionMode!=="single"' in STUDIO
