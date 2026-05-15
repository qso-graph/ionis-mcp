"""ionis-mcp — MCP server for IONIS HF propagation analytics.

Wraps the IONIS distributed datasets (SQLite from SourceForge) and exposes
propagation analytics as MCP tools. Users download datasets, install this
package, point it at their data directory, and Claude can answer propagation
questions directly.

11 tools for querying 175M+ signatures across WSPR, RBN, Contest,
DXpedition, and PSK Reporter datasets, plus live space weather conditions.
"""

import argparse
import logging
import os
import sys

from fastmcp import FastMCP

from . import __spec_version__, __version__, default_data_dir
from .database import DatabaseManager, SIGNATURE_SOURCES
from .grids import (
    GridLookup,
    band_name,
    validate_grid,
    haversine_km,
    azimuth_deg,
    BANDS,
)
from .solar import (
    solar_elevation_deg,
    classify_solar,
    classify_path_solar,
    month_to_mid_doy,
)
from .noaa import (
    fetch_current_conditions,
    classify_sfi,
    classify_kp,
    classify_bz,
    band_outlook,
)

logger = logging.getLogger("ionis-mcp")

# ── Globals (initialized in main) ───────────────────────────────────────────

mcp = FastMCP("IONIS Propagation Analytics")
db: DatabaseManager | None = None
grid_lookup: GridLookup = GridLookup()


def _require_db() -> DatabaseManager:
    """Get database manager or raise."""
    if db is None:
        raise RuntimeError("Database not initialized. Set IONIS_DATA_DIR.")
    return db


def _format_number(n: int | float) -> str:
    """Format a number with commas for readability."""
    if isinstance(n, float):
        return f"{n:,.1f}"
    return f"{n:,}"


# ── Tool 0: get_version_info — fleet identity attestation ──────────────────


def _version_info_payload() -> dict[str, str]:
    """Build the version info envelope. Pulled into a helper so tests can
    call it directly without going through the FastMCP wrapper."""
    return {
        "service_name": "ionis-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
    }


@mcp.tool()
def get_version_info() -> dict[str, str]:
    """Get ionis-mcp service version and upstream dataset version.

    Returns the running PyPI version of ionis-mcp and the IONIS
    SourceForge dataset bundle revision in use. Use this to confirm
    fleet alignment across MCP deployments — agents can compare
    service_version and spec_version across servers to detect drift
    without going outside the MCP protocol.

    Returns:
        service_name, service_version (PyPI), and spec_version (dataset bundle).
    """
    return _version_info_payload()


# ── Tool 1: list_datasets ───────────────────────────────────────────────────

@mcp.tool()
def list_datasets() -> str:
    """Show available IONIS datasets and their statistics.

    Lists all datasets found in the configured data directory with
    row counts, file sizes, and descriptions. Use this to see what
    data is available for querying.
    """
    mgr = _require_db()
    datasets = mgr.discover()

    if not datasets:
        return (
            "No datasets found. Check that IONIS_DATA_DIR points to the "
            "extracted SourceForge dataset directory.\n\n"
            "Download from: https://sourceforge.net/p/ionis-ai"
        )

    lines = ["# Available IONIS Datasets\n"]
    lines.append(f"Data directory: `{mgr.data_dir}`\n")
    lines.append("| Dataset | Rows | Size (MB) | Description |")
    lines.append("|---------|------|-----------|-------------|")

    total_rows = 0
    total_size = 0.0
    for ds in datasets:
        total_rows += max(ds.row_count, 0)
        total_size += ds.file_size_mb
        rows_str = _format_number(ds.row_count) if ds.row_count >= 0 else "error"
        lines.append(
            f"| {ds.key} | {rows_str} | {ds.file_size_mb:,.1f} | {ds.description} |"
        )

    lines.append(f"\n**Total**: {_format_number(total_rows)} rows, {total_size:,.1f} MB")
    return "\n".join(lines)


# ── Tool 2: query_signatures ────────────────────────────────────────────────

