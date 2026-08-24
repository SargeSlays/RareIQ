from pathlib import Path

from rareiq.version import BUILD_DATE, CODENAME, PRODUCT_NAME, PROJECT_NAME, VERSION, version_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_development_version_payload_is_truthful_and_consistent():
    assert VERSION == "6.4.18-dev"
    assert CODENAME == "WAR Build Foundation"
    assert BUILD_DATE == "2026.08.23"
    assert version_payload() == {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "codename": CODENAME,
        "build_date": BUILD_DATE,
        "project": PROJECT_NAME,
    }


def test_about_page_uses_live_version_payload_without_stale_build_markers():
    about = (PROJECT_ROOT / "rareiq" / "web" / "static" / "about.html").read_text(encoding="utf-8")

    assert 'fetch("/api/version",{cache:"no-store"})' in about
    for element_id in ("version", "codename", "buildDate", "project", "ocrEngine", "catalog", "camera", "server"):
        assert f'id="{element_id}"' in about

    assert "X.1" not in about
    assert "12X.1.1" not in about
    assert "Professional Operator Console" not in about
    assert "â" not in about


def test_server_identity_strings_do_not_contain_mojibake():
    server = (PROJECT_ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")

    assert "version_payload()" in server
    assert "â€”" not in server
