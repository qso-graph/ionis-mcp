"""Unit tests for ionis_mcp.database — DatabaseManager with fixture data."""

from ionis_mcp.database import DatabaseManager, SIGNATURE_SOURCES


# ── Discovery ────────────────────────────────────────────────────────────────

class TestDiscovery:
    def test_discovers_all_fixtures(self, db_manager):
        """Should find all 7 fixture datasets (5 sig + solar + grids)."""
        assert db_manager.is_available("wspr")
        assert db_manager.is_available("rbn")
        assert db_manager.is_available("contest")
        assert db_manager.is_available("dxpedition")
        assert db_manager.is_available("pskr")
        assert db_manager.is_available("solar")
        assert db_manager.is_available("grids")

    def test_not_available_missing(self, db_manager):
        """Datasets not in fixture dir should not be available."""
        assert not db_manager.is_available("dscovr")
        assert not db_manager.is_available("balloons")

    def test_available_sources(self, db_manager):
        sources = db_manager.available_sources()
        assert "wspr" in sources
        assert "rbn" in sources
        assert "pskr" in sources

    def test_discover_returns_row_counts(self, db_manager):
        """Each discovered dataset should have a positive row count."""
        datasets = db_manager.discover()
        for ds in datasets:
            assert ds.row_count > 0, f"{ds.key} has no rows"

    def test_discover_returns_file_sizes(self, db_manager):
        datasets = db_manager.discover()
        for ds in datasets:
            assert ds.file_size_mb >= 0, f"{ds.key} has negative file size"


# ── query_signatures ─────────────────────────────────────────────────────────

class TestQuerySignatures:
    def test_query_all_sources(self, db_manager):
        """Query across all sources returns combined results."""
        rows = db_manager.query_signatures(source="all", band=107)
        assert len(rows) > 0
        sources = {r["source"] for r in rows}
        assert len(sources) > 1, "Should have results from multiple sources"

    def test_query_single_source(self, db_manager):
        rows = db_manager.query_signatures(source="wspr", band=107)
        assert len(rows) > 0

    def test_filter_by_tx_grid(self, db_manager):
        rows = db_manager.query_signatures(tx_grid="DN13", band=107)
        for r in rows:
            assert r["tx_grid_4"] == "DN13"

    def test_filter_by_rx_grid(self, db_manager):
        rows = db_manager.query_signatures(rx_grid="JO51", band=107)
        for r in rows:
            assert r["rx_grid_4"] == "JO51"

    def test_filter_by_hour(self, db_manager):
        rows = db_manager.query_signatures(source="wspr", hour=14)
        for r in rows:
            assert r["hour"] == 14

    def test_filter_by_month(self, db_manager):
        rows = db_manager.query_signatures(source="wspr", month=3)
        for r in rows:
            assert r["month"] == 3

    def test_min_spots_filter(self, db_manager):
        rows = db_manager.query_signatures(source="wspr", min_spots=200)
        for r in rows:
            assert r["spot_count"] >= 200

    def test_limit_respected(self, db_manager):
        rows = db_manager.query_signatures(source="all", limit=3)
        assert len(rows) <= 3

    def test_2char_grid_field_filter(self, db_manager):
        """2-char grid should match as field prefix (LIKE 'DN%')."""
        rows = db_manager.query_signatures(tx_grid="DN")
        assert len(rows) > 0
        for r in rows:
            assert r["tx_grid_4"].startswith("DN")

    def test_empty_result(self, db_manager):
        rows = db_manager.query_signatures(tx_grid="AA00")
        assert rows == []

    def test_sorted_by_spot_count(self, db_manager):
        rows = db_manager.query_signatures(source="wspr", band=107)
        if len(rows) > 1:
            spots = [r["spot_count"] for r in rows]
            assert spots == sorted(spots, reverse=True)


# ── query_band_openings ─────────────────────────────────────────────────────

class TestBandOpenings:
    def test_returns_24_hours(self, db_manager):
        result = db_manager.query_band_openings("DN13", "JO51", 107)
        assert len(result) == 24

    def test_populated_hours_have_spots(self, db_manager):
        result = db_manager.query_band_openings("DN13", "JO51", 107)
        hours_with_data = [h for h in result if h["total_spots"] > 0]
        assert len(hours_with_data) > 0

    def test_empty_hours_have_zero_spots(self, db_manager):
        result = db_manager.query_band_openings("DN13", "JO51", 107)
        for h in result:
            if h["hour"] == 0:  # No fixture data at 00z for 20m
                assert h["total_spots"] == 0


