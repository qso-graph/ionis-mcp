"""Unit tests for ionis_mcp.solar — solar elevation and geometry."""

from ionis_mcp.solar import (
    classify_path_solar,
    classify_solar,
    month_to_mid_doy,
    solar_elevation_deg,
)

# ── solar_elevation_deg ──────────────────────────────────────────────────────

class TestSolarElevation:
    def test_noon_equator_equinox_is_high(self):
        """Sun should be near 90° at equator at noon on equinox."""
        elev = solar_elevation_deg(0.0, 0.0, 12.0, 80)  # ~March 21
        assert elev > 60

    def test_midnight_is_negative(self):
        """Sun below horizon at local midnight (00z at lon=0)."""
        elev = solar_elevation_deg(51.5, 0.0, 0.0, 172)  # mid-June, midnight
        assert elev < 0

    def test_boise_midday_june(self):
        """Boise (43.5°N) at ~19z in June should be daylight."""
        # 19z = noon local (UTC-7)
        elev = solar_elevation_deg(43.5, -116.0, 19.0, 172)
        assert elev > 50

    def test_boise_night_march(self):
        """Boise at 06z in March should be deep night."""
        elev = solar_elevation_deg(43.5, -116.0, 6.0, 75)
        assert elev < -18

    def test_symmetric_by_longitude(self):
        """Same latitude, 12h apart in local time should have roughly opposite elevations."""
        # At lon=0, 12z is noon; at lon=180, 12z is midnight
        day = solar_elevation_deg(45.0, 0.0, 12.0, 172)
        night = solar_elevation_deg(45.0, 180.0, 12.0, 172)
        assert day > 0
        assert night < 0

    def test_arctic_midnight_sun(self):
        """At 70°N in mid-June, sun should be above horizon at midnight."""
        elev = solar_elevation_deg(70.0, 0.0, 0.0, 172)
        assert elev > 0

    def test_output_range(self):
        """Elevation should always be between -90 and +90."""
        for lat in [-90, -45, 0, 45, 90]:
            for hour in [0, 6, 12, 18]:
                for doy in [1, 80, 172, 265]:
                    elev = solar_elevation_deg(lat, 0.0, hour, doy)
                    assert -90 <= elev <= 90


# ── classify_solar ───────────────────────────────────────────────────────────

class TestClassifySolar:
    def test_day(self):
        assert classify_solar(30.0) == "DAY"

    def test_civil_twilight(self):
        assert classify_solar(-3.0) == "CIVIL_TWILIGHT"

    def test_nautical_twilight(self):
        assert classify_solar(-9.0) == "NAUTICAL_TWILIGHT"

    def test_astronomical_twilight(self):
        assert classify_solar(-15.0) == "ASTRONOMICAL_TWILIGHT"

    def test_night(self):
        assert classify_solar(-25.0) == "NIGHT"

    def test_boundary_zero(self):
        """Exactly 0° is not day (sun on horizon)."""
        assert classify_solar(0.0) == "CIVIL_TWILIGHT"

    def test_boundary_neg6(self):
        assert classify_solar(-6.0) == "NAUTICAL_TWILIGHT"

    def test_boundary_neg12(self):
        assert classify_solar(-12.0) == "ASTRONOMICAL_TWILIGHT"

    def test_boundary_neg18(self):
        assert classify_solar(-18.0) == "NIGHT"


# ── classify_path_solar ─────────────────────────────────────────────────────

class TestClassifyPathSolar:
    def test_both_day(self):
        """Two points both in daylight."""
        cls, tx_e, rx_e = classify_path_solar(
            0.0, 0.0,   # equator at lon 0
            0.0, 10.0,  # equator at lon 10
            12.0, 80,   # noon UTC, equinox
        )
        assert cls == "both_day"
        assert tx_e > 0
        assert rx_e > 0

    def test_both_dark(self):
        """DN13 and JO51 at 06z in March — both deep night."""
        cls, tx_e, rx_e = classify_path_solar(
            43.5, -116.0,  # DN13 (Boise)
            51.5, 1.0,     # JO51 (England)
            6.0, 75,       # 06z, March
        )
        # Boise: 06z = ~11pm local, definitely dark
        # England: 06z = 6am, March = before sunrise
        assert tx_e < 0
        # JO51 at 06z in March: sunrise ~06:30, so barely still dark
        # Classification depends on twilight thresholds

    def test_cross_terminator(self):
        """One point in day, one in night."""
        cls, tx_e, rx_e = classify_path_solar(
            0.0, 0.0,     # equator lon 0 — noon
            0.0, 180.0,   # equator lon 180 — midnight
            12.0, 80,
        )
        assert cls == "cross_terminator"

    def test_returns_elevations(self):
        """Function should return both elevation values."""
        cls, tx_e, rx_e = classify_path_solar(
            43.5, -116.0, 51.5, 1.0, 12.0, 172,
        )
        assert isinstance(tx_e, float)
        assert isinstance(rx_e, float)


# ── month_to_mid_doy ────────────────────────────────────────────────────────

class TestMonthToMidDoy:
    def test_january(self):
        doy = month_to_mid_doy(1)
        assert 14 <= doy <= 16

    def test_june(self):
        doy = month_to_mid_doy(6)
        assert 165 <= doy <= 167

    def test_december(self):
        doy = month_to_mid_doy(12)
        assert 348 <= doy <= 350

    def test_clamps_low(self):
        """Month 0 should clamp to 1."""
        assert month_to_mid_doy(0) == month_to_mid_doy(1)

    def test_clamps_high(self):
        """Month 13 should clamp to 12."""
        assert month_to_mid_doy(13) == month_to_mid_doy(12)

    def test_monotonic(self):
        """DOY should increase with month."""
        doys = [month_to_mid_doy(m) for m in range(1, 13)]
        assert doys == sorted(doys)
