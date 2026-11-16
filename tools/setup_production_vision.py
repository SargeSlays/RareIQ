"""Download only pinned, hash-verified public inference assets (no extraction)."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rareiq.services.vision_assets import ASSETS, DEFAULT_VISION_CACHE, MAX_DOWNLOAD_BYTES, VERSION


def setup(directory):
    destination = Path(directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total = sum(item["bytes"] for item in ASSETS.values())
    if total > MAX_DOWNLOAD_BYTES:
        raise ValueError("download_limit_exceeded")
    for name, item in ASSETS.items():
        path = destination / name
        if path.exists():
            if path.is_symlink() or path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Existing asset differs; select a fresh cache directory.")
            continue
        part = destination / (name + ".part")
        # Exclusive create preserves any interrupted download for review.
        digest, count = hashlib.sha256(), 0
        with part.open("xb") as output, urllib.request.urlopen(item["url"], timeout=30) as response:
            if response.url != item["url"]:
                raise ValueError("unexpected_download_redirect")
            while chunk := response.read(65536):
                count += len(chunk)
                if count > item["bytes"]:
                    raise ValueError("asset_size_exceeded")
                digest.update(chunk)
                output.write(chunk)
        if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("asset_hash_mismatch")
        part.rename(path)
    manifest = {"version": VERSION, "files": ASSETS, "total_bytes": total}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(ASSETS)} local assets, {total} bytes. No camera was opened.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_VISION_CACHE)
    setup(parser.parse_args().cache)
