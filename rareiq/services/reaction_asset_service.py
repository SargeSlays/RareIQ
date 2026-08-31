from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class ReactionAssetService:
    ALLOWED = {
        "audio/mpeg": ("audio", ".mp3", 15 * 1024 * 1024),
        "audio/wav": ("audio", ".wav", 15 * 1024 * 1024),
        "audio/ogg": ("audio", ".ogg", 15 * 1024 * 1024),
        "image/png": ("visual", ".png", 8 * 1024 * 1024),
        "image/jpeg": ("visual", ".jpg", 8 * 1024 * 1024),
        "image/webp": ("visual", ".webp", 8 * 1024 * 1024),
        "image/gif": ("visual", ".gif", 8 * 1024 * 1024),
    }
    TIERS = ("standard", "low", "medium", "grail")

    def __init__(self, root: Path, state_path: Path) -> None:
        self.root = root
        self.state_path = state_path
        self._lock = threading.RLock()
        self._assets: dict[str, dict[str, Any]] = {}
        self._mapping = {tier: {"audio": None, "visual": None} for tier in self.TIERS}
        self._soundboard: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            assets = payload.get("assets") if isinstance(payload.get("assets"), dict) else {}
            for asset_id, asset in assets.items():
                if not isinstance(asset, dict) or asset.get("id") != asset_id:
                    continue
                rule = self.ALLOWED.get(str(asset.get("mime") or ""))
                if not rule or asset.get("kind") != rule[0] or not isinstance(asset.get("path"), str):
                    continue
                try:
                    created_at = float(asset.get("created_at") or 0)
                except (ValueError, TypeError):
                    created_at = 0
                self._assets[asset_id] = {**asset, "created_at": created_at if math.isfinite(created_at) else 0}
            mapping = payload.get("mapping") if isinstance(payload.get("mapping"), dict) else {}
            for tier in self.TIERS:
                if isinstance(mapping.get(tier), dict):
                    for kind in ("audio", "visual"):
                        value = mapping[tier].get(kind)
                        self._mapping[tier][kind] = value if isinstance(value, str) else None
            soundboard = payload.get("soundboard") if isinstance(payload.get("soundboard"), list) else []
            self._soundboard = [self._sanitize_pad(pad, index) for index, pad in enumerate(soundboard[:50]) if isinstance(pad, dict)]
        except (OSError, ValueError, TypeError):
            return

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps({"version": 2, "assets": self._assets, "mapping": self._mapping, "soundboard": self._soundboard}, indent=2), encoding="utf-8")
        temp.replace(self.state_path)

    @staticmethod
    def _signature_ok(mime: str, data: bytes) -> bool:
        return {
            "audio/mpeg": data.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
            "audio/wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
            "audio/ogg": data.startswith(b"OggS"),
            "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        }.get(mime, False)

    def add(self, name: str, mime: str, data: bytes) -> dict[str, Any]:
        mime = str(mime or "").split(";", 1)[0].lower()
        rule = self.ALLOWED.get(mime)
        if not rule:
            return {"created": False, "reason": "unsupported_media_type"}
        kind, extension, limit = rule
        if not data or len(data) > limit:
            return {"created": False, "reason": "asset_empty" if not data else "asset_too_large", "max_bytes": limit}
        if not self._signature_ok(mime, data):
            return {"created": False, "reason": "file_signature_mismatch"}
        asset_id = str(uuid.uuid4())
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or f"asset{extension}").stem).strip("._")[:60] or "asset"
        path = self.root / kind / f"{asset_id}_{safe_name}{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        asset = {"id": asset_id, "name": safe_name, "kind": kind, "mime": mime, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "path": str(path), "created_at": time.time()}
        with self._lock:
            try:
                if path.write_bytes(data) != len(data):
                    raise OSError("incomplete_asset_write")
                self._assets[asset_id] = asset
                self._persist()
            except Exception:
                self._assets.pop(asset_id, None)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        return {"created": True, "asset": self._public(asset)}

    @staticmethod
    def _public(asset: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in asset.items() if key != "path"} | {"url": f"/api/creator/assets/{asset['id']}"}

    def get_path(self, asset_id: str) -> tuple[Path, str] | None:
        with self._lock:
            asset = self._assets.get(str(asset_id))
            if not asset:
                return None
            try:
                path = Path(str(asset.get("path") or "")).resolve()
                root = self.root.resolve()
                if not path.is_file() or root not in path.parents:
                    return None
            except (OSError, ValueError):
                return None
            return path, str(asset["mime"])

    def map_tier(self, tier: str, kind: str, asset_id: str | None) -> dict[str, Any]:
        tier, kind = str(tier).lower(), str(kind).lower()
        if tier not in self.TIERS or kind not in {"audio", "visual"}:
            return {"updated": False, "reason": "invalid_mapping"}
        with self._lock:
            if asset_id:
                asset = self._assets.get(asset_id)
                if not asset or not self.get_path(asset_id):
                    return {"updated": False, "reason": "asset_not_found"}
                if asset.get("kind") != kind:
                    return {"updated": False, "reason": "asset_kind_mismatch"}
            previous = self._mapping[tier][kind]
            self._mapping[tier][kind] = asset_id or None
            try:
                self._persist()
            except Exception:
                self._mapping[tier][kind] = previous
                raise
            return {"updated": True, **self.snapshot()}

    @staticmethod
    def _sanitize_pad(pad: dict[str, Any], index: int) -> dict[str, Any]:
        return {"id": str(pad.get("id") or f"pad-{index + 1}")[:60], "label": str(pad.get("label") or f"Sound {index + 1}")[:40], "asset_id": str(pad.get("asset_id") or "") or None, "image_asset_id": str(pad.get("image_asset_id") or "") or None}

    def configure_soundboard(self, pads: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            clean = [self._sanitize_pad(pad, index) for index, pad in enumerate(pads[:50]) if isinstance(pad, dict)]
            if len({pad["id"] for pad in clean}) != len(clean):
                return {"updated": False, "reason": "duplicate_pad_id"}
            for pad in clean:
                asset = self._assets.get(str(pad.get("asset_id") or ""))
                if pad.get("asset_id") and (not asset or asset.get("kind") != "audio" or not self.get_path(pad["asset_id"])):
                    return {"updated": False, "reason": "audio_asset_not_found"}
                image = self._assets.get(str(pad.get("image_asset_id") or ""))
                if pad.get("image_asset_id") and (not image or image.get("kind") != "visual" or not self.get_path(pad["image_asset_id"])):
                    return {"updated": False, "reason": "image_asset_not_found"}
            previous = self._soundboard
            self._soundboard = clean
            try:
                self._persist()
            except Exception:
                self._soundboard = previous
                raise
            return {"updated": True, **self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            available = {asset_id: asset for asset_id, asset in self._assets.items() if self.get_path(asset_id)}
            assets = [self._public(asset) for asset in available.values()]
            mapping: dict[str, dict[str, Any]] = {}
            for tier, values in self._mapping.items():
                mapping[tier] = {}
                for kind in ("audio", "visual"):
                    asset = available.get(values.get(kind) or "")
                    mapping[tier][kind] = self._public(asset) if asset and asset.get("kind") == kind else None
            pads = []
            for pad in self._soundboard:
                asset = available.get(str(pad.get("asset_id") or ""))
                image = available.get(str(pad.get("image_asset_id") or ""))
                pads.append(dict(pad) | {"asset": self._public(asset) if asset and asset.get("kind") == "audio" else None, "image_asset": self._public(image) if image and image.get("kind") == "visual" else None})
            return {"assets": sorted(assets, key=lambda item: -item["created_at"]), "mapping": mapping, "soundboard": pads}
