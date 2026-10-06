"""SQLite database manager for IONIS datasets.

Auto-discovers SQLite files under IONIS_DATA_DIR, opens read-only
connections, and provides parameterized query helpers.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# Dataset registry: key → (subpath, table_name, description)
DATASET_REGISTRY = {
    "wspr": (
        "propagation/wspr-signatures/wspr_signatures_v2.sqlite",
        "wspr_signatures_v2",
        "WSPR automated beacon signatures (93.6M rows, 2008-2026)",
    ),
    "rbn": (
        "propagation/rbn-signatures/rbn_signatures.sqlite",
        "rbn_signatures",
        "Reverse Beacon Network CW/RTTY signatures (67.3M rows, 2009-2026)",
    ),
    "contest": (
        "propagation/contest-signatures/contest_signatures.sqlite",
        "contest_signatures",
        "CQ contest SSB/RTTY signatures (5.7M rows, 2005-2025)",
    ),
    "dxpedition": (
        "propagation/dxpedition-signatures/dxpedition_signatures.sqlite",
        "dxpedition_signatures",
        "DXpedition rare-grid signatures (260K rows, 2009-2025)",
    ),
    "pskr": (
        "propagation/pskr-signatures/pskr_signatures.sqlite",
        "pskr_signatures",
        "PSK Reporter FT8/WSPR signatures (8.4M rows, Feb 2026+)",
    ),
    "solar": (
        "solar/solar-indices/solar_indices.sqlite",
        "solar_indices",
        "Solar indices — SFI, SSN, Kp, Ap (76.7K rows, 2000-2026)",
    ),
    "dscovr": (
        "solar/dscovr/dscovr_l1.sqlite",
        "dscovr_l1",
        "DSCOVR L1 solar wind — Bz, speed, density (23K rows, Feb 2026+)",
    ),
    "grids": (
        "tools/grid-lookup/grid_lookup.sqlite",
        "grid_lookup",
        "Maidenhead grid → lat/lon lookup (31.7K grids)",
    ),
    "balloons": (
        "tools/balloon-callsigns/balloon_callsigns_v2.sqlite",
        "balloon_callsigns",
        "Known balloon/telemetry callsigns (1.5K entries)",
    ),
}

# Signature datasets (all share the same 13-column schema)
SIGNATURE_SOURCES = ["wspr", "rbn", "contest", "dxpedition", "pskr"]

# Plausible 10.7 cm solar flux (#17). Since 2000 the daily value has stayed between 64 and
# about 340. The published datasets also carry 0 and single-day spikes of up to 938.6
# (2011-03-07, between 142 and 167), and every signature averaged over such a day inherits
# them. Analyses treat an avg_sfi outside this range as unknown and say how many rows that was.
SFI_MIN = 50.0
SFI_MAX = 400.0


def plausible_sfi(value: float | None) -> bool:
    """True when an SFI value is within the plausible range."""
    return value is not None and SFI_MIN <= value <= SFI_MAX


SIGNATURE_COLUMNS = [
    "tx_grid_4", "rx_grid_4", "band", "hour", "month",
    "median_snr", "spot_count", "snr_std", "reliability",
    "avg_sfi", "avg_kp", "avg_distance", "avg_azimuth",
]


@dataclass
class DatasetInfo:
    """Metadata about an available dataset."""
    key: str
    table: str
    description: str
    path: str
    row_count: int = 0
    file_size_mb: float = 0.0


@dataclass
class DatabaseManager:
    """Manages read-only SQLite connections to IONIS datasets."""

    data_dir: str
    _connections: dict[str, sqlite3.Connection] = field(default_factory=dict, init=False, repr=False)
    _datasets: dict[str, DatasetInfo] = field(default_factory=dict, init=False, repr=False)

    def discover(self) -> list[DatasetInfo]:
        """Scan data_dir for available datasets. Returns list of found datasets."""
        results = []
        for key, (subpath, table, desc) in DATASET_REGISTRY.items():
            full_path = os.path.join(self.data_dir, subpath)
            if os.path.isfile(full_path):
                size_mb = os.path.getsize(full_path) / (1024 * 1024)
                info = DatasetInfo(
                    key=key, table=table, description=desc,
                    path=full_path, file_size_mb=round(size_mb, 1),
                )
                # Get row count
                try:
                    conn = self._get_connection(key)
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    info.row_count = row[0] if row else 0
                except Exception:
                    info.row_count = -1
                self._datasets[key] = info
                results.append(info)
        return results

    def _get_connection(self, key: str) -> sqlite3.Connection:
        """Get or create a read-only connection for a dataset."""
        if key in self._connections:
            return self._connections[key]

        if key not in DATASET_REGISTRY:
            raise KeyError(f"Unknown dataset: {key}")

        subpath = DATASET_REGISTRY[key][0]
        full_path = os.path.join(self.data_dir, subpath)

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Dataset not found: {full_path}")

        conn = sqlite3.connect(f"file:{full_path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._connections[key] = conn
        return conn

    def is_available(self, key: str) -> bool:
        """Check if a dataset is available."""
        return key in self._datasets

    def available_sources(self) -> list[str]:
        """Return list of available signature source keys."""
        return [k for k in SIGNATURE_SOURCES if k in self._datasets]

    def query_signatures(
        self,
        source: str = "all",
        band: int | None = None,
        tx_grid: str | None = None,
        rx_grid: str | None = None,
        hour: int | None = None,
        month: int | None = None,
        min_spots: int = 5,
        limit: int = 100,
    ) -> list[dict]:
        """Query signature tables with filters. Returns list of dicts."""
        sources = self._resolve_sources(source)
        if not sources:
            return []

        results = []
        for src in sources:
            try:
                rows = self._query_single_source(
                    src, band=band, tx_grid=tx_grid, rx_grid=rx_grid,
                    hour=hour, month=month, min_spots=min_spots,
                    limit=limit, extra_select=f"'{src}' as source",
                )
                results.extend(rows)
            except (FileNotFoundError, KeyError):
                continue

        # Sort by spot_count descending, trim to limit
        results.sort(key=lambda r: r.get("spot_count", 0), reverse=True)
        return results[:limit]

    def query_band_openings(
        self,
        tx_grid: str,
        rx_grid: str,
        band: int,
        source: str = "all",
    ) -> list[dict]:
        """Get hourly propagation profile for a path+band."""
        sources = self._resolve_sources(source)
        if not sources:
            return []

        # Aggregate across sources by hour
        hourly: dict[int, dict] = {}
        for src in sources:
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]
                rows = conn.execute(
                    f"SELECT hour, median_snr, spot_count, reliability, avg_sfi "
                    f"FROM {table} "
                    f"WHERE tx_grid_4 = ? AND rx_grid_4 = ? AND band = ? "
                    f"ORDER BY hour",
                    (tx_grid.upper(), rx_grid.upper(), band),
                ).fetchall()
                for row in rows:
                    h = row[0]
                    if h not in hourly:
                        hourly[h] = {
                            "hour": h, "median_snr": 0.0, "total_spots": 0,
                            "reliability": 0.0, "avg_sfi": 0.0, "sources": [],
                            "_snr_weighted": 0.0, "_sfi_weighted": 0.0,
                            "_sfi_spots": 0, "_rel_max": 0.0,
                        }
                    entry = hourly[h]
                    spots = row[2]
                    entry["total_spots"] += spots
                    entry["_snr_weighted"] += row[1] * spots
                    if plausible_sfi(row[4]):
                        entry["_sfi_weighted"] += row[4] * spots
                        entry["_sfi_spots"] += spots
                    entry["_rel_max"] = max(entry["_rel_max"], row[3])
                    entry["sources"].append(src)
            except (FileNotFoundError, KeyError):
                continue

        # Compute weighted averages
        result = []
        for h in range(24):
            if h in hourly:
                entry = hourly[h]
                total = entry["total_spots"]
                entry["median_snr"] = round(entry["_snr_weighted"] / total, 1) if total > 0 else 0.0
                sfi_spots = entry["_sfi_spots"]
                entry["avg_sfi"] = round(entry["_sfi_weighted"] / sfi_spots, 1) if sfi_spots > 0 else None
                entry["reliability"] = round(entry["_rel_max"], 3)
                # Clean up internal fields
                del entry["_snr_weighted"], entry["_sfi_weighted"], entry["_sfi_spots"], entry["_rel_max"]
                result.append(entry)
            else:
                result.append({
                    "hour": h, "median_snr": None, "total_spots": 0,
                    "reliability": 0.0, "avg_sfi": None, "sources": [],
                })
        return result

    def query_path_summary(
        self,
        tx_grid: str,
        rx_grid: str,
        source: str = "all",
    ) -> list[dict]:
        """Get all signatures for a grid pair across all bands/hours."""
        sources = self._resolve_sources(source)
        results = []
        for src in sources:
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]
                rows = conn.execute(
                    f"SELECT *, '{src}' as source FROM {table} "
                    f"WHERE tx_grid_4 = ? AND rx_grid_4 = ? "
                    f"ORDER BY band, hour",
                    (tx_grid.upper(), rx_grid.upper()),
                ).fetchall()
                results.extend([dict(r) for r in rows])
            except (FileNotFoundError, KeyError):
                continue
        return results

    def query_solar_conditions(
        self,
        start_date: str,
        end_date: str,
        resolution: str = "daily",
    ) -> list[dict]:
        """Query historical solar indices."""
        if not self.is_available("solar"):
            return []
        conn = self._get_connection("solar")

        if resolution == "3hour":
            rows = conn.execute(
                "SELECT date, timestamp, observed_flux, adjusted_flux, ssn, "
                "kp_index, ap_index FROM solar_indices "
                "WHERE date >= ? AND date <= ? ORDER BY timestamp",
                (start_date, end_date),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, "
                "AVG(observed_flux) as observed_flux, "
                "AVG(adjusted_flux) as adjusted_flux, "
                "AVG(ssn) as ssn, "
                "AVG(kp_index) as avg_kp, "
                "MAX(kp_index) as max_kp, "
                "AVG(ap_index) as avg_ap "
                "FROM solar_indices "
                "WHERE date >= ? AND date <= ? "
                "GROUP BY date ORDER BY date",
                (start_date, end_date),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_band_global(
        self,
        band: int,
        source: str = "all",
    ) -> dict:
        """Get global statistics for a band across all sources."""
        sources = self._resolve_sources(source)
        total_sigs = 0
        total_spots = 0
        hour_dist: dict[int, int] = {}
        top_pairs: list[tuple] = []
        sfi_range = [999.0, 0.0]
        sfi_excluded = 0
        dist_range = [99999, 0]

        for src in sources:
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]

                # Totals
                row = conn.execute(
                    f"SELECT COUNT(*), SUM(spot_count), "
                    f"MIN(CASE WHEN avg_sfi BETWEEN ? AND ? THEN avg_sfi END), "
                    f"MAX(CASE WHEN avg_sfi BETWEEN ? AND ? THEN avg_sfi END), "
                    f"MIN(avg_distance), MAX(avg_distance), "
                    f"SUM(CASE WHEN avg_sfi BETWEEN ? AND ? THEN 0 ELSE 1 END) "
                    f"FROM {table} WHERE band = ?",
                    (SFI_MIN, SFI_MAX) * 3 + (band,),
                ).fetchone()
                if row and row[0]:
                    total_sigs += row[0]
                    total_spots += row[1] or 0
                    if row[2] and row[2] < sfi_range[0]:
                        sfi_range[0] = row[2]
                    if row[3] and row[3] > sfi_range[1]:
                        sfi_range[1] = row[3]
                    if row[4] and row[4] < dist_range[0]:
                        dist_range[0] = row[4]
                    if row[5] and row[5] > dist_range[1]:
                        dist_range[1] = row[5]
                    sfi_excluded += row[6] or 0

                # Hour distribution
                hours = conn.execute(
                    f"SELECT hour, SUM(spot_count) FROM {table} "
                    f"WHERE band = ? GROUP BY hour", (band,)
                ).fetchall()
                for h, cnt in hours:
                    hour_dist[h] = hour_dist.get(h, 0) + (cnt or 0)

                # Top pairs by spot count
                pairs = conn.execute(
                    f"SELECT tx_grid_4, rx_grid_4, SUM(spot_count) as total "
                    f"FROM {table} WHERE band = ? "
                    f"GROUP BY tx_grid_4, rx_grid_4 ORDER BY total DESC LIMIT 10",
                    (band,),
                ).fetchall()
                top_pairs.extend([(p[0], p[1], p[2], src) for p in pairs])
            except (FileNotFoundError, KeyError):
                continue

        # Sort top pairs
        top_pairs.sort(key=lambda x: x[2], reverse=True)

        return {
            "total_signatures": total_sigs,
            "total_spots": total_spots,
            "hour_distribution": {h: hour_dist.get(h, 0) for h in range(24)},
            "top_grid_pairs": [
                {"tx": p[0], "rx": p[1], "spots": p[2], "source": p[3]}
                for p in top_pairs[:10]
            ],
            "sfi_range": sfi_range if sfi_range[0] < 999 else [None, None],
            "sfi_excluded": sfi_excluded,
            "distance_range_km": dist_range if dist_range[0] < 99999 else [None, None],
        }

    def query_solar_correlation(
        self,
        band: int,
        tx_grid: str | None = None,
        rx_grid: str | None = None,
        source: str = "wspr",
    ) -> list[dict]:
        """Group signatures by SFI bracket and compute stats."""
        sources = self._resolve_sources(source)

        # SFI brackets
        # The last bracket includes SFI_MAX; outside SFI_MIN..SFI_MAX is unknown (#17).
        brackets = [
            (SFI_MIN, 80, "50-80"),
            (80, 100, "80-100"),
            (100, 120, "100-120"),
            (120, 150, "120-150"),
            (150, 200, "150-200"),
            (200, SFI_MAX, "200-400"),
        ]

        result = []
        for lo, hi, label in brackets:
            total_sigs = 0
            total_spots = 0
            snr_weighted = 0.0
            rel_weighted = 0.0

            for src in sources:
                try:
                    conn = self._get_connection(src)
                    table = DATASET_REGISTRY[src][1]

                    upper = "avg_sfi <= ?" if hi == SFI_MAX else "avg_sfi < ?"
                    where = ["band = ?", "avg_sfi >= ?", upper]
                    params: list = [band, lo, hi]

                    if tx_grid:
                        where.append("tx_grid_4 = ?")
                        params.append(tx_grid.upper())
                    if rx_grid:
                        where.append("rx_grid_4 = ?")
                        params.append(rx_grid.upper())

                    row = conn.execute(
                        f"SELECT COUNT(*), SUM(spot_count), "
                        f"SUM(median_snr * spot_count), SUM(reliability * spot_count) "
                        f"FROM {table} WHERE {' AND '.join(where)}",
                        params,
                    ).fetchone()

                    if row and row[0]:
                        total_sigs += row[0]
                        total_spots += row[1] or 0
                        snr_weighted += row[2] or 0
                        rel_weighted += row[3] or 0
                except (FileNotFoundError, KeyError):
                    continue

            result.append({
                "sfi_bracket": label,
                "signatures": total_sigs,
                "total_spots": total_spots,
                "avg_snr": round(snr_weighted / total_spots, 1) if total_spots > 0 else None,
                "avg_reliability": round(rel_weighted / total_spots, 3) if total_spots > 0 else None,
            })
        return result

    def count_sfi_excluded(
        self,
        band: int,
        tx_grid: str | None = None,
        rx_grid: str | None = None,
        source: str = "all",
    ) -> int:
        """Rows for this band (and path) whose avg_sfi is outside the plausible range."""
        excluded = 0
        for src in self._resolve_sources(source):
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]
                where = ["band = ?", "NOT (avg_sfi BETWEEN ? AND ?) OR avg_sfi IS NULL"]
                params: list = [band, SFI_MIN, SFI_MAX]
                if tx_grid:
                    where.append("tx_grid_4 = ?")
                    params.append(tx_grid.upper())
                if rx_grid:
                    where.append("rx_grid_4 = ?")
                    params.append(rx_grid.upper())
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {' AND '.join(f'({w})' for w in where)}",
                    params,
                ).fetchone()
                excluded += row[0] if row else 0
            except (FileNotFoundError, KeyError):
                continue
        return excluded

    def query_compare_sources(
        self,
        tx_grid: str,
        rx_grid: str,
        band: int,
        hour: int | None = None,
    ) -> list[dict]:
        """Compare signatures across all available sources."""
        results = []
        for src in SIGNATURE_SOURCES:
            if not self.is_available(src):
                continue
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]
                where = ["tx_grid_4 = ?", "rx_grid_4 = ?", "band = ?"]
                params: list = [tx_grid.upper(), rx_grid.upper(), band]
                if hour is not None:
                    where.append("hour = ?")
                    params.append(hour)

                rows = conn.execute(
                    f"SELECT hour, median_snr, spot_count, reliability, avg_sfi, avg_kp "
                    f"FROM {table} WHERE {' AND '.join(where)} ORDER BY hour",
                    params,
                ).fetchall()

                for row in rows:
                    results.append({
                        "source": src,
                        "hour": row[0],
                        "median_snr": row[1],
                        "spot_count": row[2],
                        "reliability": row[3],
                        "avg_sfi": row[4],
                        "avg_kp": row[5],
                    })
            except (FileNotFoundError, KeyError):
                continue
        return results

    def query_dark_paths(
        self,
        band: int,
        source: str = "pskr",
        min_spots: int = 10,
    ) -> list[dict]:
        """Get signatures for a band, for post-processing solar classification."""
        sources = self._resolve_sources(source)
        results = []
        for src in sources:
            try:
                conn = self._get_connection(src)
                table = DATASET_REGISTRY[src][1]
                rows = conn.execute(
                    f"SELECT tx_grid_4, rx_grid_4, hour, month, median_snr, "
                    f"spot_count, reliability, avg_sfi "
                    f"FROM {table} "
                    f"WHERE band = ? AND spot_count >= ? "
                    f"ORDER BY spot_count DESC LIMIT 5000",
                    (band, min_spots),
                ).fetchall()
                results.extend([dict(r) for r in rows])
            except (FileNotFoundError, KeyError):
                continue
        return results

    def _resolve_sources(self, source: str) -> list[str]:
        """Resolve 'all' to available sources, or validate single source."""
        if source == "all":
            return self.available_sources()
        if source in SIGNATURE_SOURCES and self.is_available(source):
            return [source]
        return []

    def _query_single_source(
        self,
        source: str,
        band: int | None = None,
        tx_grid: str | None = None,
        rx_grid: str | None = None,
        hour: int | None = None,
        month: int | None = None,
        min_spots: int = 5,
        limit: int = 100,
        extra_select: str = "",
    ) -> list[dict]:
        """Query a single signature source with filters."""
        conn = self._get_connection(source)
        table = DATASET_REGISTRY[source][1]

        select = ", ".join(SIGNATURE_COLUMNS)
        if extra_select:
            select += f", {extra_select}"

        where: list[str] = []
        params: list = []

        if band is not None:
            where.append("band = ?")
            params.append(band)
        if tx_grid:
            if len(tx_grid) <= 2:
                where.append("tx_grid_4 LIKE ?")
                params.append(tx_grid.upper() + "%")
            else:
                where.append("tx_grid_4 = ?")
                params.append(tx_grid.upper())
        if rx_grid:
            if len(rx_grid) <= 2:
                where.append("rx_grid_4 LIKE ?")
                params.append(rx_grid.upper() + "%")
            else:
                where.append("rx_grid_4 = ?")
                params.append(rx_grid.upper())
        if hour is not None:
            where.append("hour = ?")
            params.append(hour)
        if month is not None:
            where.append("month = ?")
            params.append(month)
        if min_spots > 0:
            where.append("spot_count >= ?")
            params.append(min_spots)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""

        sql = f"SELECT {select} FROM {table} {where_clause} ORDER BY spot_count DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        """Close all connections."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