@mcp.tool()
def query_signatures(
    source: str = "all",
    band: int | None = None,
    tx_grid: str | None = None,
    rx_grid: str | None = None,
    hour: int | None = None,
    month: int | None = None,
    min_spots: int = 5,
    limit: int = 100,
) -> str:
    """Query propagation signatures with filters.

    Searches across WSPR, RBN, Contest, DXpedition, and PSKR signature
    tables. All signature tables share the same 13-column schema.

    Args:
        source: "wspr", "rbn", "contest", "dxpedition", "pskr", or "all"
        band: ADIF band ID (102=160m, 103=80m, 104=60m, 105=40m,
              106=30m, 107=20m, 108=17m, 109=15m, 110=12m, 111=10m)
        tx_grid: TX grid square (4-char like "DN13" or 2-char field like "DN")
        rx_grid: RX grid square (4-char or 2-char)
        hour: UTC hour (0-23)
        month: Month (1-12)
        min_spots: Minimum spot count filter (default: 5)
        limit: Max rows returned (default: 100, max: 1000)

    Returns:
        Matching signatures with all columns plus source label.
    """
    mgr = _require_db()
    limit = min(max(1, limit), 1000)

    rows = mgr.query_signatures(
        source=source, band=band, tx_grid=tx_grid, rx_grid=rx_grid,
        hour=hour, month=month, min_spots=min_spots, limit=limit,
    )

    if not rows:
        filters = []
        if band:
            filters.append(f"band={band_name(band)}")
        if tx_grid:
            filters.append(f"tx={tx_grid}")
        if rx_grid:
            filters.append(f"rx={rx_grid}")
        if hour is not None:
            filters.append(f"hour={hour}z")
        if month:
            filters.append(f"month={month}")
        return f"No signatures found matching: {', '.join(filters) or 'no filters'}"

    lines = [f"# Signature Query Results ({len(rows)} rows)\n"]
    lines.append("| Source | TX | RX | Band | Hour | Month | SNR | Spots | Reliability | SFI | Kp | Distance |")
    lines.append("|--------|----|----|------|------|-------|-----|-------|-------------|-----|----|----------|")

    for r in rows:
        b = band_name(r.get("band", 0)).split(" ")[0]
        lines.append(
            f"| {r.get('source', '?')} | {r.get('tx_grid_4', '')} | {r.get('rx_grid_4', '')} "
            f"| {b} | {r.get('hour', '')}z | {r.get('month', '')} "
            f"| {r.get('median_snr', ''):.1f} | {_format_number(r.get('spot_count', 0))} "
            f"| {r.get('reliability', 0):.3f} | {r.get('avg_sfi', 0):.0f} "
            f"| {r.get('avg_kp', 0):.1f} | {_format_number(r.get('avg_distance', 0))} km |"
        )

    return "\n".join(lines)


# ── Tool 3: band_openings ──────────────────────────────────────────────────

@mcp.tool()
def band_openings(
    tx_grid: str,
    rx_grid: str,
    band: int,
    source: str = "all",
) -> str:
    """When does a specific band open between two grid squares?

    Shows propagation hour-by-hour (0-23z) for a grid pair on a given band.
    Includes spot-count-weighted SNR, reliability, SFI, and solar elevation
    at both endpoints.

    Args:
        tx_grid: Transmitter 4-char Maidenhead grid (e.g., "DN13")
        rx_grid: Receiver 4-char Maidenhead grid (e.g., "JO51")
        band: ADIF band ID (102-111)

    Returns:
        24-row hourly profile with SNR, spots, reliability, solar geometry.
    """
    mgr = _require_db()

    tx_valid = validate_grid(tx_grid)
    rx_valid = validate_grid(rx_grid)
    if not tx_valid or not rx_valid:
        return f"Invalid grid: tx={tx_grid}, rx={rx_grid}. Use 4-char Maidenhead (e.g., DN13)."

    tx_lat, tx_lon = grid_lookup.get(tx_valid)
    rx_lat, rx_lon = grid_lookup.get(rx_valid)
    dist = haversine_km(tx_lat, tx_lon, rx_lat, rx_lon)
    azm = azimuth_deg(tx_lat, tx_lon, rx_lat, rx_lon)

    hourly = mgr.query_band_openings(tx_valid, rx_valid, band, source)

    lines = [
        f"# Band Openings: {tx_valid} → {rx_valid} on {band_name(band)}\n",
        f"**Distance**: {dist:,.0f} km | **Azimuth**: {azm:.0f}°\n",
        f"Solar elevation shown for mid-June (DOY 172) — seasonal variation applies.\n",
        "| Hour | SNR (dB) | Spots | Reliability | SFI | TX Solar | RX Solar | Classification |",
        "|------|----------|-------|-------------|-----|----------|----------|----------------|",
    ]

    doy = 172  # Mid-June for representative solar geometry
    for entry in hourly:
        h = entry["hour"]
        tx_elev = solar_elevation_deg(tx_lat, tx_lon, h + 0.5, doy)
        rx_elev = solar_elevation_deg(rx_lat, rx_lon, h + 0.5, doy)
        cls = classify_solar(min(tx_elev, rx_elev))

        if entry["total_spots"] > 0:
            snr_str = f"{entry['median_snr']:.1f}"
            spots_str = _format_number(entry["total_spots"])
            rel_str = f"{entry['reliability']:.3f}"
            sfi_str = f"{entry['avg_sfi']:.0f}" if entry["avg_sfi"] else "—"
        else:
            snr_str = "—"
            spots_str = "0"
            rel_str = "—"
            sfi_str = "—"

        lines.append(
            f"| {h:02d}z | {snr_str} | {spots_str} | {rel_str} "
            f"| {sfi_str} | {tx_elev:+.1f}° | {rx_elev:+.1f}° | {cls} |"
        )

    return "\n".join(lines)


