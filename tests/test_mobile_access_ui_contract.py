from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")


def test_settings_exposes_read_only_mobile_access_readiness() -> None:
    for element_id in (
        "mobileAccessTitle",
        "mobileAccessSummary",
        "mobileAccessMode",
        "mobileAccessPairing",
        "mobileAccessAddresses",
        "mobileAccessRefresh",
        "mobileAccessCopy",
        "mobileAccessGuidance",
    ):
        assert HTML.count(f'id="{element_id}"') == 1


def test_mobile_access_panel_cannot_enable_remote_access_or_reveal_a_token() -> None:
    assert 'api("/api/remote-access/status")' in SCRIPT
    assert 'api("/api/remote-access/status",{method:"POST"' not in SCRIPT
    assert "RAREIQ_REMOTE_ACCESS_TOKEN" not in HTML
    assert "pairing_token" not in HTML
    assert "pairing_token" not in SCRIPT


def test_mobile_url_copy_is_explicit_and_never_embeds_a_secret() -> None:
    assert "navigator.clipboard.writeText(mobileAccessUrl)" in SCRIPT
    assert "mobileAccessCopy" in SCRIPT
    section = SCRIPT[SCRIPT.index("function renderMobileAccessStatus") : SCRIPT.index("async function loadCameraManagerState")]
    assert "token=" not in section
