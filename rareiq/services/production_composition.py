"""Shared, bounded source/layout contract for local cameras and invited guests."""
from __future__ import annotations

import re
import hashlib
import json
import math


IMAGE_SOURCE = re.compile(r"^image:([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
LOCAL_SOURCE = re.compile(r"^(image|video|text|browser):([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
PRODUCER_SCREEN = re.compile(r"^producer:screen:[a-f0-9]{32}$")
SOURCE = re.compile(r"^(?:camera:[1-4]|producer:screen:[a-f0-9]{32}|guest:[a-f0-9]{32}:(?:camera|screen|audio)|(?:image|video|text|browser):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
LAYOUTS = frozenset({"auto", "grid", "spotlight", "pip", "custom"})
LAYER_FIELDS = frozenset({"x", "y", "width", "height", "crop", "opacity", "z", "locked", "hidden", "rotation", "group"})
MAX_REVISION = 2**53 - 1


def validate_sources(sources):
    if not isinstance(sources, list) or len(sources) > 6:
        raise ValueError("invalid_production_sources")
    if any(not isinstance(source, str) or not SOURCE.fullmatch(source) for source in sources):
        raise ValueError("invalid_production_source")
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate_production_source")
    return list(sources)


def normalize_layers(sources, layers=None, *, layout="custom"):
    """Bound geometry, preserve source order and drop metadata for removed sources.

    Hidden is visual only. Source audio and decode/readiness remain independently
    owned by the mixer and output transport, including for hidden pictures.
    """
    sources = validate_sources(sources)
    if layout not in LAYOUTS:
        raise ValueError("invalid_production_layout")
    if layers is None:
        layers = {}
    if (not isinstance(layers, dict) or len(layers) > 6
            or any(not isinstance(key, str) or not SOURCE.fullmatch(key) for key in layers)):
        raise ValueError("invalid_production_layers")
    if layout != "custom":
        if layers:
            raise ValueError("layers_require_custom_layout")
        return {}

    def number(value, minimum, maximum):
        if type(value) not in {int, float} or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError("invalid_production_layers")
        return round(float(value), 6)

    result = {}
    for index, source in enumerate(sources):
        value = layers.get(source, {})
        if not isinstance(value, dict) or set(value) - LAYER_FIELDS:
            raise ValueError("invalid_production_layers")
        crop = value.get("crop", {})
        if not isinstance(crop, dict) or set(crop) - {"top", "right", "bottom", "left"}:
            raise ValueError("invalid_production_layers")
        crop = {key: number(crop.get(key, 0), 0, .95) for key in ("top", "right", "bottom", "left")}
        if crop["top"] + crop["bottom"] >= 1 or crop["left"] + crop["right"] >= 1:
            raise ValueError("invalid_production_layers")
        z = value.get("z", index)
        locked, hidden = value.get("locked", False), value.get("hidden", False)
        if type(z) is not int or not 0 <= z <= 100 or type(locked) is not bool or type(hidden) is not bool:
            raise ValueError("invalid_production_layers")
        group = value.get("group", "")
        if (not isinstance(group, str) or len(group) > 40
                or re.search(r"[\x00-\x1f\x7f-\x9f]", group)
                or (group and not group.strip())):
            raise ValueError("invalid_production_layers")
        result[source] = {
            "x": number(value.get("x", 0), 0, 1), "y": number(value.get("y", 0), 0, 1),
            "width": number(value.get("width", 1), .01, 1), "height": number(value.get("height", 1), .01, 1),
            "crop": crop, "opacity": number(value.get("opacity", 1), 0, 1),
            "z": z, "locked": locked, "hidden": hidden,
            "rotation": number(value.get("rotation", 0), -180, 180), "group": group,
        }
    return result


def composition_id(sources, layout, layers=None):
    normalized = normalize_layers(sources, layers, layout=layout)
    # A pre-rotation scene keeps its receipt identity when loaded by a newer app.
    # Non-default transforms and membership still participate in exact-ID guards.
    identity_layers = {source: {key: value for key, value in layer.items()
                               if not (key == "rotation" and value == 0)
                               and not (key == "group" and value == "")}
                       for source, layer in normalized.items()}
    value = {"sources": validate_sources(sources), "layout": layout,
             "layers": identity_layers}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_scene_layers(scene):
    """Keep legacy scene bytes stable; validate custom geometry at storage boundaries."""
    result = dict(scene)
    layout = result.get("layout", "auto")
    if layout == "custom" or result.get("layers") is not None:
        sources = result.get("program_sources")
        if sources is None:
            sources = [f"camera:{int(result.get('program_slot', 1))}"]
        result["layers"] = normalize_layers(sources, result.get("layers"), layout=layout)
    preview_layout = result.get("preview_layout") or "auto"
    if preview_layout == "custom" or result.get("preview_layers") is not None:
        sources = result.get("preview_sources")
        if sources is None:
            sources = [f"camera:{int(result.get('preview_slot', 2))}"]
        result["preview_layers"] = normalize_layers(sources, result.get("preview_layers"), layout=preview_layout)
    return result


def composition_state(state):
    """Legacy slot-only state remains a single-camera composition."""
    result = dict(state)
    for bus in ("program", "preview"):
        sources = state.get(bus + "_sources")
        result[bus + "_sources"] = validate_sources(sources) if sources is not None else [f"camera:{int(state[bus + '_slot'])}"]
        result[bus + "_layout"] = state.get(bus + "_layout", "auto")
        result[bus + "_layers"] = normalize_layers(result[bus + "_sources"], state.get(bus + "_layers"), layout=result[bus + "_layout"])
        result[bus + "_composition_id"] = composition_id(result[bus + "_sources"], result[bus + "_layout"], result[bus + "_layers"])
    result["preview_revision"] = state.get("preview_revision", 0)
    return result