# ── Tool 4: path_analysis ──────────────────────────────────────────────────

@mcp.tool()
def path_analysis(
    tx_grid: str,
    rx_grid: str,
    source: str = "all",
) -> str:
    """Complete analysis of a propagation path across all bands and hours.

    Provides distance/azimuth, best band/hour combinations ranked by
    reliability, seasonal patterns, solar geometry, and total observation
    counts from all available data sources.

    Args:
        tx_grid: Transmitter 4-char Maidenhead grid
        rx_grid: Receiver 4-char Maidenhead grid
        source: Dataset source or "all"
    """
    mgr = _require_db()

    tx_valid = validate_grid(tx_grid)
    rx_valid = validate_grid(rx_grid)
    if not tx_valid or not rx_valid:
        return f"Invalid grid: tx={tx_grid}, rx={rx_grid}."

    tx_lat, tx_lon = grid_lookup.get(tx_valid)
    rx_lat, rx_lon = grid_lookup.get(rx_valid)
    dist = haversine_km(tx_lat, tx_lon, rx_lat, rx_lon)
    azm = azimuth_deg(tx_lat, tx_lon, rx_lat, rx_lon)

    sigs = mgr.query_path_summary(tx_valid, rx_valid, source)

    if not sigs:
        return (
            f"No signatures found for {tx_valid} → {rx_valid}.\n"
            f"Distance: {dist:,.0f} km, Azimuth: {azm:.0f}°\n\n"
            "This path may not have enough WSPR/RBN/Contest observations. "
            "Try a nearby 4-char grid or a different source."
        )

    lines = [
        f"# Path Analysis: {tx_valid} → {rx_valid}\n",
        f"**Distance**: {dist:,.0f} km | **Azimuth**: {azm:.0f}° | "
        f"**Reverse**: {(azm + 180) % 360:.0f}°\n",
    ]

    # Best band/hour combos ranked by spot count
    band_hour = {}
    band_totals: dict[int, dict] = {}
    month_totals: dict[int, int] = {}
    source_totals: dict[str, int] = {}
    total_spots = 0

    for sig in sigs:
        b = sig.get("band", 0)
        h = sig.get("hour", 0)
        m = sig.get("month", 0)
        spots = sig.get("spot_count", 0)
        snr = sig.get("median_snr", 0)
        rel = sig.get("reliability", 0)
        src = sig.get("source", "?")

        total_spots += spots

        key = (b, h)
        if key not in band_hour:
            band_hour[key] = {"spots": 0, "snr_w": 0.0, "rel_max": 0.0}
        band_hour[key]["spots"] += spots
        band_hour[key]["snr_w"] += snr * spots
        band_hour[key]["rel_max"] = max(band_hour[key]["rel_max"], rel)

        if b not in band_totals:
            band_totals[b] = {"spots": 0, "sigs": 0}
        band_totals[b]["spots"] += spots
        band_totals[b]["sigs"] += 1

        month_totals[m] = month_totals.get(m, 0) + spots
        source_totals[src] = source_totals.get(src, 0) + spots

    lines.append(f"**Total observations**: {_format_number(total_spots)} spots across {len(sigs)} signatures\n")

    # Source breakdown
    lines.append("## Sources")
    for src, spots in sorted(source_totals.items(), key=lambda x: -x[1]):
        lines.append(f"- **{src}**: {_format_number(spots)} spots")
    lines.append("")

    # Band summary
    lines.append("## Band Summary")
    lines.append("| Band | Signatures | Total Spots |")
    lines.append("|------|-----------|-------------|")
    for b in sorted(band_totals.keys()):
        bt = band_totals[b]
        lines.append(
            f"| {band_name(b)} | {_format_number(bt['sigs'])} | {_format_number(bt['spots'])} |"
        )
    lines.append("")

    # Top 15 band/hour combinations
    ranked = sorted(band_hour.items(), key=lambda x: x[1]["spots"], reverse=True)[:15]
    lines.append("## Best Band/Hour Combinations (by spots)")
    lines.append("| Band | Hour | Spots | Avg SNR | Best Reliability |")
    lines.append("|------|------|-------|---------|-----------------|")
    for (b, h), stats in ranked:
        avg_snr = stats["snr_w"] / stats["spots"] if stats["spots"] > 0 else 0
        lines.append(
            f"| {band_name(b).split(' ')[0]} | {h:02d}z | "
            f"{_format_number(stats['spots'])} | {avg_snr:.1f} dB | {stats['rel_max']:.3f} |"
        )
    lines.append("")

    # Seasonal pattern
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    lines.append("## Seasonal Pattern")
    lines.append("| Month | Spots |")
    lines.append("|-------|-------|")
    for m in range(1, 13):
        spots = month_totals.get(m, 0)
        lines.append(f"| {month_names[m]} | {_format_number(spots)} |")

    return "\n".join(lines)


