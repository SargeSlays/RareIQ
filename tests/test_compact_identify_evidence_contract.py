from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_identify_retains_compatibility_values_but_hides_duplicate_summary():
    for element_id in (
        "identifyCatalogStatus",
        "identifyVisualConfidence",
        "identifyAcceptanceEvidence",
    ):
        assert f'id="{element_id}"' in HTML
    assert 'class="studiox-identity-summary" aria-hidden="true"' in HTML
    identify_css = CSS[CSS.index("Identify is an evidence inspector") :]
    assert ".studiox-identity-summary{display:none!important}" in identify_css


def test_identify_promotes_verification_evidence_and_compact_review_action():
    assert "studiox-identity-evidence-heading" in HTML
    assert "Verification evidence" in HTML
    assert ">Review identity</button>" in HTML
    identify_css = CSS[CSS.index("Identify is an evidence inspector") :]
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in identify_css
    assert ".studiox-identity-review" in identify_css


def test_identify_evidence_is_responsive_and_light_theme_aware():
    identify_css = CSS[CSS.index("Identify is an evidence inspector") :]
    assert "html[data-theme=light]" in identify_css
    assert "@media(max-width:520px)" in identify_css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in identify_css
