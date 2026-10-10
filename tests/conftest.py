"""Shared fixtures for ionis-mcp tests.

Creates small SQLite fixture databases in a temp directory that mirror the
production schema. Enough data to exercise every tool without the 15 GB
SourceForge datasets.
"""

import os
import sqlite3

import pytest

# ── Signature schema (shared by all 5 sources) ──────────────────────────────

SIGNATURE_COLUMNS = """
    tx_grid_4    TEXT,
    rx_grid_4    TEXT,
    band         INTEGER,
    hour         INTEGER,
    month        INTEGER,
    median_snr   REAL,
    spot_count   INTEGER,
    snr_std      REAL,
    reliability  REAL,
    avg_sfi      REAL,
    avg_kp       REAL,
    avg_distance REAL,
    avg_azimuth  REAL
"""

# Representative fixture rows: DN13→JO51 (Boise→Germany, ~8500 km) on 20m
# Covers hours 12-18z, months 3 and 6, varying SFI brackets
WSPR_ROWS = [
    # tx,    rx,    band, hr, mo, snr,  spots, std, rel,   sfi,  kp,  dist,  azm
    ("DN13", "JO51", 107,  12,  3, -8.5,  150, 3.2, 0.42, 130.0, 2.0, 8500, 35.0),
    ("DN13", "JO51", 107,  14,  3, -6.2,  280, 2.8, 0.65, 135.0, 1.5, 8500, 35.0),
    ("DN13", "JO51", 107,  16,  3, -5.0,  320, 2.5, 0.71, 132.0, 2.5, 8500, 35.0),
    ("DN13", "JO51", 107,  18,  3, -9.1,   90, 3.5, 0.28, 128.0, 3.0, 8500, 35.0),
    ("DN13", "JO51", 107,  14,  6, -4.8,  410, 2.1, 0.78, 155.0, 1.0, 8500, 35.0),
    ("DN13", "JO51", 107,  16,  6, -3.5,  520, 1.9, 0.85, 160.0, 1.0, 8500, 35.0),
    # 10m row for dark-hour testing (hour 6z = night in both DN13 and JO51 in March)
    ("DN13", "JO51", 111,   6,  3, -15.0,  12, 4.0, 0.05,  90.0, 1.0, 8500, 35.0),
    # 40m row
    ("DN13", "JO51", 105,   2,  3, -12.0, 200, 3.0, 0.55, 100.0, 2.0, 8500, 35.0),
    # Different path: W1AW grid (FN31) to JO51
    ("FN31", "JO51", 107,  14,  6, -7.0,  180, 2.5, 0.50, 140.0, 2.0, 6300, 55.0),
    # Low SFI bracket row
    ("DN13", "JO51", 107,  14,  3, -11.0,  45, 3.8, 0.15,  72.0, 1.0, 8500, 35.0),
    # High SFI bracket row
    ("DN13", "JO51", 107,  14,  6, -2.0,  600, 1.5, 0.90, 210.0, 1.0, 8500, 35.0),
]

RBN_ROWS = [
    ("DN13", "JO51", 107,  14,  3, 15.0,  85, 4.0, 0.35, 130.0, 2.0, 8500, 35.0),
    ("DN13", "JO51", 107,  16,  3, 18.0, 110, 3.5, 0.48, 132.0, 2.5, 8500, 35.0),
]

CONTEST_ROWS = [
    ("DN13", "JO51", 107,  14,  3, 10.0,  30, 0.0, 1.00, 130.0, 2.0, 8500, 35.0),
    ("DN13", "JO51", 105,   2, 11, 10.0,  25, 0.0, 1.00, 110.0, 3.0, 8500, 35.0),
]

DXPEDITION_ROWS = [
    ("DN13", "RG37", 107,  14,  6, -5.0,  40, 2.0, 0.60, 150.0, 1.5, 14200, 220.0),
]

PSKR_ROWS = [
    ("DN13", "JO51", 107,  14,  3, -5.5, 500, 2.2, 0.72, 135.0, 2.0, 8500, 35.0),
    ("DN13", "JO51", 111,  14,  6, -3.0, 350, 2.0, 0.60, 165.0, 1.0, 8500, 35.0),
    ("DN13", "JO51", 111,   6,  3, -18.0,  8, 5.0, 0.02,  88.0, 1.0, 8500, 35.0),
]

