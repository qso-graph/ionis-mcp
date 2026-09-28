<!-- mcp-name: io.github.qso-graph/ionis-mcp -->
# ionis-mcp

[![PyPI](https://img.shields.io/pypi/v/ionis-mcp?label=PyPI&color=blue)](https://pypi.org/project/ionis-mcp/)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%3Fsearch%3Dio.github.qso-graph%2Fionis-mcp%26version%3Dlatest&query=%24.servers%5B0%5D.server.version&label=MCP%20Registry&color=blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.qso-graph/ionis-mcp&version=latest)

MCP server for HF radio propagation analytics on the [IONIS-AI](https://ionis-ai.com/) datasets — 175M+ aggregated signatures derived from 14 billion WSPR, RBN, contest, DXpedition and PSK Reporter observations, 2005–2026 — through any MCP-compatible AI assistant.

Part of the [qso-graph](https://qso-graph.io/) project. **No authentication required.** The datasets are downloaded once (see [Datasets](#datasets)).

## Install

```bash
pip install ionis-mcp
ionis-download --bundle minimal   # ~430 MB; see Datasets for the other bundles
```

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `list_datasets` | Available datasets with row counts and file sizes | — |
| `query_signatures` | Signature lookup filtered by source, band, grid, hour, month | source, band, tx_grid, rx_grid, hour, month |
| `band_openings` | Hour-by-hour propagation profile for a path on one band | tx_grid, rx_grid, band |
| `path_analysis` | A path across all bands, hours, months and sources | tx_grid, rx_grid, source |
| `solar_correlation` | Solar flux effect on propagation, by SFI bracket | band, tx_grid, rx_grid |
| `grid_info` | Maidenhead grid decode with solar elevation | grid, hour, month |
| `compare_sources` | Cross-dataset comparison (WSPR vs RBN vs contest vs PSKR) | tx_grid, rx_grid, band |
| `dark_hour_analysis` | Paths by solar geometry: both-day, cross-terminator, both-dark | band, hour, month |
| `solar_history` | Historical solar indices for a date range | start_date, end_date, resolution |
| `band_summary` | Band overview: hour distribution, top grid pairs, distances | band, source |
| `current_conditions` | Live forecast: SFI, Kp, solar wind, band outlook, POTA/SOTA tips | qth_grid |
| `get_version_info` | Service version + upstream spec version (fleet identity attestation) | — |

## What is IONIS-AI?

IONIS-AI is an open-source machine learning system for predicting HF (shortwave) radio propagation. Its datasets are curated from the world's largest amateur radio telemetry networks and distributed as SQLite files on [SourceForge](https://sourceforge.net/projects/ionis-ai/). ionis-mcp lets an assistant answer propagation questions from them, no SQL required.

| Source | Signatures | Raw Observations | SNR Type | Years |
|--------|-----------|-----------------|----------|-------|
| [WSPR](https://www.wsprnet.org/) | 93.6M | 10.9B beacon spots | Measured (-30 to +20 dB) | 2008-2026 |
| [RBN](https://reversebeacon.net/) | 67.3M | 2.3B CW/RTTY spots | Measured (8-29 dB) | 2009-2026 |
| [CQ Contests](https://cqww.com/) | 5.7M | 234M SSB/RTTY QSOs | Anchored (+10/0 dB) | 2005-2025 |
| [DXpeditions](https://www.ng3k.com/misc/adxo.html) | 260K | 3.9M rare-grid paths | Measured | 2009-2025 |
| [PSK Reporter](https://pskreporter.info/) | 8.4M | 514M+ FT8/WSPR spots | Measured (-34 to +38 dB) | Feb 2026+ |
| Solar Indices | — | 77K daily/3-hour records | SFI, SSN, Kp, Ap | 2000-2026 |
| DSCOVR L1 | — | 23K solar wind samples | Bz, speed, density | Feb 2026+ |

All signature tables share an identical 13-column schema (tx\_grid, rx\_grid, band, hour, month, median\_snr, spot\_count, snr\_std, reliability, avg\_sfi, avg\_kp, avg\_distance, avg\_azimuth) — ready for cross-source analysis.

## Datasets

```bash
# 1. Install
pip install ionis-mcp

# 2. Download datasets (to default location: ~/.ionis-mcp/data/)
ionis-download --bundle minimal          # ~430 MB — contest + solar + grids
ionis-download --bundle recommended      # ~1.1 GB — adds PSKR + DSCOVR
ionis-download --bundle full             # ~15 GB  — all 9 datasets

# 3. Configure your MCP client (see Quick Start) and restart
```

That's it. Both `ionis-download` and `ionis-mcp` use the same default data directory. No environment variables needed.

### Default data directory

| Platform | Location |
|----------|----------|
| Linux / macOS | `~/.ionis-mcp/data/` |
| Windows | `%LOCALAPPDATA%\ionis-mcp\data\` |

Override with a custom path:

```bash
# Download to custom location
ionis-download --bundle minimal /path/to/my/data

# Tell the server where to find it
ionis-mcp --data-dir /path/to/my/data
# or
export IONIS_DATA_DIR=/path/to/my/data
```

### Download individual datasets

```bash
# Pick specific datasets
ionis-download --datasets wspr,rbn,grids,solar

# See all available datasets and bundles
ionis-download --list

# Re-download (overwrite existing)
ionis-download --bundle minimal --force
```

### Data directory layout

```
~/.ionis-mcp/data/                  (or $IONIS_DATA_DIR)
├── propagation/
│   ├── wspr-signatures/wspr_signatures_v2.sqlite      (8.4 GB, 93.6M rows)
│   ├── rbn-signatures/rbn_signatures.sqlite            (5.6 GB, 67.3M rows)
│   ├── contest-signatures/contest_signatures.sqlite    (424 MB, 5.7M rows)
│   ├── dxpedition-signatures/dxpedition_signatures.sqlite (22 MB, 260K rows)
│   └── pskr-signatures/pskr_signatures.sqlite          (606 MB, 8.4M rows)
├── solar/
│   ├── solar-indices/solar_indices.sqlite               (7.7 MB, 76.7K rows)
│   └── dscovr/dscovr_l1.sqlite                         (2.9 MB, 23K rows)
└── tools/
    ├── grid-lookup/grid_lookup.sqlite                   (1.1 MB, 31.7K rows)
    └── balloon-callsigns/balloon_callsigns_v2.sqlite    (116 KB, 1.5K rows)
```

The server works with whatever datasets are present. Missing datasets degrade gracefully — tools that need unavailable data return clear messages instead of errors.

## Quick Start

### Configure your MCP client

ionis-mcp works with any MCP-compatible client. Add the server config and restart. The tools appear automatically.

If you downloaded data to a custom location, add `"env": { "IONIS_DATA_DIR": "/path/to/data" }` to any config below.

#### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

#### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

#### ChatGPT Desktop

ChatGPT supports MCP via the [OpenAI Agents SDK](https://developers.openai.com/api/docs/mcp/). Add under Settings > Apps & Connectors, or configure in your agent definition:

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

#### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

#### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

```json
{
  "mcpServers": {
    "ionis": {
      "command": "ionis-mcp"
    }
  }
}
```

### Ask questions

> "When is 20m open from Idaho to Europe?"

> "How does solar flux affect 15m propagation?"

> "Show me 10m paths at 03z where both stations are in the dark"

> "Compare WSPR and RBN observations on 20m FN31 to JO51"

> "What are the current band conditions? I'm heading out for POTA."

> "What were the solar conditions during the February 2026 geomagnetic storm?"

## Architecture

- **Transport**: stdio (Claude Desktop / Claude Code) or streamable-http (MCP Inspector)
- **Database**: Read-only `sqlite3` connections (`?mode=ro`) — no writes, ever
- **Query safety**: All queries use parameterized SQL (`?` placeholders), result limits enforced server-side (max 1000 rows)
- **Grid lookup**: 31.7K Maidenhead grids loaded into memory at startup (~2 MB) for instant lat/lon resolution
- **Solar geometry**: Pure Python solar elevation computation (same algorithm as the IONIS-AI training pipeline) — classifies endpoints as day/twilight/night for propagation context
- **Cross-source queries**: Each SQLite database opened separately, results merged in Python with source labels

## MCP Inspector

```bash
ionis-mcp --transport streamable-http --port 8000
```

Then open the MCP Inspector at `http://localhost:8000/mcp`.

## Development

```bash
git clone https://github.com/qso-graph/ionis-mcp.git
cd ionis-mcp
pip install -e .
pytest
```

## Related Projects

| Repository | Purpose |
|-----------|---------|
| [ionis-validate](https://pypi.org/project/ionis-validate/) | IONIS-AI model validation suite (PyPI) |
| [IONIS-AI datasets](https://sourceforge.net/projects/ionis-ai/) | Distributed dataset files (SourceForge) |

## License

GPL-3.0-or-later

## Citation

If you use the IONIS-AI datasets in research, please cite:

> Beam, G. (KI7MT). *IONIS: Ionospheric Neural Inference System — HF Propagation Prediction Datasets.* SourceForge, 2026. https://sourceforge.net/projects/ionis-ai/