# ── Tool 5: solar_correlation ───────────────────────────────────────────────

@mcp.tool()
def solar_correlation(
    band: int,
    tx_grid: str | None = None,
    rx_grid: str | None = None,
    source: str = "wspr",
) -> str:
    """How does solar flux (SFI) affect propagation on a specific band?

    Groups signatures by SFI bracket and shows spot counts, average SNR,
    and reliability for each bracket. Higher SFI generally helps HF bands
    above 30m (F-layer ionization) but hurts bands below 30m (D-layer
    absorption).

    Args:
        band: ADIF band ID (102-111)
        tx_grid: Optional TX grid to filter (omit for global)
        rx_grid: Optional RX grid to filter (omit for global)
        source: Dataset source (default: "wspr")
    """
    mgr = _require_db()

    brackets = mgr.query_solar_correlation(band, tx_grid, rx_grid, source)

    scope = "Global"
    if tx_grid and rx_grid:
        scope = f"{tx_grid.upper()} → {rx_grid.upper()}"
    elif tx_grid:
        scope = f"TX: {tx_grid.upper()}"
    elif rx_grid:
        scope = f"RX: {rx_grid.upper()}"

    lines = [
        f"# SFI Correlation: {band_name(band)} ({scope})\n",
        "| SFI Bracket | Signatures | Total Spots | Avg SNR (dB) | Avg Reliability |",
        "|-------------|-----------|-------------|--------------|-----------------|",
    ]

    for b in brackets:
        snr_str = f"{b['avg_snr']:.1f}" if b["avg_snr"] is not None else "—"
        rel_str = f"{b['avg_reliability']:.3f}" if b["avg_reliability"] is not None else "—"
        lines.append(
            f"| {b['sfi_bracket']} | {_format_number(b['signatures'])} "
            f"| {_format_number(b['total_spots'])} | {snr_str} | {rel_str} |"
        )

    lines.append("\n*Higher SFI generally helps bands above 30m (10-20m) due to F-layer "
                 "ionization, but increases D-layer absorption on bands below 30m (40-160m).*")

    return "\n".join(lines)


# ── Tool 6: grid_info ───────────────────────────────────────────────────────

@mcp.tool()
def grid_info(
    grid: str,
    hour: int | None = None,
    month: int | None = None,
    day_of_year: int | None = None,
) -> str:
    """Decode a Maidenhead grid to lat/lon and compute solar elevation.

    Converts a 4-char or 6-char Maidenhead grid square to geographic
    coordinates. If hour is provided, computes solar elevation angle
    with day/twilight/night classification.

    Args:
        grid: Maidenhead grid (4-char like "DN13" or 6-char like "DN13la")
        hour: UTC hour (0-23) for solar elevation calculation
        month: Month (1-12) for solar elevation (used if day_of_year not given)
        day_of_year: Day of year (1-366) for precise solar elevation
    """
    valid = validate_grid(grid)
    if not valid:
        return f"Invalid Maidenhead grid: '{grid}'. Expected format: 2 letters + 2 digits (+ optional 2 letters)."

    lat, lon = grid_lookup.get(valid)

    lines = [
        f"# Grid Info: {valid}\n",
        f"**Latitude**: {lat:.2f}° {'N' if lat >= 0 else 'S'}",
        f"**Longitude**: {lon:.2f}° {'E' if lon >= 0 else 'W'}",
        f"**Field**: {valid[:2]} | **Square**: {valid[:4]}",
    ]

    if hour is not None:
        doy = day_of_year if day_of_year else (month_to_mid_doy(month) if month else 172)
        elev = solar_elevation_deg(lat, lon, hour + 0.5, doy)
        cls = classify_solar(elev)
        month_label = ""
        if month and not day_of_year:
            month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            month_label = f" in {month_names[month]}"
        elif day_of_year:
            month_label = f" (DOY {doy})"
        else:
            month_label = " (mid-June default)"

        lines.append(f"\n## Solar Elevation at {hour:02d}z{month_label}")
        lines.append(f"**Elevation**: {elev:+.1f}°")
        lines.append(f"**Classification**: {cls}")

        if hour is not None and not day_of_year and not month:
            lines.append("\n*Tip: Add month parameter for seasonal accuracy.*")

    return "\n".join(lines)


# ── Tool 7: compare_sources ────────────────────────────────────────────────