# Solar indices fixture
SOLAR_ROWS = [
    # date, timestamp, observed_flux, adjusted_flux, ssn, kp_index, ap_index
    ("2026-03-01", "2026-03-01 00:00:00", 135.0, 132.0, 85, 2.00, 8),
    ("2026-03-01", "2026-03-01 03:00:00", 135.0, 132.0, 85, 2.33, 10),
    ("2026-03-01", "2026-03-01 06:00:00", 135.0, 132.0, 85, 1.67, 6),
    ("2026-03-01", "2026-03-01 09:00:00", 135.0, 132.0, 85, 2.00, 8),
    ("2026-03-01", "2026-03-01 12:00:00", 135.0, 132.0, 85, 1.33, 5),
    ("2026-03-01", "2026-03-01 15:00:00", 135.0, 132.0, 85, 1.67, 6),
    ("2026-03-01", "2026-03-01 18:00:00", 135.0, 132.0, 85, 2.00, 8),
    ("2026-03-01", "2026-03-01 21:00:00", 135.0, 132.0, 85, 1.33, 5),
    ("2026-03-02", "2026-03-02 00:00:00", 138.0, 135.0, 88, 3.00, 15),
    ("2026-03-02", "2026-03-02 03:00:00", 138.0, 135.0, 88, 3.33, 18),
]

# Grid lookup fixture (minimal set)
GRID_ROWS = [
    # grid, latitude, longitude
    ("DN13", 43.5, -116.0),
    ("DN46", 44.5, -110.0),
    ("JO51", 51.5, 1.0),
    ("FN31", 41.5, -73.0),
    ("RG37", -32.5, 27.0),
    ("IO91", 51.5, -1.0),
]


def _create_signature_table(conn: sqlite3.Connection, table: str, rows: list):
    """Create a signature table and insert fixture rows."""
    conn.execute(f"CREATE TABLE {table} ({SIGNATURE_COLUMNS})")
    conn.executemany(
        f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def _create_solar_table(conn: sqlite3.Connection):
    """Create solar_indices table with fixture data."""
    conn.execute("""
        CREATE TABLE solar_indices (
            date TEXT,
            timestamp TEXT,
            observed_flux REAL,
            adjusted_flux REAL,
            ssn REAL,
            kp_index REAL,
            ap_index REAL
        )
    """)
    conn.executemany(
        "INSERT INTO solar_indices VALUES (?,?,?,?,?,?,?)",
        SOLAR_ROWS,
    )
    conn.commit()


def _create_grid_table(conn: sqlite3.Connection):
    """Create grid_lookup table with fixture data."""
    conn.execute("""
        CREATE TABLE grid_lookup (
            grid TEXT PRIMARY KEY,
            latitude REAL,
            longitude REAL
        )
    """)
    conn.executemany(
        "INSERT INTO grid_lookup VALUES (?,?,?)",
        GRID_ROWS,
    )
    conn.commit()


@pytest.fixture
def fixture_data_dir(tmp_path):
    """Create a temporary data directory with all fixture SQLite databases.

    Mirrors the production directory structure expected by DatabaseManager.
    Returns the path to the data directory.
    """
    # Signature databases
    sig_map = {
        "wspr": ("propagation/wspr-signatures", "wspr_signatures_v2.sqlite", "wspr_signatures_v2", WSPR_ROWS),
        "rbn": ("propagation/rbn-signatures", "rbn_signatures.sqlite", "rbn_signatures", RBN_ROWS),
        "contest": ("propagation/contest-signatures", "contest_signatures.sqlite", "contest_signatures", CONTEST_ROWS),
        "dxpedition": ("propagation/dxpedition-signatures", "dxpedition_signatures.sqlite", "dxpedition_signatures", DXPEDITION_ROWS),
        "pskr": ("propagation/pskr-signatures", "pskr_signatures.sqlite", "pskr_signatures", PSKR_ROWS),
    }

    for key, (subdir, filename, table, rows) in sig_map.items():
        db_dir = tmp_path / subdir
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / filename
        conn = sqlite3.connect(str(db_path))
        _create_signature_table(conn, table, rows)
        conn.close()

    # Solar indices
    solar_dir = tmp_path / "solar" / "solar-indices"
    solar_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(solar_dir / "solar_indices.sqlite"))
    _create_solar_table(conn)
    conn.close()

    # Grid lookup
    grid_dir = tmp_path / "tools" / "grid-lookup"
    grid_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(grid_dir / "grid_lookup.sqlite"))
    _create_grid_table(conn)
    conn.close()

    return str(tmp_path)


@pytest.fixture
def db_manager(fixture_data_dir):
    """Create a DatabaseManager initialized with fixture data."""
    from ionis_mcp.database import DatabaseManager

    mgr = DatabaseManager(data_dir=fixture_data_dir)
    mgr.discover()
    yield mgr
    mgr.close()


@pytest.fixture
def grid_lookup_loaded(fixture_data_dir):
    """Create a GridLookup loaded from fixture SQLite."""
    from ionis_mcp.grids import GridLookup

    lookup = GridLookup()
    grid_db = os.path.join(fixture_data_dir, "tools/grid-lookup/grid_lookup.sqlite")
    lookup.load_from_sqlite(grid_db)
    return lookup
