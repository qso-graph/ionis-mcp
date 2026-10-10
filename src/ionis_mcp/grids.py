"""Maidenhead grid square utilities.

Provides grid-to-coordinate conversion, validation, and an in-memory
lookup cache loaded from the grid_lookup SQLite database.
"""

import math
import re
import sqlite3

GRID_RE = re.compile(r"^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$")

# Band ID → (name, center MHz)
BANDS = {
    102: ("160m", 1.8),
    103: ("80m", 3.5),
    104: ("60m", 5.3),
    105: ("40m", 7.0),
    106: ("30m", 10.1),
    107: ("20m", 14.0),
    108: ("17m", 18.1),
    109: ("15m", 21.0),
    110: ("12m", 24.9),
    111: ("10m", 28.0),
}

# Reverse: name → band ID
BAND_BY_NAME = {v[0]: k for k, v in BANDS.items()}


def band_name(band_id: int) -> str:
    """ADIF band ID → human-readable name like '10m (28 MHz)'."""
    if band_id in BANDS:
        name, mhz = BANDS[band_id]
        return f"{name} ({mhz} MHz)"
    return f"Band {band_id}"


def validate_grid(grid: str) -> str | None:
    """Validate and normalize a Maidenhead grid. Returns None if invalid."""
    if not grid or not isinstance(grid, str):
        return None
    g = grid.strip().rstrip("\x00")
    if GRID_RE.match(g):
        return g[:2].upper() + g[2:4] + (g[4:6].lower() if len(g) >= 6 else "")
    return None


def grid_to_latlon(grid: str) -> tuple[float, float]:
    """Convert 4-char or 6-char Maidenhead grid to (lat, lon) centroid.

    Same algorithm as ionis-training/versions/common/model.py:grid4_to_latlon
    Extended to support 6-char grids for higher precision.
    """
    g = grid.strip().rstrip("\x00").upper()
    if len(g) < 4:
        return 0.0, 0.0

    lon = (ord(g[0]) - ord("A")) * 20.0 - 180.0 + int(g[2]) * 2.0
    lat = (ord(g[1]) - ord("A")) * 10.0 - 90.0 + int(g[3]) * 1.0

    if len(g) >= 6:
        lon += (ord(g[4]) - ord("A")) * (2.0 / 24.0)
        lat += (ord(g[5]) - ord("A")) * (1.0 / 24.0)
        # 6-char subsquare centroid
        lon += 1.0 / 24.0
        lat += 0.5 / 24.0
    else:
        # 4-char square centroid
        lon += 1.0
        lat += 0.5

    return lat, lon


class GridLookup:
    """In-memory grid → (lat, lon) cache, optionally loaded from SQLite."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, float]] = {}

    def load_from_sqlite(self, db_path: str) -> int:
        """Load grid_lookup.sqlite into memory. Returns row count."""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT grid, latitude, longitude FROM grid_lookup").fetchall()
            for grid, lat, lon in rows:
                g = grid.strip().rstrip("\x00").upper()
                self._cache[g] = (lat, lon)
            return len(rows)
        finally:
            conn.close()

    def get(self, grid: str) -> tuple[float, float]:
        """Look up grid coordinates. Uses cache first, falls back to math."""
        g = grid.strip().rstrip("\x00").upper()[:4]
        if g in self._cache:
            return self._cache[g]
        return grid_to_latlon(grid)

    @property
    def size(self) -> int:
        return len(self._cache)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def azimuth_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (azimuth) in degrees from point 1 to point 2."""
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
