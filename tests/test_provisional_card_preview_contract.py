from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_unverified_canonical_card_renders_as_safe_provisional_preview():
    assert "6.8.8-provisional-identity" in HTML
    assert "const canonicalPreview=canonicalCurrent" in JS
    assert "canonical_preview:true" in JS
    assert "canonicalCard ||\n      canonicalPreview ||" in JS
    assert "canonicalCollector===observedCollector" in JS


def test_footer_ocr_evidence_drives_visible_signal_bars():
    assert "snapshot?.ocr_collector_number||snapshot?.collector_number" in JS
    assert "normalize(snapshot?.ocr_confidence||snapshot?.confidence||1)" in JS
    assert "snapshot?.collector_number||card?.collector_number" in JS


def test_safe_identity_names_remain_visible_during_verification():
    assert "function renderProvisionalIdentityData" in JS
    assert "renderProvisionalIdentityData(card,snapshot)" in JS
    assert 'setCardText("cardPrintedName",printedName)' in JS
    assert 'setCardText("cardEnglishName",englishName)' in JS