@mcp.tool()
def compare_sources(
    tx_grid: str,
    rx_grid: str,
    band: int,
    hour: int | None = None,
) -> str:
    """Cross-dataset comparison for a path/band.

    Shows side-by-side data from all available sources (WSPR, RBN,
    Contest, DXpedition, PSKR) for the same path. Useful for validating
    observations across independent measurement systems.

    Args:
        tx_grid: Transmitter 4-char grid
        rx_grid: Receiver 4-char grid
        band: ADIF band ID (102-111)
        hour: Specific UTC hour (omit for all hours)
    """
    mgr = _require_db()

    tx_valid = validate_grid(tx_grid)
    rx_valid = validate_grid(rx_grid)
    if not tx_valid or not rx_valid:
        return f"Invalid grid: tx={tx_grid}, rx={rx_grid}."

    rows = mgr.query_compare_sources(tx_valid, rx_valid, band, hour)

    if not rows:
        return (
            f"No data found for {tx_valid} → {rx_valid} on {band_name(band)}"
            + (f" at {hour:02d}z" if hour is not None else "")
            + "."
        )

    hour_label = f" at {hour:02d}z" if hour is not None else ""
    lines = [
        f"# Source Comparison: {tx_valid} → {rx_valid}, {band_name(band)}{hour_label}\n",
        "| Source | Hour | SNR (dB) | Spots | Reliability | SFI | Kp |",
        "|--------|------|----------|-------|-------------|-----|----|",
    ]

    for r in rows:
        lines.append(
            f"| {r['source']} | {r['hour']:02d}z | {r['median_snr']:.1f} "
            f"| {_format_number(r['spot_count'])} | {r['reliability']:.3f} "
            f"| {r['avg_sfi']:.0f} | {r['avg_kp']:.1f} |"
        )

    # Summary by source
    source_stats: dict[str, dict] = {}
    for r in rows:
        src = r["source"]
        if src not in source_stats:
            source_stats[src] = {"spots": 0, "hours": set()}
        source_stats[src]["spots"] += r["spot_count"]
        source_stats[src]["hours"].add(r["hour"])

    lines.append("\n## Summary by Source")
    for src, stats in sorted(source_stats.items()):
        lines.append(
            f"- **{src}**: {_format_number(stats['spots'])} spots across "
            f"{len(stats['hours'])} hours"
        )

    return "\n".join(lines)


# ── Tool 8: dark_hour_analysis ──────────────────────────────────────────────

@mcp.tool()
def dark_hour_analysis(
    band: int,
    hour: int,
    month: int | None = None,
    source: str = "pskr",
    min_spots: int = 10,
) -> str:
    """Classify propagation paths by solar geometry — both-day, cross-terminator, or both-dark.

    For a given band and hour, retrieves paths and classifies each by the
    solar elevation at both endpoints. Useful for identifying physically
    anomalous paths (e.g., 10m both-dark propagation).

    Args:
        band: ADIF band ID (102-111)
        hour: UTC hour (0-23)
        month: Month (1-12) for solar geometry (default: all months aggregated)
        source: Dataset source (default: "pskr" for most recent data)
        min_spots: Minimum spot count filter (default: 10)
    """
    mgr = _require_db()

    # Get paths for this band
    all_paths = mgr.query_dark_paths(band, source, min_spots)

    # Filter to requested hour (and month if given)
    paths = [
        p for p in all_paths
        if p["hour"] == hour and (month is None or p["month"] == month)
    ]

    if not paths:
        return f"No paths found for {band_name(band)} at {hour:02d}z" + (f" in month {month}" if month else "") + "."

    # Classify each path
    categories: dict[str, list] = {
        "both_day": [], "cross_terminator": [],
        "both_twilight": [], "both_dark": [],
    }

    for p in paths:
        tx_lat, tx_lon = grid_lookup.get(p["tx_grid_4"])
        rx_lat, rx_lon = grid_lookup.get(p["rx_grid_4"])
        doy = month_to_mid_doy(p["month"]) if p.get("month") else 172
        cls, tx_elev, rx_elev = classify_path_solar(
            tx_lat, tx_lon, rx_lat, rx_lon, hour + 0.5, doy,
        )
        entry = {
            **p,
            "tx_elev": tx_elev, "rx_elev": rx_elev,
            "distance_km": haversine_km(tx_lat, tx_lon, rx_lat, rx_lon),
        }
        categories[cls].append(entry)

    month_label = f" (month {month})" if month else " (all months)"
    lines = [
        f"# Dark Hour Analysis: {band_name(band)} at {hour:02d}z{month_label}\n",
        f"**Total paths**: {len(paths)} | **Source**: {source}\n",
        "## Classification Summary",
        "| Category | Paths | Total Spots | Avg SNR |",
        "|----------|-------|-------------|---------|",
    ]

    for cat_name, cat_paths in categories.items():
        if cat_paths:
            total_spots = sum(p["spot_count"] for p in cat_paths)
            total_snr = sum(p["median_snr"] * p["spot_count"] for p in cat_paths)
            avg_snr = total_snr / total_spots if total_spots > 0 else 0
            lines.append(
                f"| {cat_name} | {len(cat_paths)} | "
                f"{_format_number(total_spots)} | {avg_snr:.1f} dB |"
            )
        else:
            lines.append(f"| {cat_name} | 0 | 0 | — |")

    # Show both-dark paths in detail (the interesting ones)
    dark = categories["both_dark"]
    if dark:
        dark.sort(key=lambda x: x["spot_count"], reverse=True)
        lines.append(f"\n## Both-Dark Paths ({len(dark)} found)")
        lines.append("| TX | RX | Month | SNR | Spots | TX Elev | RX Elev | Distance |")
        lines.append("|----|----| ------|-----|-------|---------|---------|----------|")
        for p in dark[:20]:
            lines.append(
                f"| {p['tx_grid_4']} | {p['rx_grid_4']} | {p.get('month', '?')} "
                f"| {p['median_snr']:.1f} | {_format_number(p['spot_count'])} "
                f"| {p['tx_elev']:+.1f}° | {p['rx_elev']:+.1f}° "
                f"| {p['distance_km']:,.0f} km |"
            )

    return "\n".join(lines)


