from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
SERVER = ROOT / "rareiq" / "web" / "server.py"


def test_every_frontend_source_asset_is_referenced() -> None:
    assets = sorted(
        path for path in STATIC.iterdir()
        if path.is_file() and path.suffix in {".css", ".html", ".js"}
    )
    source = {path: path.read_text(encoding="utf-8") for path in assets}
    server_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(SERVER.parent.glob("*.py"))
    )
    unreachable = []

    for asset in assets:
        references = server_source + "\n" + "\n".join(
            text for path, text in source.items() if path != asset
        )
        if asset.name not in references:
            unreachable.append(asset.name)

    assert unreachable == []
