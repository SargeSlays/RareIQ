"""Clean browser outputs shared by the operator guide and OBS setup.

Listing a source does not claim it is live or verified in an external encoder.
"""
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BroadcastSource:
    key: str
    label: str
    path: str
    scene: str
    source: str
    width: int = 1920
    height: int = 1080
    audio: bool = False
    placement: str = "canvas"


_SOURCES = (
    BroadcastSource("program", "Program", "/program", "RareIQ Program", "RareIQ Program Browser"),
    BroadcastSource("graphics", "Graphics", "/overlay/graphics", "RareIQ Graphics", "RareIQ Graphics Browser"),
    BroadcastSource("production_screen", "Production Screen", "/production-screen", "RareIQ Production Screen", "RareIQ Production Screen Browser"),
    BroadcastSource("replay", "Replay", "/replay", "RareIQ Replay", "RareIQ Replay Browser"),
    BroadcastSource("rare_intelligence", "Rare Intelligence", "/overlay/pokedex", "RareIQ Intelligence", "RareIQ Intelligence Browser"),
    BroadcastSource("multi_card", "Selected Cards", "/overlay/multi-card", "RareIQ Multi Card", "RareIQ Multi Card Browser"),
    BroadcastSource("set_chase", "Set Chase Bar", "/overlay/set-chase", "RareIQ Set Chase", "RareIQ Set Chase Browser", 1280, 320, placement="bottom-center"),
    BroadcastSource("scan_camera", "Active Scan Camera", "/output/camera/scan", "RareIQ Scan Camera", "RareIQ Scan Camera Browser"),
    *(BroadcastSource(f"camera_{slot}", f"Camera {slot}", f"/output/camera/{slot}", f"RareIQ Camera {slot}", f"RareIQ Camera {slot} Browser") for slot in range(1, 5)),
    BroadcastSource("all_cameras", "All Cameras", "/output/camera/all", "RareIQ All Cameras", "RareIQ All Cameras Browser"),
    BroadcastSource("soundboard", "Soundboard Audio", "/output/soundboard", "RareIQ Soundboard", "RareIQ Soundboard Audio", audio=True),
)


def broadcast_sources() -> list[dict[str, Any]]:
    """Fresh metadata: per-request OBS actions must not mutate the catalog."""
    return [asdict(source) for source in _SOURCES]