# ── query_path_summary ──────────────────────────────────────────────────────

class TestPathSummary:
    def test_returns_all_bands(self, db_manager):
        sigs = db_manager.query_path_summary("DN13", "JO51")
        bands = {s["band"] for s in sigs}
        assert 107 in bands  # 20m should be present
        assert 105 in bands  # 40m

    def test_includes_source(self, db_manager):
        sigs = db_manager.query_path_summary("DN13", "JO51")
        sources = {s["source"] for s in sigs}
        assert "wspr" in sources

    def test_empty_for_unknown_path(self, db_manager):
        sigs = db_manager.query_path_summary("AA00", "AA01")
        assert sigs == []


# ── query_solar_conditions ───────────────────────────────────────────────────

class TestSolarConditions:
    def test_daily_resolution(self, db_manager):
        rows = db_manager.query_solar_conditions("2026-03-01", "2026-03-02")
        assert len(rows) == 2  # Two dates
        assert "observed_flux" in rows[0]

    def test_3hour_resolution(self, db_manager):
        rows = db_manager.query_solar_conditions(
            "2026-03-01", "2026-03-01", resolution="3hour"
        )
        assert len(rows) == 8  # 8 three-hour intervals

    def test_date_filter(self, db_manager):
        rows = db_manager.query_solar_conditions("2026-03-01", "2026-03-01")
        assert len(rows) == 1

    def test_empty_for_future_dates(self, db_manager):
        rows = db_manager.query_solar_conditions("2030-01-01", "2030-01-02")
        assert rows == []


# ── query_solar_correlation ──────────────────────────────────────────────────

class TestSolarCorrelation:
    def test_returns_brackets(self, db_manager):
        brackets = db_manager.query_solar_correlation(107, source="wspr")
        assert len(brackets) == 6  # 6 SFI brackets

    def test_bracket_labels(self, db_manager):
        brackets = db_manager.query_solar_correlation(107, source="wspr")
        labels = [b["sfi_bracket"] for b in brackets]
        assert "50-80" in labels
        assert "200-400" in labels

    def test_with_grid_filter(self, db_manager):
        brackets = db_manager.query_solar_correlation(
            107, tx_grid="DN13", rx_grid="JO51", source="wspr"
        )
        total = sum(b["signatures"] for b in brackets)
        assert total > 0


# ── query_band_global ────────────────────────────────────────────────────────

class TestBandGlobal:
    def test_has_totals(self, db_manager):
        stats = db_manager.query_band_global(107)
        assert stats["total_signatures"] > 0
        assert stats["total_spots"] > 0

    def test_hour_distribution(self, db_manager):
        stats = db_manager.query_band_global(107)
        assert len(stats["hour_distribution"]) == 24
        # Hour 14 should have spots (we have fixture data there)
        assert stats["hour_distribution"][14] > 0

    def test_top_grid_pairs(self, db_manager):
        stats = db_manager.query_band_global(107)
        assert len(stats["top_grid_pairs"]) > 0
        pair = stats["top_grid_pairs"][0]
        assert "tx" in pair
        assert "rx" in pair
        assert "spots" in pair

    def test_empty_band(self, db_manager):
        stats = db_manager.query_band_global(104)  # 60m — no fixture data
        assert stats["total_signatures"] == 0


# ── query_compare_sources ────────────────────────────────────────────────────

class TestCompareSources:
    def test_multiple_sources(self, db_manager):
        rows = db_manager.query_compare_sources("DN13", "JO51", 107)
        sources = {r["source"] for r in rows}
        assert len(sources) > 1

    def test_filter_by_hour(self, db_manager):
        rows = db_manager.query_compare_sources("DN13", "JO51", 107, hour=14)
        for r in rows:
            assert r["hour"] == 14


# ── query_dark_paths ─────────────────────────────────────────────────────────

class TestDarkPaths:
    def test_returns_paths(self, db_manager):
        paths = db_manager.query_dark_paths(107, source="wspr")
        assert len(paths) > 0

    def test_min_spots_filter(self, db_manager):
        paths = db_manager.query_dark_paths(107, source="wspr", min_spots=100)
        for p in paths:
            assert p["spot_count"] >= 100

    def test_has_required_fields(self, db_manager):
        paths = db_manager.query_dark_paths(107, source="wspr")
        for p in paths:
            assert "tx_grid_4" in p
            assert "rx_grid_4" in p
            assert "hour" in p
            assert "month" in p
            assert "median_snr" in p
