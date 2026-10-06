"""#13: tools say when a dataset isn't installed. #17: implausible SFI is unknown."""

import sqlite3

import pytest

import ionis_mcp.server as server_mod
from ionis_mcp.database import DatabaseManager, plausible_sfi
from tests.conftest import SIGNATURE_COLUMNS, WSPR_ROWS

SIGNATURE_TOOLS = [
    ("query_signatures", {}),
    ("band_openings", {"tx_grid": "DN13", "rx_grid": "JO51", "band": 107}),
    ("path_analysis", {"tx_grid": "DN13", "rx_grid": "JO51"}),
    ("solar_correlation", {"band": 107, "source": "all"}),
    ("compare_sources", {"tx_grid": "DN13", "rx_grid": "JO51", "band": 107}),
    ("dark_hour_analysis", {"band": 107, "hour": 14, "source": "all"}),
    ("band_summary", {"band": 107}),
]


@pytest.fixture
def server_with(tmp_path):
    """Point the server at a data directory holding only the given WSPR rows."""
    old = server_mod.db

    def make(wspr_rows=None):
        if wspr_rows is not None:
            d = tmp_path / "propagation" / "wspr-signatures"
            d.mkdir(parents=True)
            conn = sqlite3.connect(str(d / "wspr_signatures_v2.sqlite"))
            conn.execute(f"CREATE TABLE wspr_signatures_v2 ({SIGNATURE_COLUMNS})")
            conn.executemany(f"INSERT INTO wspr_signatures_v2 VALUES ({','.join('?' * 13)})", wspr_rows)
            conn.commit()
            conn.close()
        mgr = DatabaseManager(data_dir=str(tmp_path))
        mgr.discover()
        server_mod.db = mgr
        return mgr

    yield make
    if server_mod.db is not None and server_mod.db is not old:
        server_mod.db.close()
    server_mod.db = old


# ── #13 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool,args", SIGNATURE_TOOLS)
def test_no_datasets_is_an_error_not_a_closed_band(server_with, tool, args):
    server_with()
    out = getattr(server_mod, tool)(**args)
    assert "No propagation datasets are installed" in out
    assert "ionis-download" in out


@pytest.mark.parametrize("tool,args", [
    (t, {**a, "source": "pskr"}) for t, a in SIGNATURE_TOOLS if t != "compare_sources"
])
def test_a_missing_source_names_it_and_how_to_get_it(server_with, tool, args):
    server_with(WSPR_ROWS)  # only WSPR installed
    out = getattr(server_mod, tool)(**args)
    assert "The pskr dataset is not installed" in out
    assert "ionis-download --datasets pskr" in out


def test_an_unknown_source_is_an_error(server_with):
    server_with(WSPR_ROWS)
    assert "Unknown source 'wsrp'" in server_mod.band_summary(107, source="wsrp")


def test_installed_but_no_observations_is_an_honest_empty_answer(server_with):
    server_with(WSPR_ROWS)
    out = server_mod.band_summary(104)  # 60m: installed, no rows
    assert out.startswith("No data found")
    out = server_mod.path_analysis("DN13", "IO91")
    assert "No signatures found" in out


def test_solar_history_names_the_command(server_with):
    server_with(WSPR_ROWS)
    assert "ionis-download --datasets solar" in server_mod.solar_history("2026-03-01", "2026-03-02")


# ── #17 ──────────────────────────────────────────────────────────────────────

BAD_SFI = [
    # tx, rx, band, hr, mo, snr, spots, std, rel, sfi, kp, dist, azm
    ("DN13", "JO51", 107, 14, 3, -6.0, 100, 2.0, 0.5, 938.6, 2.0, 8500, 35.0),
    ("DN13", "JO51", 107, 15, 3, -6.0, 100, 2.0, 0.5, 0.0, 2.0, 8500, 35.0),
    ("DN13", "JO51", 107, 16, 3, -6.0, 100, 2.0, 0.5, 400.0, 2.0, 8500, 35.0),  # the edge: kept
]


def test_plausible_sfi():
    assert plausible_sfi(50) and plausible_sfi(400) and plausible_sfi(135.5)
    assert not plausible_sfi(0) and not plausible_sfi(49.9) and not plausible_sfi(938.6)
    assert not plausible_sfi(None)


def test_band_summary_range_ignores_bad_sfi_and_says_so(server_with):
    server_with(WSPR_ROWS + BAD_SFI)
    out = server_mod.band_summary(107)
    assert "**SFI range**: 72 – 400" in out
    assert "**SFI unknown**: 2 signatures" in out


def test_band_summary_says_nothing_when_all_sfi_is_good(server_with):
    server_with(WSPR_ROWS)
    assert "SFI unknown" not in server_mod.band_summary(107)


def test_solar_correlation_leaves_bad_sfi_out(server_with):
    mgr = server_with(WSPR_ROWS + BAD_SFI)
    brackets = {b["sfi_bracket"]: b for b in mgr.query_solar_correlation(107, source="wspr")}
    good = sum(1 for r in WSPR_ROWS if r[2] == 107)
    assert sum(b["signatures"] for b in brackets.values()) == good + 1  # 400.0 counts, in 200-400
    assert brackets["200-400"]["signatures"] == 2
    out = server_mod.solar_correlation(107)
    assert "2 signatures with an SFI outside 50–400" in out


def test_band_openings_sfi_average_skips_bad_values(server_with):
    rows = [
        ("DN13", "JO51", 107, 14, 3, -6.0, 100, 2.0, 0.5, 120.0, 2.0, 8500, 35.0),
        ("DN13", "JO51", 107, 14, 6, -6.0, 100, 2.0, 0.5, 0.0, 2.0, 8500, 35.0),
        ("DN13", "JO51", 107, 15, 3, -6.0, 100, 2.0, 0.5, 938.6, 2.0, 8500, 35.0),
    ]
    mgr = server_with(rows)
    hourly = {h["hour"]: h for h in mgr.query_band_openings("DN13", "JO51", 107)}
    assert hourly[14]["avg_sfi"] == 120.0  # not diluted to 60 by the 0
    assert hourly[14]["total_spots"] == 200  # the spots still count
    assert hourly[15]["avg_sfi"] is None
    assert "| 15z | -6.0 | 100 | 0.500 | — |" in server_mod.band_openings("DN13", "JO51", 107)


def test_rows_show_bad_sfi_as_unknown(server_with):
    server_with(BAD_SFI)
    out = server_mod.query_signatures(band=107)
    assert "938" not in out and "| 400 |" in out
