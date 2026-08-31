"""Catalog display order, not a market-value or pack-odds ranking.

Only explicit rarity labels are classified. Never guess from card artwork,
collector number, or name. Unknown labels remain available below known tiers.
English Ultra Rare and Japanese UR belong to different rarity systems.
"""


_TIERS = (
    (1100, ("mega hyper rare", "mega ultra rare", "mhr", "mur")),
    (1000, ("hyper rare", "hr", "secret rare", "rare secret", "rainbow rare", "rare rainbow")),
    (900, ("special illustration rare", "special art rare", "special rare", "sir", "sar")),
    (850, ("shiny ultra rare", "rare shiny gx", "ssr")),
    (800, ("shiny rare", "rare shiny", "s")),
    (750, ("ultra rare", "rare ultra", "ur", "super rare", "sr")),
    (700, ("illustration rare", "art rare", "ir", "ar", "character super rare", "csr")),
    (650, ("character rare", "chr", "amazing rare", "rare amazing", "ace spec rare", "ace spec")),
    (600, ("triple rare", "rrr", "rare holo vmax", "rare holo vstar")),
    (500, ("double rare", "rr", "rare holo ex", "rare holo gx", "rare holo v", "rare prime", "rare legend")),
    (400, ("holo rare", "rare holo", "rare holo lv.x", "rare break")),
    (300, ("rare", "r")),
    (200, ("uncommon", "u")),
    (100, ("common", "c")),
)
_PRIORITY = {label: rank for rank, labels in _TIERS for label in labels}


def rarity_priority(value: str | None, language: str | None = None) -> int:
    key = " ".join(str(value or "").strip().casefold().split())
    if not key:
        return -1
    if key == "ur" and str(language or "").strip().casefold() == "japanese":
        return 1000
    return _PRIORITY.get(key, 0)


def rarity_sort_key(value: str | None, language: str | None = None) -> tuple[int, str]:
    return -rarity_priority(value, language), str(value or "").strip().casefold()