# ── Tool 9: solar_history ──────────────────────────────────────────────────

@mcp.tool()
def solar_history(
    start_date: str,
    end_date: str,
    resolution: str = "daily",
) -> str:
    """Query historical solar indices (SFI, SSN, Kp, Ap) for a date range.

    Returns solar flux, sunspot number, and geomagnetic indices from the
    IONIS dataset (GFZ Potsdam and NOAA SWPC, 2000-2026). For live
    current conditions, use solar-mcp's solar_conditions tool instead.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        resolution: "daily" (default) or "3hour" for Kp resolution
    """
    mgr = _require_db()
    if not mgr.is_available("solar"):
        return "Solar indices dataset not available. Download solar_indices.sqlite from SourceForge."

    rows = mgr.query_solar_conditions(start_date, end_date, resolution)

    if not rows:
        return f"No solar data found for {start_date} to {end_date}."

    lines = [f"# Solar Conditions: {start_date} to {end_date}\n"]

    if resolution == "3hour":
        lines.append("| Date | Time | SFI | Adj SFI | SSN | Kp | Ap |")
        lines.append("|------|------|-----|---------|-----|----|----|")
        for r in rows[:200]:
            lines.append(
                f"| {r.get('date', '')} | {r.get('timestamp', '')} "
                f"| {r.get('observed_flux', 0):.1f} | {r.get('adjusted_flux', 0):.1f} "
                f"| {r.get('ssn', 0):.0f} | {r.get('kp_index', 0):.2f} "
                f"| {r.get('ap_index', 0):.0f} |"
            )
    else:
        lines.append("| Date | SFI | SSN | Avg Kp | Max Kp | Avg Ap |")
        lines.append("|------|-----|-----|--------|--------|--------|")
        for r in rows[:200]:
            lines.append(
                f"| {r.get('date', '')} | {r.get('observed_flux', 0):.1f} "
                f"| {r.get('ssn', 0):.0f} | {r.get('avg_kp', 0):.2f} "
                f"| {r.get('max_kp', 0):.2f} | {r.get('avg_ap', 0):.0f} |"
            )

    if len(rows) > 200:
        lines.append(f"\n*Showing 200 of {len(rows)} rows. Narrow the date range for full data.*")

    return "\n".join(lines)


# ── Tool 10: band_summary ──────────────────────────────────────────────────

@mcp.tool()
def band_summary(
    band: int,
    source: str = "all",
) -> str:
    """Overview of a band across all hours and available sources.

    Shows total signatures and spots, hour distribution, top grid pairs,
    SFI range observed, and distance distribution.

    Args:
        band: ADIF band ID (102-111)
        source: Dataset source or "all"
    """
    mgr = _require_db()
    stats = mgr.query_band_global(band, source)

    if stats["total_signatures"] == 0:
        return f"No data found for {band_name(band)}."

    lines = [
        f"# Band Summary: {band_name(band)}\n",
        f"**Total signatures**: {_format_number(stats['total_signatures'])}",
        f"**Total spots**: {_format_number(stats['total_spots'])}",
    ]

    if stats["sfi_range"][0] is not None:
        lines.append(
            f"**SFI range**: {stats['sfi_range'][0]:.0f} – {stats['sfi_range'][1]:.0f}"
        )
    if stats["distance_range_km"][0] is not None:
        lines.append(
            f"**Distance range**: {_format_number(stats['distance_range_km'][0])} – "
            f"{_format_number(stats['distance_range_km'][1])} km"
        )

    # Hour distribution
    lines.append("\n## Hour Distribution (spots by UTC hour)")
    lines.append("| Hour | Spots |")
    lines.append("|------|-------|")
    hour_dist = stats["hour_distribution"]
    max_spots = max(hour_dist.values()) if hour_dist else 1
    for h in range(24):
        spots = hour_dist.get(h, 0)
        bar_len = int(20 * spots / max_spots) if max_spots > 0 else 0
        bar = "█" * bar_len
        lines.append(f"| {h:02d}z | {_format_number(spots)} {bar} |")

    # Top grid pairs
    if stats["top_grid_pairs"]:
        lines.append("\n## Top Grid Pairs")
        lines.append("| TX | RX | Spots | Source |")
        lines.append("|----|----| ------|--------|")
        for pair in stats["top_grid_pairs"]:
            lines.append(
                f"| {pair['tx']} | {pair['rx']} | {_format_number(pair['spots'])} | {pair['source']} |"
            )

    return "\n".join(lines)


