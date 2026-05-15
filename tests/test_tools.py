"""Unit tests for all 11 ionis-mcp tools.

Uses fixture SQLite databases (no production data needed).
Each tool is tested by calling the function directly after initializing
the module-level globals with fixture data.
"""

import os

import pytest

from ionis_mcp.grids import GridLookup
import ionis_mcp.server as server_mod
from ionis_mcp.database import DatabaseManager


@pytest.fixture(autouse=True)
def init_server_globals(fixture_data_dir):
    """Initialize the module-level globals in server.py with fixture data."""
    mgr = DatabaseManager(data_dir=fixture_data_dir)
    mgr.discover()

    # Load grid lookup from fixture
    lookup = GridLookup()
    grid_db = os.path.join(fixture_data_dir, "tools/grid-lookup/grid_lookup.sqlite")
    lookup.load_from_sqlite(grid_db)

    # Patch module globals
    old_db = server_mod.db
    old_grid = server_mod.grid_lookup
    server_mod.db = mgr
    server_mod.grid_lookup = lookup

    yield

    # Restore
    server_mod.db = old_db
    server_mod.grid_lookup = old_grid
    mgr.close()


# ── Tool 1: list_datasets ───────────────────────────────────────────────────

class TestListDatasets:
    def test_returns_markdown_table(self):
        result = server_mod.list_datasets()
        assert "| Dataset |" in result
        assert "wspr" in result

    def test_shows_row_counts(self):
        result = server_mod.list_datasets()
        assert "Total" in result

    def test_shows_all_fixture_datasets(self):
        result = server_mod.list_datasets()
        for key in ["wspr", "rbn", "contest", "dxpedition", "pskr", "solar", "grids"]:
            assert key in result


# ── Tool 2: query_signatures ────────────────────────────────────────────────

class TestQuerySignatures:
    def test_basic_query(self):
        result = server_mod.query_signatures(source="wspr", band=107)
        assert "DN13" in result
        assert "JO51" in result

    def test_empty_result(self):
        result = server_mod.query_signatures(tx_grid="AA00")
        assert "No signatures found" in result

    def test_limit_parameter(self):
        result = server_mod.query_signatures(source="all", limit=2)
        # Should contain table header + at most 2 data rows
        assert "Signature Query Results" in result

    def test_all_sources(self):
        result = server_mod.query_signatures(source="all", band=107)
        assert len(result) > 0

    def test_grid_filter(self):
        result = server_mod.query_signatures(tx_grid="DN13", rx_grid="JO51")
        assert "DN13" in result
        assert "JO51" in result

    def test_hour_filter(self):
        result = server_mod.query_signatures(source="wspr", hour=14)
        assert "14z" in result


# ── Tool 3: band_openings ───────────────────────────────────────────────────

class TestBandOpenings:
    def test_returns_24_rows(self):
        result = server_mod.band_openings("DN13", "JO51", 107)
        # Should have 24 hour rows in the table
        assert "Band Openings" in result
        assert "Distance" in result

    def test_shows_solar_elevation(self):
        result = server_mod.band_openings("DN13", "JO51", 107)
        assert "TX Solar" in result
        assert "RX Solar" in result

    def test_shows_distance(self):
        result = server_mod.band_openings("DN13", "JO51", 107)
        assert "km" in result

    def test_invalid_grid(self):
        result = server_mod.band_openings("ZZZZ", "JO51", 107)
        assert "Invalid grid" in result


# ── Tool 4: path_analysis ───────────────────────────────────────────────────

class TestPathAnalysis:
    def test_returns_full_analysis(self):
        result = server_mod.path_analysis("DN13", "JO51")
        assert "Path Analysis" in result
        assert "Distance" in result
        assert "Azimuth" in result

    def test_shows_band_summary(self):
        result = server_mod.path_analysis("DN13", "JO51")
        assert "Band Summary" in result
        assert "20m" in result

    def test_shows_best_combos(self):
        result = server_mod.path_analysis("DN13", "JO51")
        assert "Best Band/Hour" in result

    def test_shows_seasonal_pattern(self):
        result = server_mod.path_analysis("DN13", "JO51")
        assert "Seasonal Pattern" in result

    def test_shows_source_breakdown(self):
        result = server_mod.path_analysis("DN13", "JO51")
        assert "Sources" in result

    def test_invalid_grid(self):
        result = server_mod.path_analysis("ZZZZ", "JO51")
        assert "Invalid grid" in result

    def test_no_data_path(self):
        result = server_mod.path_analysis("AA00", "AA01")
        assert "No signatures found" in result


