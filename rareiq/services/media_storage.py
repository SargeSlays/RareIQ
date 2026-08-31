"""Durable index/settings writes for locally generated media."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(payload, indent=2, allow_nan=False).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            if handle.write(data) != len(data):
                raise OSError("incomplete_media_index_write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