# ── Tool 11: current_conditions ────────────────────────────────────────────

@mcp.tool()
def current_conditions(
    qth_grid: str | None = None,
) -> str:
    """Live space weather and band conditions — like a morning propagation forecast.

    Fetches real-time solar flux (SFI), Kp index, solar wind data, and
    active alerts from NOAA SWPC. Generates an operator-friendly band
    outlook based on current conditions and historical propagation patterns.

    Perfect for: "What bands should I use today?" or "Is it worth setting
    up for POTA/SOTA on 10m?"

    Args:
        qth_grid: Your 4-char Maidenhead grid (e.g., "DN13") for
                  solar elevation context. Optional but recommended.
    """
    import datetime

    cond = fetch_current_conditions()
    now = datetime.datetime.now(datetime.timezone.utc)

    lines = [
        f"# Propagation Report — {now.strftime('%B %d, %Y %H:%M')} UTC\n",
    ]

    # Solar conditions
    lines.append("## Solar Conditions\n")

    if cond.sfi is not None:
        sfi_class = classify_sfi(cond.sfi)
        lines.append(f"**SFI**: {cond.sfi:.0f} ({sfi_class})")
    else:
        lines.append("**SFI**: unavailable")

    if cond.kp is not None:
        kp_class = classify_kp(cond.kp)
        lines.append(f"**Kp**: {cond.kp:.1f} ({kp_class})")
    else:
        lines.append("**Kp**: unavailable")

    # Solar wind
    wind_parts = []
    if cond.bz is not None:
        bz_class = classify_bz(cond.bz)
        wind_parts.append(f"Bz: {cond.bz:+.1f} nT ({bz_class})")
    if cond.wind_speed is not None:
        wind_parts.append(f"Speed: {cond.wind_speed:.0f} km/s")
    if cond.wind_density is not None:
        wind_parts.append(f"Density: {cond.wind_density:.1f} p/cm³")

    if wind_parts:
        lines.append(f"**Solar Wind**: {' | '.join(wind_parts)}")

    # QTH solar elevation
    if qth_grid:
        valid = validate_grid(qth_grid)
        if valid:
            lat, lon = grid_lookup.get(valid)
            hour = now.hour
            doy = now.timetuple().tm_yday
            elev = solar_elevation_deg(lat, lon, hour + now.minute / 60, doy)
            cls = classify_solar(elev)
            lines.append(f"\n**Your QTH** ({valid}): Solar elevation {elev:+.1f}° — {cls}")

    # Band outlook
    if cond.sfi is not None and cond.kp is not None:
        outlook = band_outlook(cond.sfi, cond.kp)

        lines.append("\n## Band Outlook\n")
        lines.append("| Band | Outlook |")
        lines.append("|------|---------|")

        # Order: high bands first (most SFI-dependent)
        band_order = ["10m", "12m", "15m", "17m", "20m", "30m", "40m", "80m", "160m"]
        for b in band_order:
            if b in outlook:
                lines.append(f"| {b} | {outlook[b]} |")

        # POTA/SOTA recommendation
        lines.append("\n## Portable / POTA / SOTA\n")
        if cond.sfi >= 150 and cond.kp < 4:
            lines.append("**Best portable bands**: 20m (reliable all day), 15m (excellent), 10m (open)")
            lines.append("**Strategy**: Start on 15m/10m, fall back to 20m if they close")
            lines.append("**Modes**: SSB for fast QSO rate — bands are wide open. "
                         "CW for DX pileups. FT8 unnecessary but works on 10m for weak openings.")
        elif cond.sfi >= 120 and cond.kp < 4:
            lines.append("**Best portable bands**: 20m (primary), 15m/17m (good)")
            lines.append("**Strategy**: 20m is your workhorse, try 15m for DX midday")
            lines.append("**Modes**: SSB on 20m/15m for quick QSO rate. "
                         "CW for DX and weaker paths. FT8 on 10m/12m where openings are short.")
        elif cond.sfi >= 90 and cond.kp < 4:
            lines.append("**Best portable bands**: 20m (primary), 40m (reliable)")
            lines.append("**Strategy**: 20m for DX, 40m for regional. 15m worth a try midday.")
            lines.append("**Modes**: CW/SSB on 20m/40m. "
                         "FT8 on 15m and above — marginal openings favor digital. "
                         "SSB on 40m for regional park-to-park.")
        elif cond.kp >= 5:
            lines.append("**Geomagnetic storm active** — conditions degraded on all bands")
            lines.append("**Strategy**: 40m/80m may be more stable than HF. Wait for Kp to drop.")
            lines.append("**Modes**: FT8 primary — signals will be weak and fading. "
                         "CW as backup. SSB only on 40m/80m if signals are strong enough.")
        else:
            lines.append("**Best portable bands**: 40m (primary), 20m (daytime), 80m (evening)")
            lines.append("**Strategy**: Low SFI favors lower bands. 20m still works daytime.")
            lines.append("**Modes**: FT8 on 20m and above — low ionization means weak signals. "
                         "CW/SSB on 40m/80m where conditions are more reliable. "
                         "FT8 on 15m for any sporadic openings.")

    # Active alerts
    if cond.alerts:
        lines.append("\n## Active Alerts\n")
        seen = set()
        for alert in cond.alerts[:10]:
            if isinstance(alert, dict):
                msg = alert.get("message", "")
                if msg:
                    # Extract the WATCH/WARNING/ALERT line (the meaningful one)
                    summary = ""
                    for line in msg.strip().split("\n"):
                        stripped = line.strip()
                        for prefix in ("WATCH:", "WARNING:", "ALERT:", "SUMMARY:", "CANCEL"):
                            if stripped.startswith(prefix):
                                summary = stripped[:120]
                                break
                        if summary:
                            break
                    if not summary:
                        summary = msg.strip().split("\n")[0][:120]
                    if summary not in seen:
                        seen.add(summary)
                        ts = alert.get("issue_datetime", "")[:16]
                        lines.append(f"- [{ts}] {summary}")
                    if len(seen) >= 5:
                        break

    # Fetch errors (if any)
    if cond.errors:
        lines.append(f"\n*Note: Some data unavailable — {', '.join(cond.errors)}*")

    lines.append("\n---")
    lines.append("*Live data from NOAA Space Weather Prediction Center. Cached 15 min.*")

    return "\n".join(lines)