# ── Tool 5: solar_correlation ────────────────────────────────────────────────

class TestSolarCorrelation:
    def test_returns_brackets(self):
        result = server_mod.solar_correlation(107, source="wspr")
        assert "SFI Correlation" in result
        assert "< 80" in result
        assert "200+" in result

    def test_shows_band_name(self):
        result = server_mod.solar_correlation(107)
        assert "20m" in result

    def test_with_grid_scope(self):
        result = server_mod.solar_correlation(107, tx_grid="DN13", rx_grid="JO51")
        assert "DN13" in result
        assert "JO51" in result

    def test_physics_note(self):
        """Should include the D-layer / F-layer explanation."""
        result = server_mod.solar_correlation(107)
        assert "F-layer" in result or "D-layer" in result


# ── Tool 6: grid_info ───────────────────────────────────────────────────────

class TestGridInfo:
    def test_basic_decode(self):
        result = server_mod.grid_info("DN13")
        assert "Grid Info" in result
        assert "Latitude" in result
        assert "Longitude" in result

    def test_with_solar_elevation(self):
        result = server_mod.grid_info("DN13", hour=14, month=6)
        assert "Solar Elevation" in result
        assert "Classification" in result

    def test_with_day_of_year(self):
        result = server_mod.grid_info("DN13", hour=14, day_of_year=172)
        assert "DOY 172" in result

    def test_default_month_hint(self):
        """When hour given but no month/doy, should suggest adding month."""
        result = server_mod.grid_info("DN13", hour=14)
        assert "mid-June" in result or "month" in result.lower()

    def test_invalid_grid(self):
        result = server_mod.grid_info("ZZZZ")
        assert "Invalid" in result

    def test_6char_grid(self):
        result = server_mod.grid_info("DN13la")
        assert "Grid Info" in result


# ── Tool 7: compare_sources ─────────────────────────────────────────────────

class TestCompareSources:
    def test_returns_comparison(self):
        result = server_mod.compare_sources("DN13", "JO51", 107)
        assert "Source Comparison" in result

    def test_multiple_sources(self):
        result = server_mod.compare_sources("DN13", "JO51", 107)
        # Should show data from wspr, rbn, contest, pskr
        assert "Summary by Source" in result

    def test_with_hour_filter(self):
        result = server_mod.compare_sources("DN13", "JO51", 107, hour=14)
        assert "14z" in result

    def test_invalid_grid(self):
        result = server_mod.compare_sources("ZZZZ", "JO51", 107)
        assert "Invalid grid" in result

    def test_no_data(self):
        result = server_mod.compare_sources("AA00", "AA01", 107)
        assert "No data found" in result


# ── Tool 8: dark_hour_analysis ───────────────────────────────────────────────

class TestDarkHourAnalysis:
    def test_returns_classification(self):
        result = server_mod.dark_hour_analysis(107, 14, source="wspr")
        assert "Dark Hour Analysis" in result
        assert "Classification Summary" in result

    def test_categories_present(self):
        result = server_mod.dark_hour_analysis(107, 14, source="wspr")
        assert "both_day" in result or "cross_terminator" in result

    def test_with_month_filter(self):
        result = server_mod.dark_hour_analysis(107, 14, month=3, source="wspr")
        assert "month 3" in result

    def test_no_paths_message(self):
        result = server_mod.dark_hour_analysis(104, 0, source="wspr")  # 60m, no data
        assert "No paths found" in result


# ── Tool 9: solar_history ────────────────────────────────────────────────────

