from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_creator_reveal_api_and_browser_source_exist():
    assert '@app.get("/api/creator/reveal-sequence")' in SERVER
    assert '@app.post("/api/creator/reveal-sequence")' in SERVER
    assert '@app.get("/overlay/reveal-sequence")' in SERVER
    assert Path("rareiq/web/static/overlay_reveal_sequence.html").exists()


def test_creator_ui_configures_pack_suspense_and_reaction_tiers():
    assert 'id="creatorExpectedCards"' in CONTROL
    assert 'id="creatorRareSlot"' in CONTROL
    assert 'id="creatorStandardCopy"' in CONTROL
    assert 'id="creatorMediumCopy"' in CONTROL
    assert 'id="creatorGrailCopy"' in CONTROL
    assert 'id="creatorMediumValueThreshold"' in CONTROL
    assert 'id="creatorGrailValueThreshold"' in CONTROL
    assert 'id="creatorHitDecision"' in CONTROL
    assert 'id="creatorHitReason"' in CONTROL
    assert 'id="creatorHitValue"' in CONTROL
    assert 'id="creatorArmingDelay"' in CONTROL
    assert 'id="creatorRevealNow"' in CONTROL
    assert 'id="creatorCancelReveal"' in CONTROL
    assert '"/api/creator/reveal-sequence/release"' in STUDIO
    assert '"/api/creator/reveal-sequence/cancel"' in STUDIO
    assert "medium_value_threshold:mediumThreshold" in STUDIO
    assert "grail_value_threshold:grailThreshold" in STUDIO
    assert 'verified_market_value:"Verified market value"' in STUDIO
    assert '$("creatorHitDecision").dataset.tier=tier' in STUDIO
    assert "function renderRevealSequence(state={})" in STUDIO
    assert "function saveRevealSequence()" in STUDIO


def test_custom_audio_is_not_enabled_without_user_asset():
    assert "Audio remains off until you provide and license a custom asset." in CONTROL
    assert 'id="creatorAudioEnabled"' in CONTROL
    assert '$("creatorAudioEnabled")?.checked===true' in STUDIO
