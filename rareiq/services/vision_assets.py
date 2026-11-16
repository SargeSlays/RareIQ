"""Pinned local-only MediaPipe runtime. Binary assets stay outside the repository."""
from pathlib import Path
import hashlib

DEFAULT_VISION_CACHE = Path("F:/Caches/ProducerPlease/vision/mediapipe-0.10.21")
VERSION = "0.10.21"
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
ASSETS = {
    "vision_bundle.mjs": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/vision_bundle.mjs",
        "bytes": 137735,
        "sha256": "40f4123dfcd75cfa58add046919cc6f52fde66f009ff582997c09ba54c6ba27c"
    },
    "vision_wasm_internal.js": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm/vision_wasm_internal.js",
        "bytes": 204284,
        "sha256": "4a97e2520ba506c680ecd6ba6acfb146888afa0e2746d57f205352bc6ebb82eb"
    },
    "vision_wasm_internal.wasm": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm/vision_wasm_internal.wasm",
        "bytes": 9574032,
        "sha256": "f00ec4731faa23b3e714d00e88d4d10e2df5c0a427d3a2b4ae6e3526fdd14ef7"
    },
    "vision_wasm_nosimd_internal.js": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm/vision_wasm_nosimd_internal.js",
        "bytes": 204137,
        "sha256": "927def7b465c51b86e4b3060f93646aca4e27121f4b8fc0483786e407ea9cf1f"
    },
    "vision_wasm_nosimd_internal.wasm": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm/vision_wasm_nosimd_internal.wasm",
        "bytes": 9448638,
        "sha256": "3821ea9b1f7fb8c549ef2a064ef5c85750bf375c545a49fd6eea0df44a95f1f4"
    },
    "gesture_recognizer.task": {
        "url": "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
        "bytes": 8373440,
        "sha256": "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"
    },
    "face_landmarker.task": {
        "url": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "bytes": 3758596,
        "sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
    },
    "package.json": {
        "url": "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/package.json",
        "bytes": 592,
        "sha256": "18e96c370b666f1f6b096c96255f19a4750522d207cff5dc721aeb4c4e4da701"
    }
}

class VisionAssets:
    def __init__(self, directory=DEFAULT_VISION_CACHE):
        self.directory = Path(directory).resolve()
        self._verified = {}

    def resolve(self, name):
        if name not in ASSETS:
            raise ValueError("vision_asset_not_allowed")
        path = (self.directory / name).resolve()
        if path.parent != self.directory or not path.is_file():
            raise ValueError("vision_assets_unavailable")
        info = path.stat()
        stamp = (info.st_mtime_ns, info.st_size)
        expected = ASSETS[name]
        if info.st_size != expected["bytes"]:
            raise ValueError("vision_assets_unavailable")
        if self._verified.get(name) != stamp:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
                raise ValueError("vision_assets_unavailable")
            self._verified[name] = stamp
        return path

    def ready(self):
        try:
            for name in ASSETS:
                self.resolve(name)
            return True
        except (OSError, ValueError):
            return False