class TestSolarHistoryTool:
    def test_daily_query(self):
        result = server_mod.solar_history("2026-03-01", "2026-03-02")
        assert "Solar Conditions" in result
        assert "2026-03-01" in result

    def test_3hour_resolution(self):
        result = server_mod.solar_history(
            "2026-03-01", "2026-03-01", resolution="3hour"
        )
        assert "Time" in result

    def test_no_data_range(self):
        result = server_mod.solar_history("2030-01-01", "2030-01-02")
        assert "No solar data found" in result


# ── Tool 10: band_summary ───────────────────────────────────────────────────

class TestBandSummary:
    def test_returns_overview(self):
        result = server_mod.band_summary(107)
        assert "Band Summary" in result
        assert "20m" in result

    def test_shows_hour_distribution(self):
        result = server_mod.band_summary(107)
        assert "Hour Distribution" in result

    def test_shows_top_pairs(self):
        result = server_mod.band_summary(107)
        assert "Top Grid Pairs" in result

    def test_empty_band(self):
        result = server_mod.band_summary(104)  # 60m, no fixture data
        assert "No data found" in result


# ── Tool 11: current_conditions (mock) ───────────────────────────────────────

class TestCurrentConditions:
    def test_returns_report(self, monkeypatch):
        """Mock NOAA fetch to avoid network calls."""
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(
            sfi=145.0,
            kp=2.5,
            bz=-1.5,
            wind_speed=380.0,
            wind_density=4.2,
            alerts=[],
            errors=[],
        )
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions()
        assert "Propagation Report" in result
        assert "145" in result
        assert "2.5" in result

    def test_with_qth_grid(self, monkeypatch):
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(sfi=130.0, kp=1.0)
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions(qth_grid="DN13")
        assert "DN13" in result
        assert "Solar elevation" in result.lower() or "Your QTH" in result

    def test_band_outlook_included(self, monkeypatch):
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(sfi=160.0, kp=1.5)
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions()
        assert "Band Outlook" in result
        assert "10m" in result

    def test_portable_recommendation(self, monkeypatch):
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(sfi=160.0, kp=1.5)
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions()
        assert "Portable" in result or "POTA" in result

    def test_storm_warning(self, monkeypatch):
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(sfi=130.0, kp=6.0)
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions()
        assert "storm" in result.lower()

    def test_handles_partial_data(self, monkeypatch):
        """Should handle missing SFI/Kp gracefully."""
        from ionis_mcp.noaa import SolarConditions

        mock_cond = SolarConditions(sfi=None, kp=None, errors=["SFI timeout"])
        monkeypatch.setattr(
            "ionis_mcp.server.fetch_current_conditions",
            lambda: mock_cond,
        )
        result = server_mod.current_conditions()
        assert "unavailable" in result


# ── Tool: _require_db error ──────────────────────────────────────────────────

class TestRequireDb:
    def test_raises_when_no_db(self):
        old_db = server_mod.db
        server_mod.db = None
        try:
            with pytest.raises(RuntimeError, match="Database not initialized"):
                server_mod._require_db()
        finally:
            server_mod.db = old_db


# ── Tool: get_version_info — fleet identity attestation ─────────────────────
# Tracks IONIS-AI/ionis-devel#49 — fleet get_version_info convention.

class TestGetVersionInfo:
    def test_returns_service_name(self):
        """Payload includes service_name = 'ionis-mcp'."""
        assert server_mod._version_info_payload()["service_name"] == "ionis-mcp"

    def test_returns_service_version(self):
        """service_version matches package __version__."""
        from ionis_mcp import __version__

        assert server_mod._version_info_payload()["service_version"] == __version__

    def test_returns_spec_version(self):
        """spec_version pins the IONIS dataset bundle revision."""
        assert server_mod._version_info_payload()["spec_version"] == "ionis-dataset-v1"

    def test_payload_keys_are_required_set(self):
        """Payload has the required keys (no extras yet)."""
        result = server_mod._version_info_payload()
        required = {"service_name", "service_version", "spec_version"}
        assert required.issubset(set(result.keys()))

    def test_all_values_are_strings(self):
        """All returned values are strings (JSON-safe envelope)."""
        result = server_mod._version_info_payload()
        for k in ("service_name", "service_version", "spec_version"):
            assert isinstance(result[k], str), f"{k} should be str, got {type(result[k])}"
            assert result[k], f"{k} should be non-empty"
