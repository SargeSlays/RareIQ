import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
MANIFEST = json.loads((STATIC / "rareiq.webmanifest").read_text(encoding="utf-8"))


def test_studiox_exposes_installable_mobile_metadata() -> None:
    assert '<link rel="manifest" href="/static/rareiq.webmanifest?v=6.8.98-brand-v1">' in HTML
    assert '<meta id="studioThemeColor" name="theme-color" content="#080B0D">' in HTML
    assert '<meta name="mobile-web-app-capable" content="yes">' in HTML
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in HTML
    assert '<meta name="apple-mobile-web-app-title" content="Rare IQ">' in HTML


def test_manifest_launches_the_live_operator_surface() -> None:
    assert MANIFEST["id"] == "/control"
    assert MANIFEST["start_url"] == "/control"
    assert MANIFEST["scope"] == "/"
    assert MANIFEST["display"] == "standalone"
    assert MANIFEST["orientation"] == "any"
    assert MANIFEST["theme_color"] == "#080B0D"
    assert MANIFEST["background_color"] == "#080B0D"


def test_manifest_icons_are_real_local_assets() -> None:
    assert {icon["sizes"] for icon in MANIFEST["icons"]} == {"any"}
    for icon in MANIFEST["icons"]:
        assert icon["src"].startswith("/static/")
        assert icon["type"] == "image/svg+xml"
        asset = STATIC / icon["src"].removeprefix("/static/")
        assert asset.is_file()
        assert asset.stat().st_size > 0


def test_mobile_install_contract_does_not_claim_offline_support() -> None:
    script = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
    assert "serviceWorker.register" not in HTML
    assert "serviceWorker.register" not in script
    assert "token" not in json.dumps(MANIFEST).lower()


def test_install_control_is_truthful_and_unique() -> None:
    script = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
    assert HTML.count('id="mobileInstallButton"') == 1
    assert HTML.count('id="mobileInstallStatus"') == 1
    assert 'window.addEventListener("beforeinstallprompt"' in script
    assert "event.preventDefault()" in script
    assert "await prompt.userChoice" in script
    assert 'choice?.outcome==="accepted"' in script
    assert 'window.addEventListener("appinstalled"' in script


def test_install_control_has_guidance_when_native_prompt_is_absent() -> None:
    script = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
    assert "Use your browser menu to Add to Home Screen." in HTML
    assert 'button.disabled=!installable' in script
    assert 'navigator.standalone===true' in script
    assert 'window.matchMedia?.("(display-mode: standalone)")' in script


def test_install_flow_does_not_add_offline_or_synthetic_success_behavior() -> None:
    script = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
    install = script[script.index("let deferredStudioXInstallPrompt") : script.index("let mobileAccessUrl")]
    assert "serviceWorker" not in install
    assert "fetch(" not in install
    assert "localStorage" not in install
    assert 'renderStudioXInstallState(accepted?"accepted":"dismissed")' in install
