"""Live space weather data from NOAA SWPC.

Fetches current solar conditions from public NOAA endpoints.
No API key required. Results cached for 15 minutes to avoid
hammering the service.
"""

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

SWPC_BASE = "https://services.swpc.noaa.gov"

# Cache: url → (timestamp, data)
_cache: dict[str, tuple[float, any]] = {}
_CACHE_TTL = 900  # 15 minutes


def _fetch_json(url: str) -> any:
    """Fetch JSON from NOAA with caching."""
    now = time.time()
    if url in _cache:
        ts, data = _cache[url]
        if now - ts < _CACHE_TTL:
            return data

    req = urllib.request.Request(url, headers={"User-Agent": "ionis-mcp/1.2"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    _cache[url] = (now, data)
    return data


@dataclass
class SolarConditions:
    """Current space weather conditions."""

    # Solar indices
    sfi: Optional[float] = None
    sfi_date: str = ""
    ssn: Optional[float] = None
    ssn_date: str = ""

    # Geomagnetic
    kp: Optional[float] = None
    kp_timestamp: str = ""

    # Solar wind (DSCOVR)
    bz: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_density: Optional[float] = None
    wind_timestamp: str = ""

    # Alerts
    alerts: list = field(default_factory=list)

    # Fetch errors (non-fatal)
    errors: list = field(default_factory=list)


def fetch_current_conditions() -> SolarConditions:
    """Fetch current space weather conditions from NOAA SWPC.

    Makes 4-5 HTTP calls to public endpoints. Each is independent —
    failures are non-fatal and recorded in the errors list.
    """
    cond = SolarConditions()

    # 1. Solar flux (10.7 cm)
    try:
        data = _fetch_json(f"{SWPC_BASE}/products/summary/10cm-flux.json")
        if isinstance(data, list) and data:
            latest = data[-1] if len(data) > 1 else data[0]
            if isinstance(latest, dict):
                flux_str = latest.get("flux") or latest.get("Flux", "")
                if flux_str:
                    cond.sfi = float(flux_str)
                cond.sfi_date = latest.get("time_tag") or latest.get("TimeStamp", "")
        elif isinstance(data, dict):
            # legacy
            flux_str = data.get("Flux", "")
            if flux_str:
                cond.sfi = float(flux_str)
            cond.sfi_date = data.get("TimeStamp", "")
    except Exception as e:
        cond.errors.append(f"SFI: {e}")

    # 2. Kp index
    try:
        data = _fetch_json(f"{SWPC_BASE}/products/noaa-planetary-k-index.json")
        if isinstance(data, list) and data:
            latest = data[-1]
            if isinstance(latest, dict):
                cond.kp = float(latest.get("Kp") or latest.get("kp", 0))
                cond.kp_timestamp = latest.get("time_tag", "")
            elif isinstance(latest, list) and len(latest) >= 2:
                # legacy list-of-lists
                cond.kp = float(latest[1])
                cond.kp_timestamp = latest[0]
    except Exception as e:
        cond.errors.append(f"Kp: {e}")

    # 3. Solar wind magnetic field (Bz)
    try:
        data = _fetch_json(f"{SWPC_BASE}/products/summary/solar-wind-mag-field.json")
        if isinstance(data, list) and data:
            latest = data[-1] if len(data) > 1 else data[0]
            if isinstance(latest, dict):
                bz_str = latest.get("bz_gsm") or latest.get("Bz", "")
                if bz_str:
                    cond.bz = float(bz_str)
                cond.wind_timestamp = latest.get("time_tag") or latest.get("TimeStamp", "")
        elif isinstance(data, dict):
            # legacy
            bz_str = data.get("Bz", "")
            if bz_str:
                cond.bz = float(bz_str)
            cond.wind_timestamp = data.get("TimeStamp", "")
    except Exception as e:
        cond.errors.append(f"Bz: {e}")

    # 4. Solar wind speed/density (DSCOVR plasma)
    try:
        data = _fetch_json(f"{SWPC_BASE}/products/solar-wind/plasma-5-minute.json")
        if isinstance(data, list) and len(data) > 1:
            # First row is headers, last row is most recent
            latest = data[-1]
            if latest[1]:
                cond.wind_density = float(latest[1])
            if latest[2]:
                cond.wind_speed = float(latest[2])
    except Exception as e:
        cond.errors.append(f"Solar wind: {e}")

    # 5. Alerts
    try:
        data = _fetch_json(f"{SWPC_BASE}/products/alerts.json")
        if isinstance(data, list):
            # Keep only recent alerts (last 24h worth, most relevant)
            cond.alerts = data[:10] if len(data) > 10 else data
    except Exception as e:
        cond.errors.append(f"Alerts: {e}")

    return cond


def classify_sfi(sfi: float) -> str:
    """Classify SFI level for operator context."""
    if sfi >= 200:
        return "VERY HIGH"
    if sfi >= 150:
        return "HIGH"
    if sfi >= 120:
        return "MODERATE"
    if sfi >= 90:
        return "LOW"
    return "VERY LOW"


def classify_kp(kp: float) -> str:
    """Classify Kp for operator context."""
    if kp >= 7:
        return "SEVERE STORM"
    if kp >= 5:
        return "STORM"
    if kp >= 4:
        return "UNSETTLED"
    if kp >= 2:
        return "QUIET"
    return "VERY QUIET"


def classify_bz(bz: float) -> str:
    """Classify Bz for storm potential."""
    if bz <= -10:
        return "STRONGLY SOUTHWARD (storm likely)"
    if bz <= -5:
        return "SOUTHWARD (storm possible)"
    if bz < 0:
        return "SLIGHTLY SOUTH (minor impact)"
    return "NORTHWARD (favorable)"


def band_outlook(sfi: float, kp: float) -> dict[str, str]:
    """Generate band-by-band outlook based on SFI and Kp.

    Returns dict of band_name → outlook string.
    Based on operator experience and historical signature patterns.
    """
    outlook = {}

    # Storm penalty — high Kp degrades everything
    storm = kp >= 5

    if sfi >= 150:
        outlook["10m"] = "EXCELLENT — F2 wide open" if not storm else "DEGRADED — storm suppressing F2"
        outlook["12m"] = "EXCELLENT — solid DX" if not storm else "DEGRADED"
        outlook["15m"] = "EXCELLENT — all day" if not storm else "FAIR — storm impact"
        outlook["17m"] = "VERY GOOD" if not storm else "FAIR"
        outlook["20m"] = "VERY GOOD — reliable DX" if not storm else "FAIR — may be noisy"
        outlook["30m"] = "GOOD" if not storm else "FAIR"
        outlook["40m"] = "GOOD — D-layer absorption daytime" if not storm else "FAIR"
        outlook["80m"] = "FAIR — high D-layer absorption" if not storm else "POOR"
        outlook["160m"] = "FAIR — night only, high absorption" if not storm else "POOR"
    elif sfi >= 120:
        outlook["10m"] = "GOOD — open midday, may close early" if not storm else "POOR"
        outlook["12m"] = "GOOD — DX possible" if not storm else "POOR"
        outlook["15m"] = "VERY GOOD" if not storm else "FAIR"
        outlook["17m"] = "VERY GOOD" if not storm else "FAIR"
        outlook["20m"] = "EXCELLENT — primary DX band" if not storm else "FAIR"
        outlook["30m"] = "GOOD" if not storm else "FAIR"
        outlook["40m"] = "GOOD" if not storm else "FAIR"
        outlook["80m"] = "GOOD — night" if not storm else "FAIR"
        outlook["160m"] = "FAIR — night only" if not storm else "POOR"
    elif sfi >= 90:
        outlook["10m"] = "MARGINAL — sporadic openings" if not storm else "CLOSED"
        outlook["12m"] = "FAIR — short openings midday" if not storm else "POOR"
        outlook["15m"] = "GOOD" if not storm else "FAIR"
        outlook["17m"] = "GOOD" if not storm else "FAIR"
        outlook["20m"] = "VERY GOOD — best DX band today" if not storm else "FAIR"
        outlook["30m"] = "GOOD" if not storm else "FAIR"
        outlook["40m"] = "VERY GOOD" if not storm else "GOOD"
        outlook["80m"] = "GOOD — night" if not storm else "FAIR"
        outlook["160m"] = "GOOD — night, less absorption" if not storm else "FAIR"
    else:
        outlook["10m"] = "CLOSED — insufficient ionization" if not storm else "CLOSED"
        outlook["12m"] = "POOR — rare openings" if not storm else "CLOSED"
        outlook["15m"] = "FAIR — short windows" if not storm else "POOR"
        outlook["17m"] = "FAIR" if not storm else "POOR"
        outlook["20m"] = "GOOD — primary band" if not storm else "FAIR"
        outlook["30m"] = "VERY GOOD" if not storm else "GOOD"
        outlook["40m"] = "VERY GOOD — low absorption" if not storm else "GOOD"
        outlook["80m"] = "VERY GOOD — night, low noise" if not storm else "GOOD"
        outlook["160m"] = "GOOD — night, best conditions" if not storm else "FAIR"

    return outlook
