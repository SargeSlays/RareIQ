import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
MANIFEST = json.loads((STATIC / "rareiq.webmanifest").read_text(encoding="utf-8"))


def test_studiox_exposes_installable_mobile_metadata() -> None:
    assert '<link rel="manifest" href="/static/rareiq.webmanifest?v=6.4.18-mobile1">' in HTML
    assert '<meta name="theme-color" content="#050c13">' in HTML
    assert '<meta name="mobile-web-app-capable" content="yes">' in HTML
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in HTML
    assert '<meta name="apple-mobile-web-app-title" content="RareIQ">' in HTML


def test_manifest_launches_the_live_operator_surface() -> None:
    assert MANIFEST["id"] == "/control"
    assert MANIFEST["start_url"] == "/control"
    assert MANIFEST["scope"] == "/"
    assert MANIFEST["display"] == "standalone"
    assert MANIFEST["orientation"] == "any"
    assert MANIFEST["theme_color"] == "#050c13"
    assert MANIFEST["background_color"] == "#050c13"


def test_manifest_icons_are_real_local_assets() -> None:
    assert {icon["sizes"] for icon in MANIFEST["icons"]} == {"192x192", "512x512"}
    for icon in MANIFEST["icons"]:
        assert icon["src"].startswith("/static/")
        asset = STATIC / icon["src"].removeprefix("/static/")
        assert asset.is_file()
        assert asset.stat().st_size > 0


def test_mobile_install_contract_does_not_claim_offline_support() -> None:
    script = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
    assert "serviceWorker.register" not in HTML
    assert "serviceWorker.register" not in script
    assert "token" not in json.dumps(MANIFEST).lower()
