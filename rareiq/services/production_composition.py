"""Shared, bounded source/layout contract for local cameras and invited guests."""
from __future__ import annotations

import re


IMAGE_SOURCE = re.compile(r"^image:([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
LOCAL_SOURCE = re.compile(r"^(image|video|text|browser):([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
SOURCE = re.compile(r"^(?:camera:[1-4]|guest:[a-f0-9]{32}:(?:camera|screen|audio)|(?:image|video|text|browser):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
LAYOUTS = frozenset({"auto", "grid", "spotlight", "pip"})


def validate_sources(sources):
    if not isinstance(sources, list) or len(sources) > 6:
        raise ValueError("invalid_production_sources")
    if any(not isinstance(source, str) or not SOURCE.fullmatch(source) for source in sources):
        raise ValueError("invalid_production_source")
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate_production_source")
    return list(sources)


def composition_state(state):
    """Legacy slot-only state remains a single-camera composition."""
    result = dict(state)
    for bus in ("program", "preview"):
        sources = state.get(bus + "_sources")
        result[bus + "_sources"] = validate_sources(sources) if sources is not None else [f"camera:{int(state[bus + '_slot'])}"]
        result[bus + "_layout"] = state.get(bus + "_layout", "auto")
    return result
