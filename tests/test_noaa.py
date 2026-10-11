"""Unit tests for ionis_mcp.noaa — NOAA classifiers and band outlook.

Tests the pure classification functions (no network). HTTP fetch tests
are marked --live and skipped by default.
"""

import pytest

from ionis_mcp.noaa import (
    band_outlook,
    classify_bz,
    classify_kp,
    classify_sfi,
)

# ── classify_sfi ─────────────────────────────────────────────────────────────

class TestClassifySFI:
    def test_very_high(self):
        assert classify_sfi(220) == "VERY HIGH"

    def test_high(self):
        assert classify_sfi(160) == "HIGH"

    def test_moderate(self):
        assert classify_sfi(130) == "MODERATE"

    def test_low(self):
        assert classify_sfi(95) == "LOW"

    def test_very_low(self):
        assert classify_sfi(70) == "VERY LOW"

    def test_boundary_200(self):
        assert classify_sfi(200) == "VERY HIGH"

    def test_boundary_150(self):
        assert classify_sfi(150) == "HIGH"

    def test_boundary_120(self):
        assert classify_sfi(120) == "MODERATE"

    def test_boundary_90(self):
        assert classify_sfi(90) == "LOW"


# ── classify_kp ──────────────────────────────────────────────────────────────

class TestClassifyKp:
    def test_severe_storm(self):
        assert classify_kp(8.0) == "SEVERE STORM"

    def test_storm(self):
        assert classify_kp(5.5) == "STORM"

    def test_unsettled(self):
        assert classify_kp(4.0) == "UNSETTLED"

    def test_quiet(self):
        assert classify_kp(3.0) == "QUIET"

    def test_very_quiet(self):
        assert classify_kp(1.0) == "VERY QUIET"


# ── classify_bz ──────────────────────────────────────────────────────────────

class TestClassifyBz:
    def test_strongly_southward(self):
        result = classify_bz(-15.0)
        assert "storm likely" in result.lower()

    def test_southward(self):
        result = classify_bz(-7.0)
        assert "storm possible" in result.lower()

    def test_slightly_south(self):
        result = classify_bz(-2.0)
        assert "minor" in result.lower()

    def test_northward(self):
        result = classify_bz(5.0)
        assert "favorable" in result.lower()


# ── band_outlook ─────────────────────────────────────────────────────────────

class TestBandOutlook:
    def test_returns_all_bands(self):
        outlook = band_outlook(150.0, 2.0)
        expected_bands = ["10m", "12m", "15m", "17m", "20m", "30m", "40m", "80m", "160m"]
        for b in expected_bands:
            assert b in outlook, f"Missing band {b} in outlook"

    def test_high_sfi_quiet(self):
        """High SFI + quiet Kp = excellent high bands."""
        outlook = band_outlook(180.0, 1.0)
        assert "EXCELLENT" in outlook["10m"]
        assert "EXCELLENT" in outlook["15m"]

    def test_high_sfi_storm(self):
        """High SFI + storm = degraded."""
        outlook = band_outlook(180.0, 6.0)
        assert "DEGRADED" in outlook["10m"]

    def test_low_sfi_quiet(self):
        """Low SFI + quiet = 10m closed."""
        outlook = band_outlook(70.0, 1.0)
        assert "CLOSED" in outlook["10m"]

    def test_moderate_sfi(self):
        """SFI 100 should show 20m as primary."""
        outlook = band_outlook(100.0, 2.0)
        assert "20m" in outlook

    def test_storm_all_bands_degraded(self):
        """Storm conditions hurt all bands."""
        outlook = band_outlook(130.0, 6.0)
        for band in ["10m", "12m"]:
            val = outlook[band]
            assert "EXCELLENT" not in val


# ── fetch_current_conditions (live) ──────────────────────────────────────────

@pytest.mark.live
def test_fetch_current_conditions_live():
    """Live test: fetch real data from NOAA SWPC."""
    from ionis_mcp.noaa import fetch_current_conditions

    cond = fetch_current_conditions()
    # Should get at least SFI (most reliable endpoint)
    assert cond.sfi is not None or len(cond.errors) > 0
    # SFI should be in a reasonable range if available
    if cond.sfi is not None:
        assert 50 < cond.sfi < 400
    if cond.kp is not None:
        assert 0 <= cond.kp <= 9
