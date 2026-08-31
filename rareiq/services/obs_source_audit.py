"""Read-only checks for RareIQ's dedicated OBS scenes.

The report checks configuration, not rendered media or audible playback. Never
return another source's URL, custom CSS, device settings, or OBS credentials.
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlsplit


def clean_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        valid_port = parsed.port is None or 0 < parsed.port < 65536
    except ValueError:
        valid_port = False
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or not valid_port
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Use the RareIQ http(s) origin without credentials, path, query or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def new_result(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "state": "unavailable", "issues": []}


def issue(row: dict[str, Any], code: str, message: str, *, state: str = "attention") -> dict[str, Any]:
    row["state"] = state
    row["issues"].append({"code": code, "message": message})
    return row


def inspect_scene(item: dict[str, Any], items: list[dict[str, Any]],
                  read_settings: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    row = new_result(item)
    if len(items) > 64:
        return issue(row, "scene_complex", "This scene has more than 64 items; inspect it manually.", state="unavailable")
    expected_name = re.compile(re.escape(item["source"]) + r"(?: \(\d+\))?\Z")
    candidates = [entry for entry in items if isinstance(entry, dict)
                  and (entry.get("inputKind") == "browser_source" or expected_name.fullmatch(str(entry.get("sourceName", ""))))]
    if len(candidates) > 16:
        return issue(row, "scene_complex", "Too many browser inputs to check safely; inspect this scene manually.", state="unavailable")
    matches = []
    for entry in candidates:
        name = str(entry.get("sourceName") or "")
        response = read_settings(name)
        settings = response.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("Input settings unavailable")
        if expected_name.fullmatch(name) or settings.get("url") == item["url"]:
            matches.append((entry, response, settings))
    if not matches:
        return issue(row, "source_missing", "No matching browser input in this scene. Add the clean source from the library.", state="missing")
    if len(matches) != 1:
        return issue(row, "multiple_sources", "Multiple matching inputs found. Review duplicates in OBS; nothing was removed.")
    entry, response, settings = matches[0]
    row["state"] = "configured"
    if response.get("kind") != "browser_source":
        return issue(row, "wrong_kind", "The expected input is not a Browser Source. Review its type in OBS.")
    if settings.get("url") != item["url"] or settings.get("is_local_file") is True:
        issue(row, "url_mismatch", "Use the clean URL shown here, not an editor, preview or local file.")
    if any(type(settings.get(key)) is not int or settings[key] != item[key] for key in ("width", "height")):
        issue(row, "size_mismatch", f"Set Browser Source dimensions to {item['width']} × {item['height']}. Canvas transforms are left unchanged.")
    if bool(settings.get("reroute_audio", False)) != bool(item.get("audio")):
        issue(row, "audio_routing", "Enable Control audio via OBS for the soundboard." if item.get("audio") else "This visual source should not add a separate OBS audio mixer input.")
    if settings.get("shutdown") is True:
        issue(row, "shutdown_enabled", "Disable Shutdown source when not visible to keep the output connected.")
    if settings.get("restart_when_active") is True:
        issue(row, "restart_enabled", "Disable Refresh browser when scene becomes active to avoid resetting the output.")
    enabled = entry.get("sceneItemEnabled")
    if enabled is False:
        issue(row, "source_hidden", "The source eye is off in this scene. Enable it when you intend to use the output.")
    elif enabled is not True:
        issue(row, "visibility_unknown", "Source visibility could not be confirmed; inspect its eye control in OBS.")
    transform = entry.get("sceneItemTransform")
    if not isinstance(transform, dict):
        issue(row, "crop_unknown", "Cropping could not be inspected; review the source transform in OBS.")
    elif any(transform.get(key, 0) != 0 for key in ("cropLeft", "cropRight", "cropTop", "cropBottom")):
        issue(row, "source_cropped", "This source is cropped in OBS. Review the transform if you need the complete output.")
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    configured = sum(row["state"] == "configured" for row in rows)
    unavailable = sum(row["state"] == "unavailable" for row in rows)
    return {"sources": rows, "total": len(rows), "configured": configured,
            "attention": len(rows) - configured - unavailable, "unavailable": unavailable,
            "configuration_ok": bool(rows) and configured == len(rows)}
