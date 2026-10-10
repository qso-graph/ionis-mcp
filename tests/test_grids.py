"""Unit tests for ionis_mcp.grids — Maidenhead grid utilities."""

from ionis_mcp.grids import (
    BAND_BY_NAME,
    BANDS,
    GridLookup,
    azimuth_deg,
    band_name,
    grid_to_latlon,
    haversine_km,
    validate_grid,
)

# ── validate_grid ────────────────────────────────────────────────────────────

class TestValidateGrid:
    def test_valid_4char(self):
        assert validate_grid("DN13") == "DN13"

    def test_valid_4char_lowercase(self):
        assert validate_grid("dn13") == "DN13"

    def test_valid_6char(self):
        assert validate_grid("DN13la") == "DN13la"

    def test_valid_6char_mixed_case(self):
        assert validate_grid("dn13LA") == "DN13la"

    def test_null_bytes_stripped(self):
        """FixedString(8) from ClickHouse may have trailing null bytes."""
        assert validate_grid("DN13\x00\x00\x00\x00") == "DN13"

    def test_whitespace_stripped(self):
        assert validate_grid("  DN13  ") == "DN13"

    def test_empty_string(self):
        assert validate_grid("") is None

    def test_none_input(self):
        assert validate_grid(None) is None

    def test_too_short(self):
        assert validate_grid("DN") is None

    def test_invalid_field_letters(self):
        """Field letters must be A-R (Maidenhead)."""
        assert validate_grid("ZZ99") is None

    def test_digits_first(self):
        assert validate_grid("12AB") is None

    def test_sql_injection(self):
        assert validate_grid("'; DROP TABLE--") is None

    def test_xss_attempt(self):
        assert validate_grid("<script>alert(1)</script>") is None

    def test_all_corner_grids(self):
        """Test boundary grids: AA00, RR99, AA00aa, RR99xx."""
        assert validate_grid("AA00") == "AA00"
        assert validate_grid("RR99") == "RR99"
        assert validate_grid("AA00aa") == "AA00aa"
        assert validate_grid("RR99xx") == "RR99xx"


# ── grid_to_latlon ───────────────────────────────────────────────────────────

class TestGridToLatlon:
    def test_dn13_approximate(self):
        """DN13 should be roughly Boise, Idaho area."""
        lat, lon = grid_to_latlon("DN13")
        assert 43.0 < lat < 44.0
        assert -118.0 < lon < -115.0

    def test_jo51_approximate(self):
        """JO51 should be roughly Western Europe."""
        lat, lon = grid_to_latlon("JO51")
        assert 51.0 < lat < 52.0
        assert 10.0 < lon < 13.0

    def test_6char_more_precise(self):
        """6-char grids give a tighter centroid than 4-char."""
        lat4, lon4 = grid_to_latlon("DN13")
        lat6, lon6 = grid_to_latlon("DN13la")
        # 6-char centroid should be within the 4-char square
        assert abs(lat6 - lat4) < 1.0
        assert abs(lon6 - lon4) < 2.0

    def test_southern_hemisphere(self):
        """Grid in southern hemisphere (e.g., RG37 = South Africa)."""
        lat, lon = grid_to_latlon("RG37")
        assert lat < 0, "RG37 should be in southern hemisphere"


# ── GridLookup ───────────────────────────────────────────────────────────────

class TestGridLookup:
    def test_empty_cache_falls_back_to_math(self):
        lookup = GridLookup()
        lat, lon = lookup.get("DN13")
        assert 43.0 < lat < 44.0

    def test_load_from_sqlite(self, grid_lookup_loaded):
        assert grid_lookup_loaded.size >= 6

    def test_cached_value_used(self, grid_lookup_loaded):
        """Cached value from SQLite should be returned."""
        lat, lon = grid_lookup_loaded.get("DN13")
        assert lat == 43.5
        assert lon == -116.0


# ── haversine_km ─────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_km(43.5, -116.0, 43.5, -116.0) == 0.0

    def test_boise_to_london(self):
        """DN13 to IO91 should be roughly 7500-8500 km."""
        dist = haversine_km(43.5, -116.0, 51.5, -1.0)
        assert 7500 < dist < 8500

    def test_antipodal(self):
        """Opposite sides of the earth should be ~20000 km."""
        dist = haversine_km(0, 0, 0, 180)
        assert abs(dist - 20015) < 50

    def test_symmetric(self):
        d1 = haversine_km(43.5, -116.0, 51.5, 1.0)
        d2 = haversine_km(51.5, 1.0, 43.5, -116.0)
        assert abs(d1 - d2) < 0.01


# ── azimuth_deg ──────────────────────────────────────────────────────────────

class TestAzimuth:
    def test_due_north(self):
        """Same longitude, higher latitude should be ~0 degrees."""
        az = azimuth_deg(40.0, -100.0, 50.0, -100.0)
        assert az < 1.0 or az > 359.0

    def test_due_east(self):
        """Same latitude, higher longitude should be roughly 90 degrees."""
        az = azimuth_deg(0.0, 0.0, 0.0, 10.0)
        assert 89.0 < az < 91.0

    def test_range_0_360(self):
        """Azimuth should always be in [0, 360)."""
        az = azimuth_deg(43.5, -116.0, 51.5, 1.0)
        assert 0 <= az < 360


# ── band_name ────────────────────────────────────────────────────────────────

class TestBandName:
    def test_known_band(self):
        assert "20m" in band_name(107)
        assert "14.0" in band_name(107)

    def test_unknown_band(self):
        assert "Band 999" == band_name(999)

    def test_all_bands_have_names(self):
        for band_id in BANDS:
            name = band_name(band_id)
            assert "Band " not in name  # Should resolve to a real name

    def test_reverse_lookup(self):
        assert BAND_BY_NAME["20m"] == 107
        assert BAND_BY_NAME["10m"] == 111