# ── Server Startup ──────────────────────────────────────────────────────────

def _resolve_data_dir(cli_arg: str) -> str:
    """Resolve data directory: CLI arg > env var > default location."""
    # 1. Explicit CLI arg
    if cli_arg:
        return cli_arg

    # 2. Environment variable
    env_dir = os.environ.get("IONIS_DATA_DIR", "")
    if env_dir:
        return env_dir

    # 3. Platform default
    return default_data_dir()


def main():
    """Entry point for ionis-mcp server."""
    default_dir = default_data_dir()

    parser = argparse.ArgumentParser(
        description="IONIS MCP Server — HF Propagation Analytics",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help=f"Path to IONIS dataset directory (default: $IONIS_DATA_DIR or {default_dir})",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    args = parser.parse_args()

    data_dir = _resolve_data_dir(args.data_dir)

    if not os.path.isdir(data_dir):
        print(
            f"Error: Data directory not found: {data_dir}\n\n"
            "Download datasets first:\n"
            "  ionis-download --bundle minimal\n\n"
            "Or specify a custom location:\n"
            f"  ionis-mcp --data-dir /path/to/data\n"
            f"  export IONIS_DATA_DIR=/path/to/data",
            file=sys.stderr,
        )
        sys.exit(1)

    # Initialize database manager
    global db
    db = DatabaseManager(data_dir=data_dir)
    datasets = db.discover()

    if not datasets:
        print(
            f"Warning: No SQLite datasets found in {data_dir}",
            file=sys.stderr,
        )
    else:
        print(
            f"IONIS MCP: Found {len(datasets)} datasets in {data_dir}",
            file=sys.stderr,
        )
        for ds in datasets:
            rows_str = _format_number(ds.row_count) if ds.row_count >= 0 else "error"
            print(f"  {ds.key}: {rows_str} rows ({ds.file_size_mb:.1f} MB)", file=sys.stderr)

    # Load grid lookup into memory if available
    if db.is_available("grids"):
        grid_db_path = os.path.join(data_dir, "tools/grid-lookup/grid_lookup.sqlite")
        count = grid_lookup.load_from_sqlite(grid_db_path)
        print(f"  Grid lookup: {_format_number(count)} grids loaded into memory", file=sys.stderr)

    # Run server
    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http", port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
